"""Render the interface to PNG files for review, without showing windows.

Usage: .venv/Scripts/python tools/ui_preview.py OUT_DIR [--dark] [parts...]
parts: overlay settings wizard tray about (default: all)
"""
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def grid(images, cols, bg, pad=14):
    w = max(i.width() for i in images)
    h = max(i.height() for i in images)
    rows = math.ceil(len(images) / cols)
    out = QImage(cols * (w + pad) + pad, rows * (h + pad) + pad, QImage.Format_ARGB32)
    out.fill(QColor(bg))
    p = QPainter(out)
    for n, img in enumerate(images):
        p.drawImage(pad + (n % cols) * (w + pad), pad + (n // cols) * (h + pad), img)
    p.end()
    return out


def overlay(out_dir):
    from dictation.ui.overlay import BARS, RecordingBar
    bar = RecordingBar(lambda: 0.05)
    shots = []

    def snap(state, title, sub, tick=0, levels=None):
        bar.state, bar.title, bar.subtitle, bar._tick = state, title, sub, tick
        bar.started = time.monotonic() - 7
        if levels:
            bar.levels = deque(levels, maxlen=BARS)
            bar._smooth = 0.6
        shots.append(bar.grab().toImage())

    lv = [abs(math.sin(i * 0.7)) * 0.9 * (0.4 + 0.6 * abs(math.sin(i * 0.23))) for i in range(BARS)]
    snap("recording", "در حال شنیدن…", "Esc برای لغو", 10, lv)
    snap("busy", "در حال نوشتن متن…", "چند لحظه صبر کنید", 14)
    snap("done", "متن درج شد", "۲۴ کلمه")
    snap("warning", "متن در کلیپ‌بورد است", "این برنامه با دسترسی مدیر اجرا شده؛ Ctrl+V بزنید")
    grid(shots, 2, "#DCE3EE").save(str(out_dir / "overlay.png"))


def widget_shot(w, size=None):
    if size:
        w.resize(*size)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.show()
    for _ in range(5):
        QApplication.processEvents()
    img = w.grab().toImage()
    return img


def fake_app():
    from PySide6.QtCore import QObject, Signal
    from dictation.config import Config

    class Rec:
        level, error = 0.08, None

        def monitor(self, on):
            pass

    class Fake(QObject):
        engine_status_changed = Signal()
        devices_changed = Signal()

        def __init__(self):
            super().__init__()
            self.cfg = Config(replacements={"اشتیمل": "اچ‌تی‌ام‌ال", "فرانتند": "فرانت‌اند"})
            self.recorder, self.hotkey = Rec(), None

        def update_config(self, **kw):
            for k, v in kw.items():
                setattr(self.cfg, k, v)

        def save_config(self):
            pass

        def engine_status(self):
            return {"state": "ready", "model": self.cfg.model,
                    "text": "فعال و آماده؛ اجرا روی کارت گرافیک NVIDIA T500"}

        def switch_model(self, m):
            pass

        def set_device(self, device):
            self.cfg.device = device

        def open_wizard(self, page=None):
            pass
    return Fake()


def settings(out_dir, suffix):
    from dictation.ui.settings import PAGES, SettingsWindow
    w = SettingsWindow(fake_app())
    shots = []
    for key, _, _ in PAGES:
        w.show_page(key)
        img = widget_shot(w, (940, 660))
        img.save(str(out_dir / f"settings_{key}{suffix}.png"))
        shots.append(img)
    w.hide()


def wizard(out_dir, suffix):
    from dictation.ui.wizard import SetupWizard
    wz = SetupWizard(fake_app())
    for i in range(5):
        wz._go(i)
        widget_shot(wz).save(str(out_dir / f"wizard_{i}{suffix}.png"))
    wz.hide()


def tray(out_dir, suffix):
    from dictation.ui.tray import Tray
    t = Tray("ctrl+q")
    t.set_state("ready")
    m = t.menu
    m.adjustSize()
    img = widget_shot(m)
    grid([img], 1, "#DCE3EE" if not suffix else "#0B0A14").save(str(out_dir / f"tray{suffix}.png"))


def history(out_dir, suffix):
    import json
    import tempfile
    import dictation.ui.history as h
    tmp = Path(tempfile.mkdtemp()) / "history.jsonl"
    rows = [("2026-09-27 19:02:35", "سلام، ازت می‌خوام به عنوان یک مدرس برنامه‌نویس به من اچ‌تی‌ام‌ال و "
             "جاوا اسکریپت رو یاد بدی."),
            ("2026-09-27 19:05:10", "جلسه‌ی فردا ساعت ۱۰ صبح برگزار می‌شود؛ لطفاً گزارش‌ها را آماده کنید."),
            ("2026-09-26 11:40:02", "یادم باشه برای خرید نرم‌افزار حسابداری با پشتیبانی تماس بگیرم.")]
    tmp.write_text("\n".join(json.dumps({"time": t, "text": x}, ensure_ascii=False) for t, x in rows),
                   encoding="utf-8")
    h.HISTORY_PATH = tmp
    w = h.HistoryWindow(lambda t: None)
    widget_shot(w, (720, 620)).save(str(out_dir / f"history{suffix}.png"))
    w.hide()


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    dark = "--dark" in sys.argv
    parts = [a for a in sys.argv[2:] if not a.startswith("--")] or [
        "overlay", "settings", "wizard", "tray", "history"]
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    from dictation.ui import theme
    theme.load_fonts()
    theme.apply(app, "dark" if dark else "light")
    suffix = "_dark" if dark else ""
    for part in parts:
        fn = globals().get(part)
        if fn:
            fn(out_dir) if part == "overlay" else fn(out_dir, suffix)
            print("rendered", part)


if __name__ == "__main__":
    main()
