"""Start with Windows, via the current user's Run key (no admin rights needed)."""
import sys
import winreg
from pathlib import Path

from .branding import APP_NAME
from .paths import APP_ROOT, FROZEN

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command() -> str:
    if FROZEN:
        return f'"{sys.executable}" --autostart'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{APP_ROOT / "MH-Speech to Text.pyw"}" --autostart'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_enabled(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass
