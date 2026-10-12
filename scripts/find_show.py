"""用有头真实 Chrome 逛大麦首页，提取在售演出链接（辅助脚本）。"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(locale="zh-CN")
        page.goto("https://www.damai.cn/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)

        anchors = page.locator("a[href*='item.htm?id=']")
        n = anchors.count()
        print(f"详情链接数: {n}")

        seen: set[str] = set()
        for i in range(n):
            if len(seen) >= 12:
                break
            a = anchors.nth(i)
            try:
                href = a.get_attribute("href") or ""
                m = re.search(r"id=(\d+)", href)
                if not m or m.group(1) in seen:
                    continue
                text = " ".join(
                    t.strip() for t in (a.inner_text(timeout=500) or "").splitlines() if t.strip()
                )
                if len(text) < 4:
                    continue
                seen.add(m.group(1))
                if not href.startswith("http"):
                    href = (
                        "https:" + href
                        if href.startswith("//")
                        else "https://detail.damai.cn/item.htm?id=" + m.group(1)
                    )
                print(f"{len(seen)}. [{text[:90]}] -> {href}")
            except Exception:
                continue

        browser.close()


if __name__ == "__main__":
    main()
