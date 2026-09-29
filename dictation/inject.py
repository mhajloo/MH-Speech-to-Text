"""Put text into whatever window has focus.

"clipboard": save the clipboard, put our text on it (flagged so it stays out of
Win+V history), send Ctrl+V, then restore what was there. Fast for any length.
"type": send the text as Unicode keystrokes; slower, for apps that block paste.
"""
import ctypes
import time
from ctypes import wintypes

import win32clipboard as wcb

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4
VK_CONTROL, VK_V = 0x11, 0x56
VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x12, 0x5B, 0x5C


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
SMTO_ABORTIFHUNG = 0x0002


def _key(vk=0, scan=0, flags=0):
    return INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


def _send(inputs) -> bool:
    """False if Windows refused the input (e.g. blocked by another program)."""
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) == len(inputs)


def _wait_modifiers_released(timeout=1.5):
    """Shift/Alt/Win still held would turn our Ctrl+V into something else."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000
                   for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)):
            return
        time.sleep(0.02)


def _open_clipboard(retries=25):
    for _ in range(retries):
        try:
            wcb.OpenClipboard()
            return
        except Exception:  # another app holds it for a moment
            time.sleep(0.02)
    wcb.OpenClipboard()


def _snapshot():
    saved = []
    _open_clipboard()
    try:
        fmt = wcb.EnumClipboardFormats(0)
        while fmt:
            try:
                data = wcb.GetClipboardData(fmt)
                if isinstance(data, (str, bytes)):  # handles (bitmaps etc.) can't be re-set
                    saved.append((fmt, data))
            except Exception:
                pass
            fmt = wcb.EnumClipboardFormats(fmt)
    finally:
        wcb.CloseClipboard()
    return saved


def _set_clipboard(items):
    _open_clipboard()
    try:
        wcb.EmptyClipboard()
        for fmt, data in items:
            try:
                wcb.SetClipboardData(fmt, data)
            except Exception:
                pass
    finally:
        wcb.CloseClipboard()


def copy_to_clipboard(text: str):
    _set_clipboard([(wcb.CF_UNICODETEXT, text)])


def _wait_until_processed(hwnd, timeout_ms=3000):
    """Return once the target window's thread has worked through its queue (our
    Ctrl+V included), or after timeout_ms if it is hung. Restoring the clipboard
    any earlier would make a slow app paste the user's old clipboard instead."""
    if not hwnd:
        return
    result = ctypes.c_size_t()
    for _ in range(2):  # twice: the first reply can come before the keystrokes are handled
        user32.SendMessageTimeoutW(hwnd, 0, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result))
        time.sleep(0.05)


def paste(text: str) -> bool:
    saved = _snapshot()
    target = user32.GetForegroundWindow()
    _set_clipboard([
        (wcb.CF_UNICODETEXT, text),
        (wcb.RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing"), b"\0"),
        (wcb.RegisterClipboardFormat("CanIncludeInClipboardHistory"), b"\0\0\0\0"),
    ])
    sent = _send([_key(VK_CONTROL), _key(VK_V),
                  _key(VK_V, flags=KEYEVENTF_KEYUP), _key(VK_CONTROL, flags=KEYEVENTF_KEYUP)])
    if not sent:
        return False
    _wait_until_processed(target)
    time.sleep(0.3)  # apps that read the clipboard asynchronously (browsers, Electron)
    if saved:
        _set_clipboard(saved)
    return True


def type_text(text: str) -> bool:
    inputs = []
    for ch in text.replace("\r\n", "\n"):
        code = ord(ch)
        units = [code] if code < 0x10000 else [
            0xD800 + ((code - 0x10000) >> 10), 0xDC00 + ((code - 0x10000) & 0x3FF)]
        for u in units:
            inputs += [_key(scan=u, flags=KEYEVENTF_UNICODE),
                       _key(scan=u, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    for i in range(0, len(inputs), 200):
        if not _send(inputs[i:i + 200]):
            return False
        time.sleep(0.005)
    return True


def insert(text: str, method="clipboard") -> str:
    """Put text into the focused window. Returns "ok", or "clipboard" when
    Windows won't let us type into that window: the text is then left on the
    clipboard for the user to paste."""
    _wait_modifiers_released()
    if foreground_is_elevated():
        copy_to_clipboard(text)
        return "clipboard"
    ok = type_text(text) if method == "type" else paste(text)
    if not ok:
        copy_to_clipboard(text)
        return "clipboard"
    return "ok"


# --- elevated (administrator) windows ---
# Windows blocks input from a normal program into a program running as
# administrator (UIPI), silently. Detect it so the user isn't left guessing.
TOKEN_QUERY, TOKEN_ELEVATION = 0x0008, 20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def _elevated(process_handle):
    """True/False, or None if the token can't be read."""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        value, size = wintypes.DWORD(), wintypes.DWORD()
        if not advapi32.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(value),
                                            ctypes.sizeof(value), ctypes.byref(size)):
            return None
        return bool(value.value)
    finally:
        kernel32.CloseHandle(token)


SELF_ELEVATED = bool(_elevated(kernel32.GetCurrentProcess()))


def foreground_is_elevated() -> bool:
    if SELF_ELEVATED:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    if not pid.value:
        return False
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not proc:
        return False
    try:
        # a normal process may not even open an elevated process's token
        return _elevated(proc) is not False
    finally:
        kernel32.CloseHandle(proc)
