"""诊断：选好场次+票档后，导出购买区域的真实 HTML / 文本 / 截图，定位购买按钮选择器。

用法：python scripts/dump_buybtn.py <详情页URL> <场次关键字> <票档关键字>
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
        page.wait_for_timeout(3000)  # 给按钮渲染留时间

        # 购票区域容器
        box = page.locator(".perform__order__box").first
        try:
            html = box.inner_html(timeout=3000)
            (OUT_DIR / "orderbox.html").write_text(html, encoding="utf-8")
            print(f"购票区 HTML 已保存（{len(html)} 字符）：{OUT_DIR / 'orderbox.html'}")
            text = box.inner_text(timeout=2000)
            print("购票区文本：")
            for line in text.splitlines():
                if line.strip():
                    print(f"  | {line.strip()}")
            box.screenshot(path=str(OUT_DIR / "orderbox.png"))
            print(f"购票区截图：{OUT_DIR / 'orderbox.png'}")
        except Exception as e:
            print(f"读取购票区失败：{e}")

        # 全页所有疑似按钮元素
        print("\n疑似按钮元素（class 含 buy/btn 或 tag 为 button）：")
        candidates = page.locator("[class*='buy'], [class*='btn'], button")
        n = candidates.count()
        print(f"共 {n} 个")
        for i in range(min(n, 40)):
            el = candidates.nth(i)
            try:
                cls = el.get_attribute("class") or ""
                tag = el.evaluate("e => e.tagName")
                text = (el.inner_text(timeout=400) or "").strip().replace("\n", " ")
                visible = el.is_visible()
                print(f"  {i + 1}. <{tag} class='{cls}'> visible={visible} text=''{text[:40]}'")
            except Exception:
                continue

        context.close()


if __name__ == "__main__":
    main()
