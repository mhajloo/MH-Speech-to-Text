"""Generate the download page's assets into website/mh-speech-to-text/:
web fonts (WOFF2), logo/favicon, the social preview image, and 2x screenshots.

Usage: .venv/Scripts/python tools/make_site_assets.py
(needs requirements.txt and requirements-site.txt)
"""
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = "2"  # crisp screenshots on high-DPI screens
ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "website" / "mh-speech-to-text"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from fontTools.ttLib import TTFont  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()), "raw", "RGBA", 0, 1)


def save_webp(img, name, quality=88):
    pil = qimage_to_pil(img) if isinstance(img, QImage) else img
    pil.save(SITE / "img" / name, "WEBP", quality=quality, method=6)


def fonts():
    (SITE / "fonts").mkdir(parents=True, exist_ok=True)
    for weight, name in ((400, "Regular"), (500, "Medium"), (700, "Bold")):
        f = TTFont(ROOT / "assets" / "fonts" / f"Vazirmatn-{name}.ttf")
        f.flavor = "woff2"
        f.save(SITE / "fonts" / f"vazirmatn-{weight}.woff2")
    (SITE / "fonts" / "OFL.txt").write_bytes((ROOT / "assets" / "fonts" / "OFL.txt").read_bytes())


def logos():
    from dictation.ui.icons import LOGO_SVG, svg_pixmap
    (SITE / "img" / "logo.svg").write_text(LOGO_SVG.strip(), encoding="utf-8")
    pm = svg_pixmap(LOGO_SVG, 90)  # 180 px at the 2x scale factor
    qimage_to_pil(pm.toImage()).save(SITE / "img" / "apple-touch-icon.png")


def og_image():
    """1200×630 preview shown when the link is shared (Telegram, X, ...)."""
    from dictation.ui import theme
    from dictation.ui.icons import BRAND_A, BRAND_B, LOGO_SVG, svg_pixmap
    w, h = 1200, 630
    img = QImage(w, h, QImage.Format_RGB32)
    img.setDevicePixelRatio(1)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#1a1433"))
    g.setColorAt(1, QColor("#0d2b3a"))
    p.fillRect(img.rect(), g)
    p.setPen(Qt.NoPen)
    for (cx, cy, r, col, a) in ((980, 120, 380, BRAND_A, 70), (1120, 600, 300, BRAND_B, 60)):
        c = QColor(col)
        c.setAlpha(a)
        p.setBrush(c)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    logo = svg_pixmap(LOGO_SVG, 110)  # 220 px
    logo.setDevicePixelRatio(1)
    p.drawPixmap(w - 220 - 90, 90, logo)
    p.setPen(QColor("#ffffff"))
    p.setFont(theme.font(40, 700))
    p.drawText(QRectF(90, 300, w - 180, 90), Qt.AlignRight | Qt.AlignVCenter, "MH-Speech to Text")
    p.setLayoutDirection(Qt.RightToLeft)
    p.setFont(theme.font(30, 700))
    p.drawText(QRectF(90, 395, w - 180, 70), Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter, "دیکته‌ی فارسی در هر برنامه‌ای")
    p.setPen(QColor("#b9b5d8"))
    p.setFont(theme.font(19, 400))
    p.drawText(QRectF(90, 470, w - 180, 50), Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter,
               "رایگان · متن‌باز · کاملاً آفلاین")
    p.end()
    qimage_to_pil(img).convert("RGB").save(SITE / "img" / "og.png", optimize=True)


def screenshots():
    import dictation.modelstore as ms
    import ui_preview
    from dictation.ui import theme
    from dictation.ui.overlay import BARS, RecordingBar
    from dictation.ui.settings import SettingsWindow
    from dictation.ui.wizard import SetupWizard

    ms.installed_models = lambda: [ms.DEFAULT_MODEL]  # a user's PC, not the dev machine
    ms.gpu_pack_installed = lambda: True
    app = QApplication.instance()

    theme.apply(app, "light")
    w = SettingsWindow(ui_preview.fake_app())
    w.show_page("general")
    save_webp(ui_preview.widget_shot(w, (940, 660)), "settings-light.webp")
    w.hide()

    theme.apply(app, "dark")
    w = SettingsWindow(ui_preview.fake_app())
    w.show_page("model")
    save_webp(ui_preview.widget_shot(w, (940, 660)), "settings-dark.webp")
    w.hide()

    theme.apply(app, "light")
    wz = SetupWizard(ui_preview.fake_app())
    wz._go(0)
    save_webp(ui_preview.widget_shot(wz), "setup-wizard.webp")
    wz.hide()

    bar = RecordingBar(lambda: 0.05)
    lv = [abs(math.sin(i * 0.7)) * 0.9 * (0.4 + 0.6 * abs(math.sin(i * 0.23))) for i in range(BARS)]
    for state, title, sub, tick in (("recording", "در حال شنیدن…", "Esc برای لغو", 10),
                                    ("busy", "در حال نوشتن متن…", "چند لحظه صبر کنید", 14),
                                    ("done", "متن درج شد", "۲۴ کلمه", 0)):
        bar.state, bar.title, bar.subtitle, bar._tick = state, title, sub, tick
        bar.started = time.monotonic() - 7
        bar.levels, bar._smooth = deque(lv, maxlen=BARS), 0.6
        save_webp(bar.grab().toImage(), f"bar-{state}.webp", quality=92)


def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    from dictation.ui import theme
    theme.load_fonts()
    (SITE / "img").mkdir(parents=True, exist_ok=True)
    fonts()
    logos()
    og_image()
    screenshots()
    total = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file() and f.suffix != ".html")
    print(f"site assets written to {SITE.relative_to(ROOT)} ({total // 1024} KB)")
    for f in sorted(SITE.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(SITE)}  {f.stat().st_size // 1024} KB")
    del app


if __name__ == "__main__":
    main()
