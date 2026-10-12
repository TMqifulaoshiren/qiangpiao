"""抢票主流程状态机：prepare → wait → grab → order → done/fail。"""

from __future__ import annotations

import random
import time

from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.browser import ensure_login, launch_context
from src.config import Config
from src.notify import Notifier, countdown_sleep
from src.pages.detail_page import AppOnlyError, DetailPage, DetailPageError
from src.pages.order_page import OrderPage, OrderPageError
from src.time_sync import TimeSync


class Grabber:
    def __init__(self, cfg: Config, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.notifier = Notifier()

    # ========== 入口 ==========

    def run(self) -> bool:
        """执行完整流程，返回是否成功到达订单提交（dry-run 为到达订单页）"""
        with sync_playwright() as p:
            context = launch_context(p)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                self._prepare(page, context)
                if self.dry_run:
                    print("[模式] dry-run：跳过开售等待，立即执行抢票链路（到订单页即停）")
                else:
                    self._wait_for_sale()
                return self._grab_and_order(context, page)
            except Exception as e:
                # 异常立即打印，不等浏览器关闭
                print(f"\n[流程异常] {type(e).__name__}: {e}")
                raise
            finally:
                self.notifier.stop()
                self._wait_user_done(context)
                try:
                    context.close()
                except Exception:
                    pass

    def _wait_user_done(self, context: BrowserContext) -> None:
        """等待用户确认结束：有终端时按回车；后台运行时保持浏览器打开直到用户手动关窗"""
        print("[结束] 登录态已保存，下次免扫码。")
        try:
            input("核对完成后按回车关闭浏览器……")
        except EOFError:
            print("[提示] 非交互模式：浏览器保持打开，请手动关闭浏览器窗口结束脚本")
            while True:
                try:
                    if not context.pages:
                        break
                    time.sleep(2)
                except Exception:
                    break

    # ========== 阶段一：准备 ==========

    def _prepare(self, page: Page, context: BrowserContext) -> None:
        try:
            page.bring_to_front()
        except Exception:
            pass

        # 先访问首页"预热"，建立自然浏览轨迹，降低直接命中详情页被风控的概率
        print("[准备] 先打开大麦首页预热……")
        page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        # 未登录时先扫码
        ensure_login(context, page, self.cfg.show_url)

        print("[准备] 打开演出详情页……")
        self._goto_detail_with_anti_block(page)

        detail = DetailPage(page)
        if detail.is_app_only():
            raise AppOnlyError(
                "该演出仅支持手机端购买（页面提示『该渠道不支持购买』），网页抢票方案不适用。"
                "请换一场支持电脑购买的演出，或改走 Android 手机自动化方案"
            )
        self._select_skus(page, detail)

        if detail.is_seat_select():
            raise RuntimeError(
                "该演出是『选座购买』流程（要点进座位图选座），当前版本只支持直购演出。"
                "请换一场直购演出（购票区显示数量选择+『不，立即购票』）"
            )

        button_text = detail.buy_button_text()
        print(f"[准备] 就绪，当前购买按钮状态：『{button_text or '未找到'}』")

        # 预热购买链路：新版 PC 购票走 H5 下单流程，登录态与 www 首页独立，需提前激活
        # （仅在购买按钮可点时预热；未开售时点了也不会跳转，开售瞬间再由 _locate_order_page 兜底登录）
        if self.dry_run or detail.is_buy_clickable():
            self._prime_buy_session(context, page, detail)
        else:
            print("[准备] 按钮暂不可点（未开售），跳过购买链路预热；开售瞬间如跳登录页会响铃提醒")

    # 订单页 URL 特征（新版 H5 下单页 / 旧版 PC 下单页）
    ORDER_URL_MARKERS = ("ultron-buy", "buy.damai.cn", "orderconfirm", "order/confirm")

    def _is_order_url(self, url: str) -> bool:
        u = (url or "").lower()
        return any(m in u for m in self.ORDER_URL_MARKERS) and "passport" not in u

    def _locate_order_page(
        self, context: BrowserContext, page: Page, pages_before: set, timeout_s: int = 30
    ) -> Page:
        """点击购买后定位订单确认页；中途遇到独立登录页则响铃等人工登录，遇到验证码等人工过验证"""
        login_prompted = False
        deadline = time.time() + timeout_s

        while True:
            new_pages = [pg for pg in context.pages if pg not in pages_before]
            candidates = new_pages + [page]

            for pg in candidates:
                try:
                    if self._is_order_url(pg.url):
                        return pg
                except Exception:
                    continue

            on_login = any("passport.damai.cn" in (pg.url or "") for pg in candidates)
            if on_login:
                if not login_prompted:
                    login_prompted = True
                    self.notifier.start(
                        "购票流程需要单独登录：请在浏览器窗口完成登录（建议扫码登录），"
                        "登录成功进入订单页后脚本自动继续"
                    )
                    deadline = time.time() + 300  # 给出 5 分钟登录时间
                page.wait_for_timeout(1000)
                if time.time() > deadline:
                    raise OrderPageError("等待购票流程登录超时（5 分钟）")
                continue

            probe = new_pages[0] if new_pages else page
            if OrderPage(probe).has_captcha():
                OrderPage(probe).wait_captcha_solved()
                continue

            if time.time() > deadline:
                raise OrderPageError(
                    f"点击购买后 {timeout_s} 秒内未进入订单确认页，当前页面：{page.url[:80]}"
                )
            page.wait_for_timeout(500)

    def _prime_buy_session(self, context: BrowserContext, page: Page, detail: DetailPage) -> None:
        """提前点一次购买入口，激活 H5 下单流程的登录态，然后回到详情页待命"""
        pages_before = set(context.pages)
        print("[准备] 预热购买链路（首次可能需要在弹窗/新页单独登录）……")
        detail.click_buy()
        order_page = self._locate_order_page(context, page, pages_before, timeout_s=20)
        self.notifier.stop()
        print("[准备] 购买链路登录态已激活（已到过一次订单页）")

        # 回到详情页重新选座档（跳转会清空选择状态）
        if order_page is not page:
            # 极少见：开在新标签页。关掉新页，用原页回详情页（Cookie 已在上下文生效）
            try:
                order_page.close()
            except Exception:
                pass
        page.goto(self.cfg.show_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self._select_skus(page, detail)
        print(f"[准备] 已回到详情页待命，按钮状态：『{detail.buy_button_text() or '未找到'}』")

    def _select_skus(self, page: Page, detail: DetailPage) -> None:
        """选择场次+票档+数量（每次刷新后都需重选，刷新会清空已选状态）"""
        detail.select_session(self.cfg.session)
        page.wait_for_timeout(500)
        detail.select_ticket(self.cfg.ticket)
        page.wait_for_timeout(500)
        detail.set_quantity(self.cfg.quantity)

    def _is_blocked(self, page: Page) -> bool:
        """判断当前页是否为大麦反爬拦截页（访问被拒绝 / 安全验证 / punish 跳转）"""
        url = page.url
        if "punish" in url or "bixi.alicdn.com" in url or "_____tmd_____" in url:
            return True
        try:
            title = page.title()
        except Exception:
            title = ""
        return ("拒绝" in title) or ("访问被拒" in title) or ("验证" in title and "detail.damai.cn" not in url)

    def _goto_detail_with_anti_block(self, page: Page, max_rounds: int = 3) -> None:
        """打开详情页；若命中风控拦截，响铃提醒人工过验证，处理后自动重试。

        每轮之间会重新走一遍首页预热，尽量恢复自然访问轨迹。
        """
        for round_no in range(1, max_rounds + 1):
            page.goto(self.cfg.show_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            if not self._is_blocked(page) and "detail.damai.cn" in page.url:
                title = page.title()
                print(f"[准备] 详情页已打开：『{title}』")
                return

            # 命中拦截：提醒人工处理
            print(f"[准备] 第 {round_no} 次访问被风控拦截，等待人工过验证……")
            self.notifier.start(
                f"大麦风控拦截（第{round_no}次）：请在浏览器窗口手动完成滑块/验证，"
                "或直接手动刷新到能正常显示演出详情，脚本会自动继续"
            )
            # 最长等 3 分钟，期间检测到恢复正常即继续
            for _ in range(180):
                page.wait_for_timeout(1000)
                if not self._is_blocked(page) and "detail.damai.cn" in page.url:
                    break
            self.notifier.stop()

            if not self._is_blocked(page) and "detail.damai.cn" in page.url:
                print("[准备] 验证已通过，详情页恢复正常")
                return

            # 仍未恢复，重新预热首页再试
            if round_no < max_rounds:
                print("[准备] 重新访问首页预热后再试……")
                try:
                    page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)
                except Exception:
                    pass

        raise RuntimeError(
            f"连续 {max_rounds} 次被大麦风控拦截。建议：1) 换网络环境（如手机热点，避开被标记的 IP）；"
            "2) 手动在窗口里把详情页刷出来后再运行；3) 稍等一段时间再试"
        )

    # ========== 阶段二：等待开售 ==========

    def _wait_for_sale(self) -> None:
        print("[校准] 正在与大麦服务器对时……")
        time_sync = TimeSync.calibrate(self.cfg.show_url)
        print(f"[校准] 完成：本地时钟偏移 {time_sync.offset * 1000:+.0f}ms（RTT {time_sync.rtt_ms:.0f}ms）")

        sale_ts = self.cfg.sale_timestamp
        remain = sale_ts - time_sync.now()
        if remain <= 0:
            print(f"[等待] 开售时间已过 {-remain:.0f} 秒，直接进入抢票")
            return
        print(f"[等待] 开售时间：{self.cfg.sale_time} ，开始倒计时……")
        # 提前 0.3 秒进入检测循环（刷新本身有耗时）
        countdown_sleep(sale_ts - 0.3, time_sync.now)
        print("\n[开抢] 时间到！")

    # ========== 阶段三：刷新抢购 ==========

    def _grab_and_order(self, context: BrowserContext, page: Page) -> bool:
        detail = DetailPage(page)
        deadline = time.time() + self.cfg.max_retry_minutes * 60
        attempt = 0

        while time.time() < deadline:
            attempt += 1
            try:
                # 刷新途中命中风控拦截：提醒人工过验证后继续
                if self._is_blocked(page):
                    print("[抢购] 刷新时被风控拦截，等待人工过验证……")
                    self.notifier.start("抢票中被风控拦截，请在浏览器窗口手动完成验证！")
                    for _ in range(180):
                        page.wait_for_timeout(1000)
                        if not self._is_blocked(page):
                            break
                    self.notifier.stop()
                    continue
                if detail.is_sold_out():
                    self._fail("票已售罄/缺货，本次抢票结束")
                    return False
                if detail.is_buy_clickable():
                    print(f"[抢购] 第 {attempt} 次检测：按钮可点击，立即下单！")
                    order_page = self._click_buy_and_locate_order(context, page, detail)
                    return self._handle_order(context, order_page)
                # 按钮未就绪（即将开抢等），刷新重试；刷新会清空已选票档，需重选
                if attempt % 10 == 1:
                    print(f"[抢购] 第 {attempt} 次检测：按钮状态『{detail.buy_button_text() or '未找到'}』，刷新等待……")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(800)
                self._select_skus(page, detail)
            except DetailPageError as e:
                print(f"[抢购] 警告：{e}")
                page.reload(wait_until="domcontentloaded")
            except Exception as e:
                print(f"[抢购] 网络/页面异常：{e}，重试……")
                try:
                    page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass

            # 限速：基础间隔 + 随机抖动，模拟人工节奏
            sleep_ms = self.cfg.refresh_interval_ms + random.randint(0, self.cfg.refresh_jitter_ms)
            page.wait_for_timeout(sleep_ms)

        self._fail(f"重试超过 {self.cfg.max_retry_minutes} 分钟仍未开售/未抢到，已放弃")
        return False

    def _click_buy_and_locate_order(
        self, context: BrowserContext, page: Page, detail: DetailPage
    ) -> Page:
        """点击购买按钮并定位订单确认页（登录/验证码均由 _locate_order_page 统一处理）"""
        pages_before = set(context.pages)
        detail.click_buy()
        return self._locate_order_page(context, page, pages_before, timeout_s=30)

    # ========== 阶段四：订单确认与提交 ==========

    def _handle_order(self, context: BrowserContext, order_page: Page) -> bool:
        order = OrderPage(order_page)
        print("[订单] 已进入订单确认页")
        order.wait_ready()
        order.wait_captcha_solved()

        order.set_quantity(self.cfg.quantity)
        order.check_viewers(self.cfg.quantity)
        order.wait_captcha_solved()

        if order.has_stock_problem():
            self._fail("订单页提示无票/库存不足")
            return False

        if self.dry_run:
            self.notifier.start("dry-run 已到达订单确认页（未提交）。请肉眼核对票档、数量、观演人。")
            print("[dry-run] 不执行提交。")
            self._wait_user_done(context)
            self.notifier.stop()
            return True

        order.click_submit()

        # 等待提交结果（可能再弹验证码）
        for _ in range(40):
            order_page.wait_for_timeout(500)
            order.wait_captcha_solved()
            if order.is_submitted():
                self.notifier.start("订单已提交！请在 15 分钟内到浏览器手动完成付款！")
                print("[成功] 订单已提交，浏览器保持打开，请立即手动付款！")
                return True
            if order.has_stock_problem():
                self._fail("提交订单时无票/库存不足")
                return False

        self._fail("提交订单后 20 秒内未确认结果，请手动查看浏览器订单状态")
        return False

    # ========== 结果处理 ==========

    def _fail(self, reason: str) -> None:
        self.notifier.start(f"抢票失败：{reason}")
        print(f"[失败] {reason}")
