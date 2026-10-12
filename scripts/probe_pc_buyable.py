"""探测脚本：批量判断演出是否支持电脑网页购买，并导出票档与按钮状态。

用法：python scripts/probe_pc_buyable.py <详情页URL1> [URL2 ...]
判定结果：BLOCKED（风控）/ APP_ONLY（仅手机端）/ PC_BUYABLE（支持网页购买）
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from src.browser import launch_context  # noqa: E402
from src.pages.detail_page import OPTION_ITEM_SELECTORS  # noqa: E402


def probe(page, url: str) -> None:
    print(f"\n########## {url}")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    title = page.title()
    if "拒绝" in title or "punish" in page.url:
        print("判定：BLOCKED（风控拦截）")
        return

    try:
        unsale = page.locator(".unsale").first.is_visible(timeout=1500)
    except Exception:
        unsale = False
    if unsale or "该渠道不支持购买" in (page.locator("body").inner_text(timeout=2000) or ""):
        print("判定：APP_ONLY（仅手机端购买）")
        return

    print(f"判定：PC_BUYABLE  标题：{title}")

    # 导出票档/场次选项
    for selector in OPTION_ITEM_SELECTORS:
        items = page.locator(selector)
        n = items.count()
        if n == 0:
            continue
        print(f"  [选择器 {selector}] 命中 {n} 项：")
        for i in range(min(n, 30)):
            try:
                text = (items.nth(i).inner_text(timeout=500) or "").strip().replace("\n", " ")
                cls = items.nth(i).get_attribute("class") or ""
                flag = " [不可选]" if "disabled" in cls else ""
                if text:
                    print(f"    {i + 1}. 『{text}』{flag}")
            except Exception:
                continue
        break

    # 购买按钮状态
    for selector in (".buybtn", ".buy-btn", "[class*='buybtn']"):
        btn = page.locator(selector).first
        try:
            if btn.is_visible():
                print(f"  购买按钮：『{(btn.inner_text(timeout=800) or '').strip()}』")
                return
        except Exception:
            continue
    print("  购买按钮：未通过 class 找到")


def main() -> None:
    urls = sys.argv[1:]
    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()
        # 预热一次首页
        page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        for url in urls:
            try:
                probe(page, url)
            except Exception as e:
                print(f"探测异常：{type(e).__name__}: {e}")
        context.close()


if __name__ == "__main__":
    main()
