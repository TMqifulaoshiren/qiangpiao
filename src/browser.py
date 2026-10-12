"""浏览器管理：持久化上下文（复用登录态）+ 克制的反自动化检测处理。

只做常规降检测手段：真实 Chrome、去掉 automation 标志、隐藏 navigator.webdriver。
不做指纹伪造等激进对抗——那会显著提高风控风险且难以维护。
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright

# 登录态存储目录（在项目根目录下，勿提交到 git）
PROFILE_DIR = Path(__file__).resolve().parent.parent / "profile"

# 大麦/淘系登录后的关键 Cookie，存在即视为已登录
LOGIN_COOKIE_MARKERS = ("_m_h5_tk", "cookie2")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


def launch_context(p: Playwright) -> BrowserContext:
    """启动持久化浏览器上下文，登录态保存在 ./profile"""
    PROFILE_DIR.mkdir(exist_ok=True)
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",  # 使用本机真实 Chrome 而非捆绑 Chromium
        headless=False,
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
        viewport=None,
        locale="zh-CN",
    )
    context.add_init_script(STEALTH_JS)
    return context


def is_logged_in(context: BrowserContext) -> bool:
    """通过淘系关键 Cookie 判断是否已登录大麦"""
    cookies = {c["name"] for c in context.cookies()}
    return any(marker in cookies for marker in LOGIN_COOKIE_MARKERS)


def ensure_login(context: BrowserContext, page: Page, show_url: str) -> None:
    """确保已登录：未登录则打开大麦首页，等用户手动扫码，脚本不接触任何凭据"""
    if is_logged_in(context):
        print("[登录] 检测到已保存的登录态")
        return

    print("[登录] 未检测到登录态，已打开大麦首页，请手动扫码登录……")
    page.goto("https://www.damai.cn/", wait_until="domcontentloaded")
    # 轮询等待登录 Cookie 出现，最长 5 分钟
    for _ in range(300):
        if is_logged_in(context):
            print("[登录] 登录成功")
            page.goto(show_url, wait_until="domcontentloaded")
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("等待登录超时（5 分钟），请重新运行脚本")
