"""Render build assets from the SVG logo: the Windows .ico, a PNG, and the
installer's wizard images (BMP, as Inno Setup expects).

Usage: .venv/Scripts/python tools/make_assets.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402  (build-time only)
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ICONS = ROOT / "assets" / "icons"
INSTALLER = ROOT / "installer"


def qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()), "raw", "RGBA", 0, 1)


def main():
    app = QApplication(sys.argv)
    from dictation.ui import theme
    from dictation.ui.icons import BRAND_A, BRAND_B, LOGO_SVG, svg_pixmap
    theme.load_fonts()
    ICONS.mkdir(parents=True, exist_ok=True)
    INSTALLER.mkdir(parents=True, exist_ok=True)

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [qimage_to_pil(svg_pixmap(LOGO_SVG, s).toImage()) for s in sizes]
    frames[-1].save(ICONS / "app.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    frames[-1].save(ICONS / "app.png")

    # installer images: a tall gradient panel and a small square logo
    for name, (w, h), logo in (("wizard_large.bmp", (410, 797), 170), ("wizard_small.bmp", (138, 140), 110)):
        img = QImage(w, h, QImage.Format_RGB32)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        if name == "wizard_large.bmp":
            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0, QColor(BRAND_A))
            g.setColorAt(1, QColor(BRAND_B))
            p.fillRect(img.rect(), g)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 24))
            p.drawEllipse(QRectF(-120, h - 330, 420, 420))
            p.drawEllipse(QRectF(w - 170, -90, 300, 300))
            p.drawPixmap((w - logo) // 2, int(h * 0.30), svg_pixmap(LOGO_SVG, logo))
            p.setPen(QColor("#ffffff"))
            p.setFont(theme.font(22, 700))
            p.drawText(QRectF(0, h * 0.30 + logo + 30, w, 60), Qt.AlignCenter, "MH-Speech to Text")
            p.setFont(theme.font(15, 400))
            p.drawText(QRectF(0, h * 0.30 + logo + 90, w, 50), Qt.AlignCenter, "Persian speech to text")
        else:
            p.fillRect(img.rect(), QColor("#ffffff"))
            p.drawPixmap((w - logo) // 2, (h - logo) // 2, svg_pixmap(LOGO_SVG, logo))
        p.end()
        qimage_to_pil(img).convert("RGB").save(INSTALLER / name)
    print("assets written:", ICONS / "app.ico", INSTALLER / "wizard_large.bmp")
    del app


if __name__ == "__main__":
    main()
