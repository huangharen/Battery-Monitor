"""
Settings — 持久化配置管理 (JSON)
"""
import json, os, winreg
from pathlib import Path

FILE = Path(__file__).parent / "settings.json"

DEFAULTS = {
    "theme": "system",        # system | dark | light
    "draggable": False,       # 可否拖动
    "click_through": False,   # 鼠标穿透
    "opacity": 1.0,           # 不透明度 0.3-1.0
    "autostart": False,       # 开机自启
    "ontop": True,            # 强制置顶
    "x": None, "y": None,     # 上次位置
}

_cache = None


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if FILE.exists():
        try:
            _cache = {**DEFAULTS, **json.loads(FILE.read_text(encoding="utf-8"))}
            return _cache
        except Exception:
            pass
    _cache = dict(DEFAULTS)
    return _cache


def save(data: dict):
    global _cache
    _cache = dict(data)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def set_(key: str, value):
    s = load()
    s[key] = value
    save(s)


def set_autostart(enable: bool):
    """在 Startup 文件夹创建/删除快捷方式，实现开机自启"""
    import sys, os
    startup = os.path.join(os.getenv("APPDATA"),
                          "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    lnk_path = os.path.join(startup, "BatteryMonitor.lnk")

    if enable:
        exe = sys.executable
        try:
            from win32com.client import Dispatch
            shell = Dispatch("WScript.Shell")
            sc = shell.CreateShortCut(lnk_path)
            sc.Targetpath = exe
            sc.WorkingDirectory = os.path.dirname(exe)
            sc.save()
        except Exception:
            pass
    else:
        try:
            if os.path.exists(lnk_path):
                os.remove(lnk_path)
        except Exception:
            pass


def detect_system_theme() -> str:
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return "light" if v == 1 else "dark"
    except Exception:
        return "dark"
