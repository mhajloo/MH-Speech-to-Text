"""The app logo and the line icons used in menus and the settings window.

Everything is SVG drawn for this app (no third-party icon set), rendered by Qt
at whatever size is needed, so it stays crisp on any display scaling.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Brand gradient: violet → turquoise
BRAND_A = "#7A5CFF"
BRAND_B = "#21C3E6"

LOGO_SVG = f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BRAND_A}"/>
      <stop offset="1" stop-color="{BRAND_B}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.3" cy="0.2" r="0.9">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.35"/>
      <stop offset="0.6" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect x="8" y="8" width="240" height="240" rx="60" fill="url(#bg)"/>
  <rect x="8" y="8" width="240" height="240" rx="60" fill="url(#glow)"/>
  <!-- microphone -->
  <rect x="94" y="46" width="52" height="94" rx="26" fill="#ffffff"/>
  <path d="M74 116 a46 46 0 0 0 92 0" fill="none" stroke="#ffffff" stroke-width="13"
        stroke-linecap="round"/>
  <path d="M120 162 v26" stroke="#ffffff" stroke-width="13" stroke-linecap="round"/>
  <path d="M96 194 h48" stroke="#ffffff" stroke-width="13" stroke-linecap="round"/>
  <!-- text lines: speech becoming text (right-to-left, like Persian) -->
  <path d="M176 80 h38" stroke="#ffffff" stroke-opacity="0.95" stroke-width="12" stroke-linecap="round"/>
  <path d="M190 110 h24" stroke="#ffffff" stroke-opacity="0.8" stroke-width="12" stroke-linecap="round"/>
  <path d="M182 140 h32" stroke="#ffffff" stroke-opacity="0.65" stroke-width="12" stroke-linecap="round"/>
</svg>
"""

# 24×24 line icons, stroke drawn in {color}
_LINE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
         'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
LINE_ICONS = {
    "general": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/>'
               '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/>'
           '<path d="M12 17.5V21M9 21h6"/>',
    "text": '<path d="M5 6h14M5 10h14M9 14h10M12 18h7"/>',
    "model": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
             '<path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3 4v4h4"/><path d="M12 8v4l3 2"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "power": '<path d="M12 3v8"/><path d="M6.4 6.4a8 8 0 1 0 11.2 0"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "github": '<path d="M9 19c-4 1.3-4-2-6-2.5M15 21v-3.5a3 3 0 0 0-.9-2.4c3-.3 6.1-1.5 6.1-6.6a5.2 5.2 0 0 0-1.4-3.6 4.8 4.8 0 0 0-.1-3.6s-1.1-.3-3.7 1.4a12.8 12.8 0 0 0-6.8 0C5.6 1.7 4.5 2 4.5 2a4.8 4.8 0 0 0-.1 3.6A5.2 5.2 0 0 0 3 9.2c0 5.1 3.1 6.3 6.1 6.6a3 3 0 0 0-.9 2.4V21"/>',
    "heart": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "bolt": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
}


def svg_pixmap(svg: str, size: int, dpr: float = 1.0) -> QPixmap:
    px = int(round(size * dpr))
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def line_icon(name: str, color: str) -> QIcon:
    svg = _LINE.format(color=color, body=LINE_ICONS[name])
    icon = QIcon()
    for s in (16, 20, 24, 32, 48):
        icon.addPixmap(svg_pixmap(svg, s))
    return icon


@lru_cache(maxsize=None)
def logo_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(svg_pixmap(LOGO_SVG, s))
    return icon


def tray_icon(state: str) -> QIcon:
    """The logo with a status badge: loading (dimmed), recording (red dot),
    busy (amber dot), error (red ring)."""
    icon = QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64):
        pm = svg_pixmap(LOGO_SVG, s)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        if state == "loading":
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.fillRect(pm.rect(), QColor(0, 0, 0, 110))
        elif state in ("recording", "busy", "error"):
            color = {"recording": "#FF3B5C", "busy": "#FFB020", "error": "#E5484D"}[state]
            r = s * 0.40
            x, y = s - r - s * 0.02, s - r - s * 0.02
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QRectF(x - s * 0.06, y - s * 0.06, r + s * 0.12, r + s * 0.12))
            painter.setBrush(QColor(color))
            painter.drawEllipse(QRectF(x, y, r, r))
        painter.end()
        icon.addPixmap(pm)
    return icon
