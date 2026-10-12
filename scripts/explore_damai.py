"""大麦演出探索工具（辅助脚本，不参与抢票主流程）。

用法：
    python scripts/explore_damai.py list              # 搜索在售演唱会，列出候选
    python scripts/explore_damai.py detail <url>      # 读取某演出的场次/票档/按钮状态
"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

# Windows 控制台输出中文
sys.stdout.reconfigure(encoding="utf-8")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 与 src/pages/detail_page.py 保持一致的选项选择器
OPTION_ITEM_SELECTORS = [
    ".select_right_list_item",
    ".perform__order__select__performs__perform",
    "[class*='perform-item']",
    "[class*='sku-item']",
]


def list_shows() -> None:
    """搜索在售演唱会并列出候选（标题/链接/低价）"""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(user_agent=UA, locale="zh-CN")
        url = "https://search.damai.cn/search.htm?keyword=%E6%BC%94%E5%94%B1%E4%BC%9A&ctl=%E6%BC%94%E5%94%B1%E4%BC%9A"
        print(f"[list] 打开搜索页：{url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # 提取所有指向详情页的链接及其上下文文本
        anchors = page.locator("a[href*='detail.damai.cn/item.htm'], a[href*='/item.htm?id=']")
        count = anchors.count()
        print(f"[list] 找到 {count} 个详情链接")

        seen: set[str] = set()
        shown = 0
        for i in range(count):
            if shown >= 15:
                break
            a = anchors.nth(i)
            try:
                href = a.get_attribute("href") or ""
                if not re.search(r"id=(\d+)", href):
                    continue
                item_id = re.search(r"id=(\d+)", href).group(1)
                if item_id in seen:
                    continue
                # 向上找容器，取整块文本（含标题/价格/状态）
                container = a.locator("xpath=ancestor-or-self::*[contains(@class,'item')][1]")
                text = ""
                try:
                    text = container.inner_text(timeout=800)
                except Exception:
                    text = a.inner_text(timeout=800)
                text = " | ".join(t.strip() for t in text.splitlines() if t.strip())
                if not href.startswith("http"):
                    href = "https:" + href if href.startswith("//") else "https://detail.damai.cn/item.htm?id=" + item_id
                seen.add(item_id)
                shown += 1
                print(f"\n--- 候选 {shown} (id={item_id}) ---")
                print(f"链接: {href}")
                print(f"信息: {text[:200]}")
            except Exception:
                continue

        browser.close()


def show_detail(show_url: str) -> None:
    """读取演出详情页：场次、票档、购买按钮状态（有头模式规避反爬）"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(locale="zh-CN")
        print(f"[detail] 打开：{show_url}")
        page.goto(show_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        title = page.title()
        print(f"[detail] 标题：{title}")

        # 逐个选择器尝试读取选项文本
        for selector in OPTION_ITEM_SELECTORS:
            items = page.locator(selector)
            n = items.count()
            if n == 0:
                continue
            print(f"\n[detail] 选择器 {selector} 命中 {n} 项：")
            for i in range(min(n, 30)):
                item = items.nth(i)
                try:
                    text = (item.inner_text(timeout=500) or "").strip().replace("\n", " ")
                    cls = item.get_attribute("class") or ""
                    flag = " [不可选]" if "disabled" in cls else ""
                    if text:
                        print(f"  {i + 1}. {text}{flag}")
                except Exception:
                    continue
            break  # 第一个命中的选择器即为主结构

        # 购买按钮状态
        for selector in (".buybtn", ".buy-btn", "[class*='buybtn']"):
            btn = page.locator(selector).first
            try:
                if btn.is_visible():
                    print(f"\n[detail] 购买按钮（{selector}）：『{(btn.inner_text(timeout=800) or '').strip()}』")
                    break
            except Exception:
                continue
        else:
            print("\n[detail] 未通过 class 找到购买按钮")

        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "list":
        list_shows()
    elif sys.argv[1] == "detail" and len(sys.argv) >= 3:
        show_detail(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
