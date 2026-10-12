"""诊断脚本：用已保存的登录态打开详情页，导出场次/票档选项的真实文本。

用法：python scripts/dump_options.py <详情页URL> [场次关键字]
若给了场次关键字，会先点击场次再导出票档（部分演出票档依赖场次选择）。
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from src.browser import launch_context  # noqa: E402

OPTION_SELECTORS = [
    ".select_right_list_item",
    ".perform__order__select__performs__perform",
    "[class*='perform-item']",
    "[class*='sku-item']",
    "[class*='select_right_list'] [class*='item']",
]


def dump(page, label: str) -> None:
    print(f"\n===== {label} =====")
    hit_any = False
    for selector in OPTION_SELECTORS:
        items = page.locator(selector)
        n = items.count()
        if n == 0:
            continue
        hit_any = True
        print(f"[选择器 {selector}] 命中 {n} 项：")
        for i in range(min(n, 40)):
            item = items.nth(i)
            try:
                text = (item.inner_text(timeout=500) or "").strip().replace("\n", " ")
                cls = item.get_attribute("class") or ""
                flag = " [不可选]" if "disabled" in cls else ""
                print(f"  {i + 1}. 『{text}』{flag}")
            except Exception:
                continue
    if not hit_any:
        print("（所有候选选择器均未命中，输出页面中含'¥'或'元'的行）")
        body = page.locator("body").inner_text(timeout=3000)
        for line in body.splitlines():
            line = line.strip()
            if line and ("¥" in line or "元" in line) and len(line) < 60:
                print(f"  | {line}")


def main() -> None:
    url = sys.argv[1]
    session_kw = sys.argv[2] if len(sys.argv) > 2 else None

    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()

        # 预热首页再进详情，降低风控概率
        page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)

        title = page.title()
        print(f"页面标题：『{title}』")
        if "拒绝" in title or "punish" in page.url:
            print("!! 仍被风控拦截")
            context.close()
            return

        dump(page, "初始状态（未选场次）")

        if session_kw:
            print(f"\n>>> 点击场次关键字：{session_kw}")
            page.get_by_text(session_kw, exact=False).first.click(force=True)
            page.wait_for_timeout(2000)
            dump(page, f"选择场次『{session_kw}』之后")

        # 购买按钮状态
        for selector in (".buybtn", ".buy-btn", "[class*='buybtn']"):
            btn = page.locator(selector).first
            try:
                if btn.is_visible():
                    print(f"\n购买按钮（{selector}）：『{(btn.inner_text(timeout=800) or '').strip()}』")
                    break
            except Exception:
                continue

        context.close()


if __name__ == "__main__":
    main()
