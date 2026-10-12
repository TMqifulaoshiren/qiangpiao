"""深度诊断：保存详情页完整 HTML、全页截图、iframe 列表，供离线分析结构。

用法：python scripts/dump_page.py <详情页URL>
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from src.browser import launch_context  # noqa: E402

OUT_DIR = Path("debug_out")


def main() -> None:
    url = sys.argv[1]
    OUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()

        # 预热首页再进详情
        page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.goto(url, wait_until="domcontentloaded")
        # 多等一会儿，给重 JS 渲染留时间
        page.wait_for_timeout(10000)

        print(f"标题：{page.title()}")
        print(f"URL：{page.url}")

        # 保存 HTML 与截图
        html = page.content()
        (OUT_DIR / "page.html").write_text(html, encoding="utf-8")
        print(f"HTML 已保存：{OUT_DIR / 'page.html'}（{len(html)} 字符）")
        page.screenshot(path=str(OUT_DIR / "page.png"), full_page=True)
        print(f"截图已保存：{OUT_DIR / 'page.png'}")

        # iframe 列表
        print(f"\nframe 数量：{len(page.frames)}")
        for i, frame in enumerate(page.frames):
            print(f"  frame[{i}]: {frame.url[:120]}")

        # 在所有 frame 里找包含 880 / 场次 / 票档 关键字的元素
        keywords = ("880", "场次", "票档", "立即购买", "即将开抢", "缺货")
        for i, frame in enumerate(page.frames):
            try:
                body_text = frame.locator("body").inner_text(timeout=2000)
            except Exception:
                continue
            hits = [kw for kw in keywords if kw in body_text]
            if hits:
                print(f"\nframe[{i}] 正文命中关键字：{hits}")
                # 打印命中行
                for line in body_text.splitlines():
                    line = line.strip()
                    if line and any(kw in line for kw in keywords) and len(line) < 80:
                        print(f"  | {line}")

        context.close()


if __name__ == "__main__":
    main()
