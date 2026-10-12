"""大麦抢票助手入口。

用法：
    python main.py                 # 正式抢票（按 config.yaml 的开售时间定时自动抢）
    python main.py --dry-run       # 演练模式：立即走完整链路，到订单确认页即停，不提交
    python main.py --check-login   # 仅打开浏览器完成扫码登录并保存登录态
"""

from __future__ import annotations

import argparse
import sys

from src.config import ConfigError, load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="大麦抢票助手（个人自用）")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径，默认 config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="演练模式：跳过等待直接走链路，到订单页即停不提交")
    parser.add_argument("--check-login", action="store_true", help="仅打开浏览器扫码登录并保存登录态")
    return parser.parse_args()


def check_login_only(show_url: str) -> None:
    """只维护登录态：打开大麦，扫码登录后 Cookie 保存在 ./profile"""
    from playwright.sync_api import sync_playwright

    from src.browser import ensure_login, launch_context

    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()
        ensure_login(context, page, show_url)
        print("[完成] 登录态已保存到 profile/ 目录")
        context.close()


def main() -> int:
    args = parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[配置错误] {e}")
        return 1

    if args.check_login:
        check_login_only(cfg.show_url)
        return 0

    from src.grabber import Grabber

    print("=" * 60)
    print("大麦抢票助手（个人自用）")
    print(f"  演出链接：{cfg.show_url}")
    print(f"  场次/票档：{cfg.session} / {cfg.ticket}  x{cfg.quantity}")
    print(f"  开售时间：{cfg.sale_time}（北京时间）")
    print(f"  模式：{'dry-run 演练' if args.dry_run else '定时自动抢（停在提交订单，付款需手动）'}")
    print("=" * 60)

    grabber = Grabber(cfg, dry_run=args.dry_run)
    try:
        success = grabber.run()
    except KeyboardInterrupt:
        print("\n[中断] 用户手动停止")
        return 130
    except Exception as e:
        print(f"[异常] {type(e).__name__}: {e}")
        return 1

    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
