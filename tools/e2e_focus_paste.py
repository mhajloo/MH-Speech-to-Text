"""End-to-end check of the two things that must never break on a real desktop:
1. the recording bar never takes the keyboard focus from the window being typed in;
2. the text is pasted into that window and the user's clipboard is restored.

Opens a small test window for a few seconds. Usage:
    .venv/Scripts/python tools/e2e_focus_paste.py
"""
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = ctypes.c_void_p


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication(sys.argv)
    from dictation import inject
    from dictation.ui import theme
    from dictation.ui.overlay import RecordingBar
    theme.load_fonts()
    theme.apply(app, "light")

    target = QWidget()
    target.setWindowTitle("MH-STT focus test")
    target.setLayoutDirection(Qt.RightToLeft)
    edit = QLineEdit()
    QVBoxLayout(target).addWidget(edit)
    target.resize(420, 80)
    target.show()
    # allowed to take the foreground: this process was started by the foreground app
    user32.keybd_event(0x12, 0, 0, 0)       # a tap of Alt lifts the foreground lock
    user32.keybd_event(0x12, 0, 2, 0)
    target.raise_()
    target.activateWindow()
    user32.SetForegroundWindow(int(target.winId()))
    edit.setFocus()
    pump(0.6)
    hwnd = int(target.winId())
    fg = user32.GetForegroundWindow()
    print(f"target is foreground before test: {fg == hwnd}")
    if fg != hwnd:
        print("could not bring the test window to the front; aborting")
        return 1

    inject.copy_to_clipboard("ORIGINAL-CLIPBOARD")
    bar = RecordingBar(lambda: 0.06)
    results = {}
    for state, call in (("recording", lambda: bar.recording("Esc لغو")),
                        ("busy", bar.busy), ("done", lambda: bar.done(3))):
        call()
        pump(0.5)
        results[state] = user32.GetForegroundWindow() == hwnd and edit.hasFocus()
    print("focus kept while bar shows:", results)

    # like the app: insert on a worker thread while this (target) window keeps
    # its event loop running
    import threading
    box = {}
    worker = threading.Thread(target=lambda: box.setdefault("r", inject.insert(
        "سلام، این یک آزمایش است ", "clipboard")))
    worker.start()
    while worker.is_alive():
        pump(0.05)
    pump(0.3)
    out = box.get("r")
    print("insert result:", out)
    print("text in target:", repr(edit.text()))
    import win32clipboard as wcb
    wcb.OpenClipboard()
    try:
        clip = wcb.GetClipboardData(wcb.CF_UNICODETEXT)
    finally:
        wcb.CloseClipboard()
    print("clipboard restored:", clip == "ORIGINAL-CLIPBOARD")

    pasted_ok = edit.text() == "سلام، این یک آزمایش است "
    edit.clear()
    out = inject.insert("تایپ حرف‌به‌حرف", "type")
    pump(0.8)
    print("type mode:", out, repr(edit.text()))
    ok = (all(results.values()) and pasted_ok and edit.text() == "تایپ حرف‌به‌حرف"
          and clip == "ORIGINAL-CLIPBOARD")
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
