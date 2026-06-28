"""
Battery Monitor · 液态玻璃悬浮窗
入口 · 系统托盘 · 开机自启 · 单实例
"""

import sys, os, time, ctypes
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from overlay_window import BatteryOverlay, SettingsDialog, init_font

if getattr(sys, 'frozen', False):
    _RES_DIR = Path(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))
else:
    _RES_DIR = Path(__file__).parent

_MUTEX_NAME = "BatteryMonitor_SingleInstance_Mutex"
kernel32 = ctypes.windll.kernel32


def _ensure_single_instance():
    """互斥体检测冲突，存在旧实例则 taskkill 杀之"""
    mutex = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        our_pid = os.getpid()
        import subprocess
        subprocess.run(['taskkill', '/F', '/FI', f'PID ne {our_pid}',
                        '/IM', 'BatteryMonitor.exe'],
                       capture_output=True, timeout=5,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(0.3)
        mutex = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    return mutex


def main():
    _ensure_single_instance()

    app = QApplication(sys.argv)
    app.setApplicationName("Battery Monitor")
    app.setStyle("Fusion")

    try:
        init_font()
    except Exception:
        pass

    try:
        icon_path = _RES_DIR / "charge.png"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass

    overlay = BatteryOverlay()
    overlay.show()

    try:
        tray_icon = QIcon(str(_RES_DIR / "charge.png"))
    except Exception:
        tray_icon = QIcon()
    tray = QSystemTrayIcon(tray_icon, app)
    tray.setToolTip("电池助手")

    menu = QMenu()
    menu.addAction("设置...", lambda: overlay._open_settings())
    menu.addAction("重启", overlay._restart)
    menu.addSeparator()
    menu.addAction("退出", app.quit)
    tray.setContextMenu(menu)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
