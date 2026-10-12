"""提醒模块：蜂鸣循环 + Windows 桌面通知。

用于三种场景：订单提交成功（提醒付款）、遇到滑块验证码（提醒人工）、抢票失败。
"""

from __future__ import annotations

import subprocess
import threading
import time

try:
    import winsound  # Windows 内置

    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False


class Notifier:
    """响铃提醒器：后台线程循环蜂鸣，直到调用 stop()"""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, message: str) -> None:
        """开始响铃 + 弹出桌面通知（重复调用会先停掉上一个）"""
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._beep_loop, daemon=True)
        self._thread.start()
        _toast("大麦抢票助手", message)
        print(f"\n[提醒] {message}\n")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _beep_loop(self) -> None:
        # 每 1.2 秒两声短蜂鸣，持续到被停止
        while not self._stop_event.is_set():
            if _HAS_WINSOUND:
                try:
                    winsound.Beep(1200, 300)
                    winsound.Beep(1600, 300)
                except RuntimeError:
                    pass
            else:
                print("\a", end="", flush=True)
            self._stop_event.wait(1.2)


def _toast(title: str, message: str) -> None:
    """通过 PowerShell 弹 Windows 桌面通知，失败时静默降级（控制台仍有输出）"""
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null; "
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::Text02); "
        "$texts = $template.GetElementsByTagName('text'); "
        f"$texts.Item(0).AppendChild($template.CreateTextNode('{title}')) | Out-Null; "
        f"$texts.Item(1).AppendChild($template.CreateTextNode('{message}')) | Out-Null; "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'qiangpiao').Show($toast)"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def countdown_sleep(until_ts: float, time_sync_now) -> None:
    """睡到指定时刻（用校准时间的 now 函数），最后 2 秒内改为小步轮询避免睡过头"""
    while True:
        remain = until_ts - time_sync_now()
        if remain <= 0:
            return
        if remain > 30:
            print(f"[等待] 距开售还有 {int(remain // 60)} 分 {int(remain % 60)} 秒    ", end="\r")
            time.sleep(min(remain - 2, 30))
        elif remain > 2:
            time.sleep(0.2)
        else:
            time.sleep(0.01)
