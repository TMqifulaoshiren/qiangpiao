"""诊断：点击购买入口后逐秒记录标签页、URL、弹窗内容，搞清跳转行为。

用法：python scripts/trace_buy_click.py <详情页URL> <场次关键字> <票档关键字>
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from src.browser import launch_context  # noqa: E402
from src.pages.detail_page import DetailPage  # noqa: E402

OUT_DIR = Path("debug_out")


def main() -> None:
    url, session_kw, ticket_kw = sys.argv[1], sys.argv[2], sys.argv[3]
    OUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        detail = DetailPage(page)
        detail.select_session(session_kw)
        page.wait_for_timeout(800)
        detail.select_ticket(ticket_kw)
        page.wait_for_timeout(1500)

        before = [pg.url for pg in context.pages]
        print(f"点击前标签页：{before}")

        btn = detail.buy_button()
        print(f"购买入口文本：『{(btn.inner_text(timeout=800) or '').strip()}』")
        btn.click(force=True)
        print("已点击，开始追踪 15 秒……")

        for sec in range(1, 16):
            page.wait_for_timeout(1000)
            urls = [pg.url for pg in context.pages]
            new = [u for u in urls if u not in before]
            print(f"[{sec}s] 标签页数={len(urls)} 新增={new or '无'} 当前页={page.url[:100]}")
            # 弹窗/对话框文本
            for selector in (".dialog", "[class*='modal']", "[class*='dialog']", "[role='dialog']"):
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=300):
                        text = (el.inner_text(timeout=500) or "").strip().replace("\n", " | ")
                        print(f"      弹窗（{selector}）：{text[:150]}")
                except Exception:
                    continue
            # 若已到非详情页，记录标题并截图后结束
            if "detail.damai.cn" not in page.url or len(context.pages) > len(before):
                target = context.pages[-1]
                print(f"      跳转后标题：{target.title()}")
                target.screenshot(path=str(OUT_DIR / "after_click.png"), full_page=False)
                print(f"      截图：{OUT_DIR / 'after_click.png'}")
                break

        context.close()


if __name__ == "__main__":
    main()
