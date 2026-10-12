"""大麦演出详情页（detail.damai.cn）操作。

大麦前端改版频繁，所有候选选择器集中在此文件；每个操作都有多条定位策略，
按顺序尝试，全部失败时抛出带中文说明的异常。
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, TimeoutError as PwTimeout

# 购买按钮候选选择器（按优先级）
# 新版 PC UI：购票入口是 .buy-link（文案"不，立即购票"），旧版才是 .buybtn
BUY_BUTTON_SELECTORS = [
    ".buy-link",
    ".buybtn",
    ".buy-btn",
    "[class*='buybtn']",
]

# 数量加减控件（新版 PC UI，详情页上直接选张数）
PLUS_BUTTON_SELECTORS = [
    ".cafe-c-input-number-handler-up",
    ".number_right",
]
QUANTITY_INPUT_SELECTORS = [
    ".cafe-c-input-number-input",
]

# 按钮文案：可点击状态 / 不可点击状态
CLICKABLE_TEXTS = ("不，立即购票", "立即购买", "立即预订", "立即抢购", "立即预定")
SEAT_SELECT_TEXTS = ("不，选座购票", "选座购买")
DISABLED_TEXTS = ("即将开抢", "即将开售", "缺货登记", "已售罄", "售罄", "暂缺货", "开售提醒", "预售")

# 场次/票档选项的候选选择器
OPTION_ITEM_SELECTORS = [
    ".select_right_list_item",
    ".perform__order__select__performs__perform",
    "[class*='perform-item']",
    "[class*='sku-item']",
    "[class*='select_right_list'] [class*='item']",
]


class DetailPageError(Exception):
    """详情页操作失败（中文提示）"""


class AppOnlyError(Exception):
    """该演出仅支持手机端购买，网页方案不适用"""


class DetailPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    # ---------- 基础工具 ----------

    def _first_visible(self, selectors: list[str], timeout_ms: int = 1500) -> Locator | None:
        """按顺序尝试候选选择器，返回第一个可见的 Locator"""
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except PwTimeout:
                continue
        return None

    def is_app_only(self) -> bool:
        """该演出是否仅支持手机端购买（页面显示"该渠道不支持购买"+ App 二维码）"""
        try:
            if self.page.locator(".unsale").first.is_visible(timeout=1500):
                return True
        except PwTimeout:
            pass
        except Exception:
            pass
        try:
            return self.page.get_by_text("该渠道不支持购买").first.is_visible(timeout=1000)
        except Exception:
            return False

    # ---------- 场次 / 票档选择 ----------

    def select_option(self, keyword: str, area_name: str) -> None:
        """按关键字模糊匹配选择场次或票档。

        策略一：候选选项选择器 + 文本过滤；策略二：全页文本定位兜底。
        选中后若元素带 disabled 类会给出警告（可能未开售，属正常）。
        """
        # 策略一：结构化选项定位
        for selector in OPTION_ITEM_SELECTORS:
            item = self.page.locator(selector).filter(has_text=keyword).first
            try:
                item.wait_for(state="visible", timeout=1000)
            except PwTimeout:
                continue
            cls = item.get_attribute("class") or ""
            if "disabled" in cls:
                print(f"[详情页] 警告：{area_name}『{keyword}』当前不可选（未开售或无票），仍尝试点击")
            item.click(force=True)
            print(f"[详情页] 已选择{area_name}：{keyword}")
            return

        # 策略二：文本兜底
        text_item = self.page.get_by_text(keyword, exact=False).first
        try:
            text_item.wait_for(state="visible", timeout=2000)
            text_item.click(force=True)
            print(f"[详情页] 已通过文本定位选择{area_name}：{keyword}")
            return
        except PwTimeout:
            pass

        raise DetailPageError(
            f"在详情页找不到{area_name}『{keyword}』，请检查 config.yaml 中的关键字是否与页面文字一致"
        )

    def select_session(self, keyword: str) -> None:
        self.select_option(keyword, "场次")

    def select_ticket(self, keyword: str) -> None:
        self.select_option(keyword, "票档")

    # ---------- 购买按钮 ----------

    def buy_button(self) -> Locator | None:
        """返回购买按钮 Locator，找不到返回 None"""
        button = self._first_visible(BUY_BUTTON_SELECTORS, timeout_ms=800)
        if button is not None:
            return button
        # 文本兜底
        pattern = "|".join(CLICKABLE_TEXTS + SEAT_SELECT_TEXTS + DISABLED_TEXTS)
        text_btn = self.page.get_by_text(re.compile(f"^({pattern})$")).first
        try:
            text_btn.wait_for(state="visible", timeout=800)
            return text_btn
        except PwTimeout:
            return None

    def buy_button_text(self) -> str:
        """当前购买按钮文案，找不到按钮返回空串"""
        button = self.buy_button()
        if button is None:
            return ""
        try:
            return (button.inner_text(timeout=800) or "").strip()
        except PwTimeout:
            return ""

    def is_buy_clickable(self) -> bool:
        """按钮是否处于可购买状态（文案为立即购买/预订类）"""
        text = self.buy_button_text()
        return any(t in text for t in CLICKABLE_TEXTS)

    def is_sold_out(self) -> bool:
        """按钮是否显示售罄/缺货"""
        text = self.buy_button_text()
        return any(t in text for t in ("缺货登记", "已售罄", "售罄", "暂缺货"))

    def is_seat_select(self) -> bool:
        """是否为选座购买流程（需在座位图选座，当前版本不支持）"""
        text = self.buy_button_text()
        return any(t in text for t in SEAT_SELECT_TEXTS)

    def set_quantity(self, target: int) -> None:
        """在详情页把购票数量调到 target（新版 UI 的数量控件在详情页上）"""
        if target <= 1:
            return
        plus = self._first_visible(PLUS_BUTTON_SELECTORS, timeout_ms=1000)
        if plus is None:
            print("[详情页] 警告：未找到数量加号控件，保持默认 1 张")
            return
        for _ in range(target - 1):
            try:
                plus.click(timeout=800)
                self.page.wait_for_timeout(150)
            except Exception:
                break
        try:
            value = self.page.locator(QUANTITY_INPUT_SELECTORS[0]).first.input_value(timeout=800)
            print(f"[详情页] 数量已设为：{value} 张")
        except Exception:
            print(f"[详情页] 数量加号已点击 {target - 1} 次（未能读回核对）")

    def click_buy(self) -> None:
        """点击购买按钮"""
        button = self.buy_button()
        if button is None:
            raise DetailPageError("详情页找不到购买按钮，页面可能已改版，请更新 detail_page.py 中的选择器")
        button.click(force=True)
