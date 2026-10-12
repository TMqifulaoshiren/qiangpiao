"""大麦订单确认页（buy.damai.cn）操作。

注意：支付环节（密码/人脸）不自动化。本文件只负责到"提交订单"为止。
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, TimeoutError as PwTimeout

# 数量"+"按钮候选选择器
PLUS_BUTTON_SELECTORS = [
    ".cafe-c-number-handler-up",
    ".item-add",
    "[class*='plus']",
    "[class*='add']",
    ".next-icon-add",
]

# 提交订单按钮候选选择器
SUBMIT_SELECTORS = [
    ".submit-wrapper .submit-btn",
    ".submit-btn",
    "[class*='submit']",
]

# 验证码/风控容器候选选择器
CAPTCHA_SELECTORS = [
    "#baxia-dialog-content",
    ".baxia-dialog",
    "#nocaptcha",
    ".nc-container",
    "iframe[src*='captcha']",
    "#nc_1_wrapper",
]

# 提交成功的标志文案
SUCCESS_TEXTS = ("提交成功", "立即支付", "去支付", "支付订单", "订单号")


class OrderPageError(Exception):
    """订单页操作失败（中文提示）"""


class OrderPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def wait_ready(self, timeout_ms: int = 15000) -> None:
        """等待订单确认页加载完成"""
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except PwTimeout:
            pass
        # 出现提交按钮或验证码任一个即视为"到达"
        for _ in range(int(timeout_ms / 500)):
            if self.submit_button() is not None or self.has_captcha():
                return
            self.page.wait_for_timeout(500)
        raise OrderPageError("订单确认页加载超时，未找到提交按钮，页面可能已改版")

    # ---------- 验证码检测（只检测不破解，提醒人工处理） ----------

    def has_captcha(self) -> bool:
        for selector in CAPTCHA_SELECTORS:
            try:
                if self.page.locator(selector).first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def wait_captcha_solved(self) -> None:
        """检测到验证码时响铃提醒人工处理，直到验证码消失"""
        if not self.has_captcha():
            return
        from src.notify import Notifier

        notifier = Notifier()
        notifier.start("检测到滑块验证码，请在浏览器中手动完成验证！")
        try:
            while self.has_captcha():
                self.page.wait_for_timeout(500)
        finally:
            notifier.stop()
        print("[订单页] 验证码已人工通过，继续")

    # ---------- 数量与观演人 ----------

    def set_quantity(self, target: int) -> None:
        """尽力把票数调到 target；找不到控件时警告并保持默认（通常为 1）"""
        if target <= 1:
            return
        plus = self._first_visible(PLUS_BUTTON_SELECTORS)
        if plus is None:
            print(f"[订单页] 警告：找不到数量加号控件，保持默认数量，请手动调整为 {target} 张")
            return
        for _ in range(target - 1):
            try:
                plus.click(timeout=1000)
                self.page.wait_for_timeout(150)
            except Exception:
                break
        print(f"[订单页] 已尝试将数量调整为 {target} 张（请在提交前肉眼核对）")

    def _first_visible(self, selectors: list[str], timeout_ms: int = 1200) -> Locator | None:
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except PwTimeout:
                continue
        return None

    def check_viewers(self, count: int) -> None:
        """勾选观演人（如页面要求）。尽力而为：部分演出会自动带上常用观演人"""
        viewer_items = self.page.locator(
            "[class*='viewer'] [class*='item'], [class*='guanyingren'] [class*='item'], "
            "[class*='customer'] [class*='item']"
        )
        try:
            total = viewer_items.count()
        except Exception:
            total = 0
        if total == 0:
            return
        checked = 0
        for i in range(total):
            if checked >= count:
                break
            item = viewer_items.nth(i)
            cls = (item.get_attribute("class") or "") + " " + (item.inner_html() or "")
            if "checked" in cls or "selected" in cls or "active" in cls:
                checked += 1
                continue
            try:
                item.click(timeout=800)
                checked += 1
            except Exception:
                continue
        print(f"[订单页] 观演人已勾选 {checked} 人")

    # ---------- 提交与结果判定 ----------

    def submit_button(self) -> Locator | None:
        button = self._first_visible(SUBMIT_SELECTORS, timeout_ms=800)
        if button is not None:
            return button
        text_btn = self.page.get_by_text(re.compile("^提交订单$")).first
        try:
            text_btn.wait_for(state="visible", timeout=800)
            return text_btn
        except PwTimeout:
            return None

    def click_submit(self) -> None:
        button = self.submit_button()
        if button is None:
            raise OrderPageError("找不到提交订单按钮，页面可能已改版，请更新 order_page.py 中的选择器")
        button.click(force=True)
        print("[订单页] 已点击提交订单")

    def is_submitted(self) -> bool:
        """提交成功判定：跳转到支付页或出现成功文案"""
        url = self.page.url
        if "pay" in url or "cashier" in url:
            return True
        try:
            body_text = self.page.locator("body").inner_text(timeout=1500)
        except Exception:
            return False
        return any(t in body_text for t in SUCCESS_TEXTS)

    def has_stock_problem(self) -> bool:
        """订单页提示无票/库存不足"""
        try:
            body_text = self.page.locator("body").inner_text(timeout=1500)
        except Exception:
            return False
        return any(t in body_text for t in ("库存不足", "已售罄", "无票", "缺货", "没有票"))
