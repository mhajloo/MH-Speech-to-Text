"""Render the download page's demo video: MH-Speech to Text dictating into a
Word document (holding the hotkey) and a VS Code file (pressing it once), with
music and the app's own sound cues.

Everything is drawn with Qt (the recording bar is the app's own widget, so the
video matches the real app) and encoded with PyAV as H.264 + AAC. Word and
VS Code are simplified look-alikes, drawn without their logos.

Usage: .venv/Scripts/python tools/make_demo_video.py [--frames 5,10.4,...] [--out DIR]
  --frames  only save PNG stills at these times (seconds), for checking the design
Output: website/mh-speech-to-text/media/demo.mp4 and img/demo-poster.webp
"""
import argparse
import math
import random
import sys
import time
from collections import deque
from pathlib import Path

import av
import numpy as np
from PIL import Image
from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient, QRegion, QTextLayout, QTextOption)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SITE = ROOT / "website" / "mh-speech-to-text"
W, H, FPS = 1920, 1080, 30
SR = 44100                      # the app's cue sounds are made at this rate
DURATION = 30.0

# ---------------- timeline (seconds) ----------------
INTRO_END = 3.0
WORD_IN = 2.7                   # Word window slides in
WORD_PRESS, WORD_RELEASE, WORD_TEXT = 5.2, 9.4, 10.3
SWITCH = 14.3                   # Word out, VS Code in
CODE_TAP1, CODE_TAP2, CODE_TEXT = 16.4, 20.6, 21.4
OUTRO_IN = 25.2
TAP = 0.22                      # how long a "press once" keeps the keys down

WORD_TEXT_FA = ("جلسه‌ی فردا ساعت ده صبح برگزار می‌شود؛ لطفاً گزارش‌ها را تا امشب بفرستید "
                "تا پیش از جلسه مرورشان کنم.")
CODE_TEXT_FA = "این تابع فهرست اعضا را از پایگاه داده می‌خواند و بر اساس تاریخ عضویت مرتب می‌کند"

# window placement on the 1920x1080 "screen"
WIN = QRectF(180, 150, 1560, 870)


# ---------------- helpers ----------------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def ease_back(x, s=1.7):
    x = clamp(x)
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def span(t, a, b):
    """0 before a, 1 after b, linear between."""
    return clamp((t - a) / (b - a)) if b > a else float(t >= a)


def font(family, px, weight=400):
    f = QFont(family)
    f.setPixelSize(int(px))
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def fa_digits(n):
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def text_opt(align, rtl, wrap=False):
    # AlignAbsolute: "right" means the visual right even for right-to-left text
    opt = QTextOption(align | Qt.AlignAbsolute)
    opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    opt.setWrapMode(QTextOption.WordWrap if wrap else QTextOption.NoWrap)
    return opt


def paragraph(text, f, width, rtl=True, leading=1.55):
    """A wrapped QTextLayout -> (layout, height, (caret x, caret y, caret h) at the end)."""
    lay = QTextLayout(text, f)
    lay.setTextOption(text_opt(Qt.AlignRight if rtl else Qt.AlignLeft, rtl, wrap=True))
    lay.beginLayout()
    y, last = 0.0, None
    while True:
        line = lay.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        line.setPosition(QPointF(0, y))
        y += line.height() * leading
        last = line
    lay.endLayout()
    x = last.cursorToX(len(text))
    x = x[0] if isinstance(x, tuple) else x
    return lay, y, (x, last.y(), last.height())


def round_rect(p, r, radius, fill, pen=None):
    p.setPen(pen or Qt.NoPen)
    p.setBrush(fill)
    p.drawRoundedRect(r, radius, radius)


def soft_shadow(p, r, radius, strength=1.0, spread=26, dy=18):
    p.setPen(Qt.NoPen)
    for i in range(spread, 0, -2):
        a = int(strength * 5 * (1 - i / spread) ** 1.6) + 1
        p.setBrush(QColor(40, 30, 90, a))
        rr = r.adjusted(-i, -i + dy, i, i + dy)
        p.drawRoundedRect(rr, radius + i, radius + i)


def star(p, c, size, color, alpha):
    path = QPainterPath()
    for k in range(8):
        ang = math.pi / 4 * k - math.pi / 2
        rad = size if k % 2 == 0 else size * 0.28
        pt = QPointF(c.x() + math.cos(ang) * rad, c.y() + math.sin(ang) * rad)
        path.moveTo(pt) if k == 0 else path.lineTo(pt)
    path.closeSubpath()
    col = QColor(color)
    col.setAlphaF(clamp(alpha))
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawPath(path)


# ---------------- speech-like microphone levels ----------------
def speech_levels(seconds, seed):
    rnd = random.Random(seed)
    n = int(seconds * FPS) + 2
    lv = np.full(n, 0.03)
    t = 0.15
    while t < seconds - 0.2:
        for _ in range(rnd.randint(2, 5)):                  # syllables of a word
            dur, amp = rnd.uniform(0.12, 0.2), rnd.uniform(0.45, 1.0)
            a, b = int(t * FPS), int((t + dur) * FPS) + 1
            for i in range(a, min(b, n)):
                lv[i] = max(lv[i], amp * math.sin(math.pi * (i / FPS - t) / dur) + rnd.uniform(0, 0.08))
            t += dur * rnd.uniform(0.8, 1.05)
        t += rnd.uniform(0.08, 0.3)                         # gap between words
    return np.clip(lv, 0, 1)


# ---------------- the app's recording bar ----------------
class Bar:
    """Draws the app's own RecordingBar widget into the video."""

    def __init__(self):
        from dictation.ui.overlay import BARS, RecordingBar
        self.w = RecordingBar(lambda: 0.0)
        self.bars = BARS

    def draw(self, p, center_x, bottom_y, scale, state, title, subtitle, elapsed, levels, tick, opacity):
        if opacity <= 0:
            return
        w = self.w
        w.state, w.title, w.subtitle = state, title, subtitle
        w.started = time.monotonic() - elapsed                  # the bar shows its own clock
        w.levels = deque(levels, maxlen=self.bars)
        w._smooth = max(levels) * 0.8 if len(levels) else 0.0
        w._tick = tick
        p.save()
        p.setOpacity(opacity)
        p.translate(center_x - w.width() * scale / 2, bottom_y - w.height() * scale)
        p.scale(scale, scale)
        w.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        p.restore()


# ---------------- scenes ----------------
class Demo:
    def __init__(self):
        from dictation.ui import theme
        from dictation.ui.icons import LOGO_SVG
        theme.load_fonts()
        for name in ("consola.ttf", "consolab.ttf", "segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"):
            path = Path("C:/Windows/Fonts") / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        self.fa = "Vazirmatn"
        self.ui = "Segoe UI"
        self.mono = "Consolas"
        self.logo = QSvgRenderer(QByteArray(LOGO_SVG.encode()))
        self.bar = Bar()
        self.levels_word = speech_levels(WORD_RELEASE - WORD_PRESS, seed=7)
        self.levels_code = speech_levels(CODE_TAP2 - CODE_TAP1, seed=11)
        self.backdrop = self._backdrop()
        self.word_img = self._word_window()
        self.code_img = self._code_window()

    # ----- static layers -----
    def _backdrop(self):
        img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0, QColor("#F4F1FF"))
        g.setColorAt(1, QColor("#E6F6FB"))
        p.fillRect(img.rect(), g)
        for cx, cy, r, col, a in ((W - 160, 90, 520, "#7A5CFF", 70), (130, H - 60, 460, "#21C3E6", 60)):
            rg = QRadialGradient(QPointF(cx, cy), r)
            c = QColor(col)
            c.setAlpha(a)
            rg.setColorAt(0, c)
            c.setAlpha(0)
            rg.setColorAt(1, c)
            p.setPen(Qt.NoPen)
            p.setBrush(rg)
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()
        return img

    def _window_base(self, bg):
        img = QImage(int(WIN.width()) + 120, int(WIN.height()) + 120, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(60, 50, WIN.width(), WIN.height())
        soft_shadow(p, r, 16, strength=1.0, spread=40, dy=22)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        p.fillRect(r, QColor(bg))
        return img, p, r

    def _win_buttons(self, p, r, top, h, color):
        p.setPen(QPen(QColor(color), 1.6))
        x = r.right() - 46
        cy = top + h / 2
        p.drawLine(QPointF(x - 7, cy - 7), QPointF(x + 7, cy + 7))      # close
        p.drawLine(QPointF(x + 7, cy - 7), QPointF(x - 7, cy + 7))
        x -= 62
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x - 7, cy - 7, 14, 14))                       # maximize
        x -= 62
        p.drawLine(QPointF(x - 7, cy), QPointF(x + 7, cy))              # minimize

    def _word_window(self):
        img, p, r = self._window_base("#E9E9EE")
        x0, y0, w = r.left(), r.top(), r.width()
        # title bar
        p.fillRect(QRectF(x0, y0, w, 44), QColor("#185ABD"))
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font(self.ui, 17, 500))
        p.drawText(QRectF(x0, y0, w, 44), Qt.AlignCenter, "Meeting notes.docx  -  Word")
        self._win_buttons(p, r, y0, 44, "#FFFFFF")
        for i in range(3):                                              # quick-access icons
            round_rect(p, QRectF(x0 + 22 + i * 36, y0 + 13, 18, 18), 4, QColor(255, 255, 255, 190))
        # tabs
        ty = y0 + 44
        p.fillRect(QRectF(x0, ty, w, 40), QColor("#FFFFFF"))
        x = x0 + 24
        p.setFont(font(self.ui, 16))
        for i, tab in enumerate(("File", "Home", "Insert", "Design", "Layout", "References", "Review", "View")):
            tw = p.fontMetrics().horizontalAdvance(tab)
            p.setPen(QColor("#185ABD") if i == 1 else QColor("#444444"))
            p.drawText(QRectF(x, ty, tw + 2, 40), Qt.AlignVCenter | Qt.AlignLeft, tab)
            if i == 1:
                p.fillRect(QRectF(x, ty + 34, tw, 3), QColor("#185ABD"))
            x += tw + 34
        # ribbon
        ry = ty + 40
        p.fillRect(QRectF(x0, ry, w, 104), QColor("#F5F5F7"))
        p.fillRect(QRectF(x0, ry + 104, w, 1), QColor("#DADADF"))
        p.setFont(font(self.ui, 13))
        gx = x0 + 20
        for label, n in (("Clipboard", 2), ("Font", 6), ("Paragraph", 6), ("Styles", 4), ("Editing", 2)):
            gw = 64 + n * 40
            for k in range(n):
                row, col = divmod(k, max(1, (n + 1) // 2))
                c = QColor(["#5B8DEF", "#9AA3B2", "#C9CDD6", "#7F8796"][k % 4])
                round_rect(p, QRectF(gx + 12 + col * 44, ry + 14 + row * 34, 30, 24), 5, c)
            if label == "Font":
                round_rect(p, QRectF(gx + 150, ry + 14, 132, 26), 5, QColor("#FFFFFF"), QPen(QColor("#CFCFD6")))
                p.setPen(QColor("#333333"))
                p.drawText(QRectF(gx + 158, ry + 14, 120, 26), Qt.AlignVCenter | Qt.AlignLeft, "Vazirmatn   12")
            p.setPen(QColor("#6B6B75"))
            p.drawText(QRectF(gx, ry + 80, gw, 20), Qt.AlignCenter, label)
            p.fillRect(QRectF(gx + gw + 6, ry + 12, 1, 80), QColor("#DADADF"))
            gx += gw + 14
        # status bar
        sy = r.bottom() - 32
        p.fillRect(QRectF(x0, sy, w, 32), QColor("#F3F3F5"))
        p.setPen(QColor("#555560"))
        p.setFont(font(self.ui, 14))
        p.drawText(QRectF(x0 + 20, sy, 700, 32), Qt.AlignVCenter | Qt.AlignLeft,
                   "Page 1 of 1        Persian (Iran)")
        p.drawText(QRectF(r.right() - 220, sy, 200, 32), Qt.AlignVCenter | Qt.AlignRight, "100%")
        # the page
        page = self.word_page = QRectF(x0 + (w - 820) / 2, ry + 136, 820, sy - ry - 136 + 40)
        p.setPen(Qt.NoPen)
        for i in range(8, 0, -2):
            p.setBrush(QColor(20, 20, 40, 6))
            p.drawRect(page.adjusted(-i, -i + 3, i, i + 3))
        p.fillRect(page, QColor("#FFFFFF"))
        m = 84
        tr = QRectF(page.left() + m, page.top() + 70, page.width() - 2 * m, 60)
        p.setPen(QColor("#1F2A44"))
        p.setFont(font(self.fa, 36, 700))
        p.drawText(tr, "گزارش جلسه‌ی هفتگی", text_opt(Qt.AlignRight | Qt.AlignVCenter, True))
        p.setPen(QColor("#7A7A88"))
        p.setFont(font(self.fa, 20))
        p.drawText(tr.translated(0, 58), "سه‌شنبه، ۸ مهر ۱۴۰۵", text_opt(Qt.AlignRight | Qt.AlignVCenter, True))
        p.setPen(QColor("#2A2A36"))
        p.setFont(font(self.fa, 23))
        body = "موضوع‌ها: برنامه‌ی انتشار نسخه‌ی جدید و بازخورد کاربران."
        p.drawText(QRectF(tr.left(), tr.top() + 132, tr.width(), 44), body,
                   text_opt(Qt.AlignRight | Qt.AlignVCenter, True))
        self.word_text_rect = QRectF(tr.left(), tr.top() + 200, tr.width(), 200)
        p.end()
        return img

    def _code_window(self):
        img, p, r = self._window_base("#1F1F1F")
        x0, y0, w = r.left(), r.top(), r.width()
        # title bar with menus
        p.fillRect(QRectF(x0, y0, w, 40), QColor("#181818"))
        p.setFont(font(self.ui, 15))
        x = x0 + 56
        round_rect(p, QRectF(x0 + 18, y0 + 11, 18, 18), 4, QColor("#3B8EEA"))
        for m in ("File", "Edit", "Selection", "View", "Go", "Run", "Terminal", "Help"):
            p.setPen(QColor("#CCCCCC"))
            tw = p.fontMetrics().horizontalAdvance(m)
            p.drawText(QRectF(x, y0, tw + 2, 40), Qt.AlignVCenter | Qt.AlignLeft, m)
            x += tw + 22
        p.setPen(QColor("#9D9D9D"))
        p.drawText(QRectF(x0, y0, w, 40), Qt.AlignCenter, "app.py  —  members  —  Visual Studio Code")
        self._win_buttons(p, r, y0, 40, "#CCCCCC")
        body_top, body_bottom = y0 + 40, r.bottom() - 30
        # activity bar
        p.fillRect(QRectF(x0, body_top, 56, body_bottom - body_top), QColor("#181818"))
        for i in range(5):
            self._activity_icon(p, i, QPointF(x0 + 28, body_top + 32 + i * 58),
                                QColor("#D7D7D7") if i == 0 else QColor("#858585"))
        p.fillRect(QRectF(x0, body_top + 12, 3, 40), QColor("#0078D4"))
        # side bar: explorer
        sx = x0 + 56
        p.fillRect(QRectF(sx, body_top, 270, body_bottom - body_top), QColor("#181818"))
        p.fillRect(QRectF(sx + 270, body_top, 1, body_bottom - body_top), QColor("#2B2B2B"))
        p.setPen(QColor("#BBBBBB"))
        p.setFont(font(self.ui, 13, 600))
        p.drawText(QRectF(sx + 20, body_top + 8, 240, 30), Qt.AlignVCenter | Qt.AlignLeft, "EXPLORER")
        p.drawText(QRectF(sx + 20, body_top + 44, 240, 28), Qt.AlignVCenter | Qt.AlignLeft, "⌄  MEMBERS")
        p.setFont(font(self.ui, 15))
        files = (("app.py", "#4B8BBE"), ("database.py", "#4B8BBE"), ("README.md", "#519ABA"),
                 ("requirements.txt", "#BBBBBB"))
        for i, (name, col) in enumerate(files):
            fy = body_top + 76 + i * 32
            if i == 0:
                p.fillRect(QRectF(sx, fy, 270, 30), QColor("#37373D"))
            round_rect(p, QRectF(sx + 34, fy + 9, 13, 13), 3, QColor(col))
            p.setPen(QColor("#E6E6E6") if i == 0 else QColor("#CCCCCC"))
            p.drawText(QRectF(sx + 56, fy, 200, 30), Qt.AlignVCenter | Qt.AlignLeft, name)
        # tabs and breadcrumbs
        ex = sx + 271
        p.fillRect(QRectF(ex, body_top, r.right() - ex, 42), QColor("#181818"))
        p.fillRect(QRectF(ex, body_top, 160, 42), QColor("#1F1F1F"))
        p.fillRect(QRectF(ex, body_top, 160, 2), QColor("#0078D4"))
        p.setFont(font(self.ui, 15))
        round_rect(p, QRectF(ex + 16, body_top + 15, 12, 12), 3, QColor("#4B8BBE"))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(ex + 36, body_top, 110, 42), Qt.AlignVCenter | Qt.AlignLeft, "app.py")
        p.setPen(QColor("#9D9D9D"))
        p.drawText(QRectF(ex + 190, body_top, 130, 42), Qt.AlignVCenter | Qt.AlignLeft, "README.md")
        p.setFont(font(self.ui, 14))
        p.drawText(QRectF(ex + 20, body_top + 44, 600, 26), Qt.AlignVCenter | Qt.AlignLeft,
                   "members  ›  app.py  ›  list_members")
        # code
        self.code_origin = QPointF(ex, body_top + 84)
        self.code_line_h = 34
        lines = [
            [("import", "#C586C0"), (" sqlite3", "#4EC9B0")],
            [],
            [],
            [("def", "#569CD6"), (" list_members", "#DCDCAA"), ("(", "#D4D4D4"), ("db_path", "#9CDCFE"),
             ("):", "#D4D4D4")],
            [("    # ", "#6A9955")],
            [("    with", "#C586C0"), (" sqlite3", "#4EC9B0"), (".", "#D4D4D4"), ("connect", "#DCDCAA"),
             ("(", "#D4D4D4"), ("db_path", "#9CDCFE"), (") ", "#D4D4D4"), ("as", "#C586C0"), (" db", "#9CDCFE"),
             (":", "#D4D4D4")],
            [("        rows", "#9CDCFE"), (" = ", "#D4D4D4"), ("db", "#9CDCFE"), (".", "#D4D4D4"),
             ("execute", "#DCDCAA"), ("(", "#D4D4D4"), ('"SELECT name, joined FROM members"', "#CE9178"),
             (").", "#D4D4D4"), ("fetchall", "#DCDCAA"), ("()", "#D4D4D4")],
            [("    return", "#C586C0"), (" sorted", "#DCDCAA"), ("(", "#D4D4D4"), ("rows", "#9CDCFE"),
             (", ", "#D4D4D4"), ("key", "#9CDCFE"), ("=", "#D4D4D4"), ("lambda", "#569CD6"), (" row", "#9CDCFE"),
             (": ", "#D4D4D4"), ("row", "#9CDCFE"), ("[", "#D4D4D4"), ("1", "#B5CEA8"), ("])", "#D4D4D4")],
        ]
        mono = font(self.mono, 22)
        p.setFont(mono)
        fm = p.fontMetrics()
        self.code_char_w = fm.horizontalAdvance("M")
        self.code_x = ex + 86
        p.fillRect(QRectF(ex, self.code_origin.y() + 4 * self.code_line_h, r.right() - ex, self.code_line_h),
                   QColor("#2A2D2E"))
        for i, segs in enumerate(lines):
            ly = self.code_origin.y() + i * self.code_line_h
            p.setPen(QColor("#CCCCCC") if i == 4 else QColor("#6E7681"))
            p.drawText(QRectF(ex, ly, 60, self.code_line_h), Qt.AlignVCenter | Qt.AlignRight, str(i + 1))
            x = self.code_x
            for s, col in segs:
                p.setPen(QColor(col))
                p.drawText(QRectF(x, ly, 1000, self.code_line_h), Qt.AlignVCenter | Qt.AlignLeft, s)
                x += fm.horizontalAdvance(s)
        self.code_caret_x = self.code_x + fm.horizontalAdvance("    # ")
        # minimap
        mx = r.right() - 110
        for i, segs in enumerate(lines):
            x = mx
            for s, col in segs:
                c = QColor(col)
                c.setAlpha(150)
                p.fillRect(QRectF(x, self.code_origin.y() + i * 5, len(s) * 1.6, 3), c)
                x += len(s) * 1.6
        # status bar
        sy = r.bottom() - 30
        p.fillRect(QRectF(x0, sy, w, 30), QColor("#181818"))
        p.fillRect(QRectF(x0, sy, 44, 30), QColor("#0078D4"))
        p.setPen(QColor("#CCCCCC"))
        p.setFont(font(self.ui, 14))
        p.drawText(QRectF(r.right() - 640, sy, 620, 30), Qt.AlignVCenter | Qt.AlignRight,
                   "Ln 5, Col 7     Spaces: 4     UTF-8     LF     Python")
        p.end()
        return img

    @staticmethod
    def _activity_icon(p, kind, c, color):
        """Simple line icons: explorer, search, source control, run, extensions."""
        p.save()
        p.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        x, y = c.x(), c.y()
        if kind == 0:
            p.drawRect(QRectF(x - 9, y - 12, 15, 20))
            p.drawPolyline([QPointF(x - 4, y - 16), QPointF(x + 11, y - 16), QPointF(x + 11, y + 4)])
        elif kind == 1:
            p.drawEllipse(QPointF(x - 2, y - 2), 8, 8)
            p.drawLine(QPointF(x + 4, y + 4), QPointF(x + 11, y + 11))
        elif kind == 2:
            for px, py in ((x - 7, y - 10), (x - 7, y + 10), (x + 8, y - 4)):
                p.drawEllipse(QPointF(px, py), 3.2, 3.2)
            p.drawLine(QPointF(x - 7, y - 7), QPointF(x - 7, y + 7))
            p.drawLine(QPointF(x + 8, y - 1), QPointF(x - 5, y + 8))
        elif kind == 3:
            path = QPainterPath(QPointF(x - 7, y - 11))
            path.lineTo(x + 10, y)
            path.lineTo(x - 7, y + 11)
            path.closeSubpath()
            p.drawPath(path)
        else:
            for px, py in ((x - 10, y - 1), (x - 10, y + 10), (x + 1, y + 10), (x + 3, y - 12)):
                p.drawRect(QRectF(px, py, 9, 9))
        p.restore()

    # ----- dynamic parts -----
    def _caret(self, p, x, y, h, t, color):
        if (t % 1.06) < 0.56:
            p.fillRect(QRectF(x - 1, y, 2.4, h), QColor(color))

    def _sparkles(self, p, rect, t, t0, seed):
        age = t - t0
        if age < 0 or age > 1.2:
            return
        rnd = random.Random(seed)
        for _ in range(16):
            cx = rnd.uniform(rect.left() - 20, rect.right() + 20)
            cy = rect.top() - rnd.uniform(6, 22) if rnd.random() < 0.5 else rect.bottom() + rnd.uniform(6, 22)
            delay = rnd.uniform(0, 0.35)
            life = rnd.uniform(0.55, 0.85)
            k = (age - delay) / life
            if 0 <= k <= 1:
                size = rnd.uniform(7, 16) * math.sin(math.pi * k) + 1
                col = rnd.choice(("#8B73FF", "#2CCBEF", "#FFC857", "#FF6B86"))
                star(p, QPointF(cx, cy - k * 26), size, col, 1 - k * 0.7)

    def _inserted_text(self, p, layout, origin, width, height, t, t0, color_alpha=1.0):
        """Wipe in from the right (Persian reads right to left), then a fading highlight."""
        k = ease_out(span(t, t0, t0 + 0.38))
        if k <= 0:
            return
        hl = 1 - span(t, t0 + 0.4, t0 + 2.2)
        if hl > 0:
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(108, 77, 255, int(46 * hl)))
            p.drawRoundedRect(QRectF(origin.x() - 10, origin.y() - 6, width + 20, height + 8), 10, 10)
            p.restore()
        p.save()
        p.setClipRect(QRectF(origin.x() + width * (1 - k) - 30, origin.y() - 20, width * k + 60, height + 60))
        p.setOpacity(color_alpha)
        layout.draw(p, origin)
        p.restore()

    def _hud(self, p, t, caption, sub, pressed, show):
        """The caption chip at the top: text on the right, the hotkey caps on the left."""
        if show <= 0:
            return
        p.save()
        p.setOpacity(show)
        dy = (1 - show) * -18
        cap_font = font(self.fa, 32, 700)
        sub_font = font(self.fa, 21, 400)
        p.setFont(cap_font)
        tw = p.fontMetrics().horizontalAdvance(caption)
        if sub:
            p.setFont(sub_font)
            tw = max(tw, p.fontMetrics().horizontalAdvance(sub))
        keys_w = 250
        chip_w, chip_h = tw + keys_w + 92, (118 if sub else 92)
        chip = QRectF((W - chip_w) / 2, 26 + dy, chip_w, chip_h)
        soft_shadow(p, chip, chip_h / 2, strength=0.8, spread=22, dy=12)
        round_rect(p, chip, 26, QColor(255, 255, 255, 245), QPen(QColor("#E3DFF5"), 1.2))
        text_r = QRectF(chip.right() - 40 - tw, chip.top(), tw, chip_h)
        p.setPen(QColor("#17152A"))
        p.setFont(cap_font)
        top = QRectF(text_r.left(), chip.top() + (14 if sub else 0), tw, 56 if sub else chip_h)
        p.drawText(top, caption, text_opt(Qt.AlignRight | Qt.AlignVCenter, True))
        if sub:
            p.setPen(QColor("#6B6788"))
            p.setFont(sub_font)
            p.drawText(QRectF(text_r.left(), chip.top() + 66, tw, 36), sub,
                       text_opt(Qt.AlignRight | Qt.AlignVCenter, True))
        p.fillRect(QRectF(text_r.left() - 26, chip.top() + 18, 1.5, chip_h - 36), QColor("#E3DFF5"))
        # keycaps: Ctrl + Q
        kx = chip.left() + 34
        ky = chip.center().y() - 31
        self._key(p, QRectF(kx, ky, 112, 62), "Ctrl", pressed)
        p.setPen(QColor("#8C88A6"))
        p.setFont(font(self.ui, 26, 600))
        p.drawText(QRectF(kx + 112, ky, 34, 62), Qt.AlignCenter, "+")
        self._key(p, QRectF(kx + 146, ky, 62, 62), "Q", pressed)
        p.restore()

    def _key(self, p, r, label, pressed):
        down = 4 * pressed
        r = r.translated(0, down)
        if pressed > 0.01:
            glow = QRadialGradient(r.center(), r.width() * 0.9)
            glow.setColorAt(0, QColor(122, 92, 255, int(90 * pressed)))
            glow.setColorAt(1, QColor(122, 92, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(r.center(), r.width() * 0.9, r.width() * 0.9)
        round_rect(p, r.translated(0, 6 - down), 14, QColor("#CFCBE3"))                 # the key's side
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        if pressed > 0.5:
            g.setColorAt(0, QColor("#8B73FF"))
            g.setColorAt(1, QColor("#5B8CFF"))
        else:
            g.setColorAt(0, QColor("#FFFFFF"))
            g.setColorAt(1, QColor("#F1EFF9"))
        round_rect(p, r, 14, g, QPen(QColor("#D9D5EC"), 1.2))
        p.setPen(QColor("#FFFFFF") if pressed > 0.5 else QColor("#17152A"))
        p.setFont(font(self.ui, 24, 600))
        p.drawText(r, Qt.AlignCenter, label)

    def _window(self, p, img, t_in, t_out, t, from_x=0, to_x=0):
        k_in = ease_out(span(t, t_in, t_in + 0.7))
        k_out = ease_in_out(span(t, t_out, t_out + 0.7)) if t_out else 0
        if k_in <= 0 or k_out >= 1:
            return None
        x = WIN.left() - 60 + from_x * (1 - k_in) + to_x * k_out
        y = WIN.top() - 50 + 50 * (1 - k_in)
        p.save()
        p.setOpacity(k_in * (1 - k_out))
        p.drawImage(QPointF(x, y), img)
        p.restore()
        # the window's own rectangles are in image coordinates: offset them by the image origin
        return QPointF(x, y), k_in * (1 - k_out)

    def _pill(self, p, t, press, release, text_at, subtitle, words, levels, frame):
        """Recording bar: listening from press to release, busy until text_at, then done."""
        fade_in = span(t, press, press + 0.14)
        fade_out = 1 - span(t, text_at + 1.5, text_at + 1.72)
        opacity = min(fade_in, fade_out)
        if opacity <= 0:
            return
        if t < release:
            n = int((t - press) * FPS)
            lv = list(levels[max(0, n - self.bar.bars + 1):n + 1])
            lv = [0.0] * (self.bar.bars - len(lv)) + lv
            args = ("recording", "در حال شنیدن…", subtitle, t - press, lv)
        elif t < text_at:
            args = ("busy", "در حال نوشتن متن…", "چند لحظه صبر کنید", 0, [0.0] * self.bar.bars)
        else:
            args = ("done", "متن درج شد", f"{fa_digits(words)} کلمه", 0, [0.0] * self.bar.bars)
        state, title, sub, elapsed, lv = args
        self.bar.draw(p, W / 2, H - 22, 1.55, state, title, sub, elapsed, lv, frame, opacity)

    def _intro_outro(self, p, t, show, outro):
        if show <= 0:
            return
        p.save()
        p.setOpacity(show)
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0, QColor("#7A5CFF"))
        g.setColorAt(1, QColor("#21C3E6"))
        p.fillRect(QRectF(0, 0, W, H), g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(QPointF(W - 220, 150), 360, 360)
        p.drawEllipse(QPointF(180, H - 120), 300, 300)
        t0 = OUTRO_IN + 0.2 if outro else 0.15
        k_logo = ease_back(span(t, t0, t0 + 0.65))
        size = 190 * k_logo
        if size > 1:
            self.logo.render(p, QRectF(W / 2 - size / 2, (330 if outro else 300) - size / 2 + 95, size, size))
        k_title = ease_out(span(t, t0 + 0.35, t0 + 1.0))
        p.setOpacity(show * k_title)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font(self.ui, 78, 700))
        ty = (560 if outro else 530) + 30 * (1 - k_title)
        p.drawText(QRectF(0, ty, W, 100), Qt.AlignCenter, "MH-Speech to Text")
        k_sub = ease_out(span(t, t0 + 0.6, t0 + 1.25))
        p.setOpacity(show * k_sub)
        p.setFont(font(self.fa, 40, 500))
        sub = "رایگان، متن‌باز و کاملاً آفلاین" if outro else "نرم‌افزار پیشرفته‌ی تبدیل گفتار به متن فارسی"
        p.drawText(QRectF(0, ty + 110 + 20 * (1 - k_sub), W, 70), sub,
                   text_opt(Qt.AlignCenter, True))
        if outro:
            k_url = ease_out(span(t, t0 + 0.9, t0 + 1.5))
            p.setOpacity(show * k_url)
            pill = QRectF(W / 2 - 330, ty + 210, 660, 76)
            round_rect(p, pill, 38, QColor(255, 255, 255, 235))
            p.setPen(QColor("#5B3FE0"))
            p.setFont(font(self.ui, 32, 600))
            p.drawText(pill, Qt.AlignCenter, "hajloo.ir/mh-speech-to-text")
        p.restore()

    # ----- one frame -----
    def frame(self, i):
        t = i / FPS
        img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        p.drawImage(0, 0, self.backdrop)

        # Word: hold the hotkey
        word = self._window(p, self.word_img, WORD_IN, SWITCH, t, to_x=-260)
        if word:
            off, vis = word
            tr = self.word_text_rect.translated(off)
            f = font(self.fa, 25)
            lay, h, (cx, cy, ch) = paragraph(WORD_TEXT_FA, f, tr.width())
            if t < WORD_TEXT:
                self._caret(p, tr.right() + 3, tr.top() + 4, 36, t, "#1F2A44")
            else:
                p.save()
                p.setPen(QColor("#2A2A36"))        # QTextLayout draws with the painter's pen
                self._inserted_text(p, lay, tr.topLeft(), tr.width(), h, t, WORD_TEXT)
                p.restore()
                if t > WORD_TEXT + 0.45:
                    self._caret(p, tr.left() + cx - 3, tr.top() + cy + 4, ch - 4, t, "#1F2A44")
                self._sparkles(p, QRectF(tr.left(), tr.top(), tr.width(), h), t, WORD_TEXT, 3)
        # VS Code: press once to start, again to stop
        code = self._window(p, self.code_img, SWITCH + 0.15, None, t, from_x=260)
        if code:
            off, vis = code
            line_y = self.code_origin.y() + 4 * self.code_line_h + off.y()
            x = self.code_caret_x + off.x()
            if t < CODE_TEXT:
                self._caret(p, x, line_y + 5, self.code_line_h - 10, t, "#AEAFAD")
            else:
                f = font(self.mono, 22)
                f.setFamilies([self.mono, self.fa])
                lay = QTextLayout(CODE_TEXT_FA, f)
                lay.setTextOption(text_opt(Qt.AlignLeft, False))
                lay.beginLayout()
                line = lay.createLine()
                line.setLineWidth(1200)
                lay.endLayout()
                wdt = line.naturalTextWidth()
                p.save()
                p.setPen(QColor("#6A9955"))        # a comment's color
                self._inserted_text(p, lay, QPointF(x, line_y + (self.code_line_h - line.height()) / 2),
                                    wdt, line.height(), t, CODE_TEXT)
                p.restore()
                if t > CODE_TEXT + 0.45:
                    self._caret(p, x + wdt + 2, line_y + 5, self.code_line_h - 10, t, "#AEAFAD")
                self._sparkles(p, QRectF(x, line_y, wdt, self.code_line_h), t, CODE_TEXT, 9)

        # recording bar, as the app shows it
        if WORD_PRESS <= t < SWITCH:
            self._pill(p, t, WORD_PRESS, WORD_RELEASE, WORD_TEXT, "Esc برای لغو",
                       len(WORD_TEXT_FA.split()), self.levels_word, i)
        if CODE_TAP1 <= t < OUTRO_IN:
            self._pill(p, t, CODE_TAP1, CODE_TAP2, CODE_TEXT, "پایان با Ctrl + Q",
                       len(CODE_TEXT_FA.split()), self.levels_code, i)

        # captions with the hotkey caps
        if WORD_IN + 0.8 <= t < SWITCH + 0.3:
            before = t < WORD_RELEASE
            cap = "کلید میان‌بر را نگه دارید و صحبت کنید" if before else "رها کنید؛ متن همان‌جا نوشته می‌شود"
            sub = "کلید دلخواه شما؛ پیش‌فرض Ctrl + Q" if before else None
            show = min(span(t, WORD_IN + 0.8, WORD_IN + 1.2), 1 - span(t, SWITCH - 0.1, SWITCH + 0.3))
            flip = span(t, WORD_RELEASE, WORD_RELEASE + 0.3) if not before else 1
            pressed = ease_out(span(t, WORD_PRESS - 0.08, WORD_PRESS)) * (1 - span(t, WORD_RELEASE,
                                                                                    WORD_RELEASE + 0.08))
            self._hud(p, t, cap, sub, pressed, show * (0.4 + 0.6 * flip))
        if SWITCH + 0.9 <= t < OUTRO_IN:
            before = t < CODE_TAP2
            cap = "یا یک بار بزنید و صحبت کنید" if before else "دوباره بزنید؛ متن در هر برنامه‌ای نوشته می‌شود"
            show = min(span(t, SWITCH + 0.9, SWITCH + 1.3), 1 - span(t, OUTRO_IN - 0.4, OUTRO_IN))
            flip = span(t, CODE_TAP2, CODE_TAP2 + 0.3) if not before else 1
            pressed = 0.0
            for tap in (CODE_TAP1, CODE_TAP2):
                pressed = max(pressed, ease_out(span(t, tap - 0.06, tap)) * (1 - span(t, tap + TAP, tap + TAP + 0.08)))
            self._hud(p, t, cap, None, pressed, show * (0.4 + 0.6 * flip))

        # intro and outro
        self._intro_outro(p, t, 1 - ease_in_out(span(t, INTRO_END - 0.4, INTRO_END + 0.2)), outro=False)
        self._intro_outro(p, t, ease_in_out(span(t, OUTRO_IN, OUTRO_IN + 0.5)), outro=True)
        p.end()
        return img


# ---------------- sound ----------------
def mix_in(track, start, sig, gain=1.0, pan=0.0):
    a = int(start * SR)
    if a >= track.shape[1]:
        return
    sig = sig[: track.shape[1] - a] * gain
    left, right = math.sqrt(0.5 * (1 - pan)), math.sqrt(0.5 * (1 + pan))
    track[0, a:a + len(sig)] += sig * left * 1.41
    track[1, a:a + len(sig)] += sig * right * 1.41


def note(freq, dur, attack=0.01, decay=None, harmonics=((2, 0.25),)):
    t = np.arange(int(SR * dur)) / SR
    sig = np.sin(2 * np.pi * freq * t)
    for mult, amp in harmonics:
        sig += amp * np.sin(2 * np.pi * freq * mult * t)
    env = np.minimum(1, t / attack)
    env *= np.exp(-t / decay) if decay else np.minimum(1, (dur - t) / 0.3)
    return sig * env


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def music(track):
    """A soft pad with a slow arpeggio: Cmaj7, Am7, Fmaj7, G6 (96 bpm, one chord per bar)."""
    beat = 60 / 96
    bar = beat * 4
    chords = ((48, (60, 64, 67, 71)), (45, (57, 60, 64, 67)), (41, (53, 57, 60, 64)), (43, (55, 59, 62, 64)))
    n_bars = int(DURATION / bar) + 1
    rnd = random.Random(5)
    for b in range(n_bars):
        root, tones = chords[b % 4]
        start = b * bar
        for k, m in enumerate(tones):                                   # pad
            for det in (-0.0015, 0.0015):
                sig = note(midi(m) * (1 + det), bar + 0.9, attack=0.7, harmonics=((2, 0.12),))
                mix_in(track, start, sig, 0.018, pan=(k - 1.5) * 0.25)
        mix_in(track, start, note(midi(root), bar + 0.4, attack=0.08, decay=1.4), 0.07)   # bass
        for s in range(8):                                              # arpeggio, eighth notes
            m = tones[(s * 2 + b) % 4] + 12
            mix_in(track, start + s * beat / 2, note(midi(m), 1.2, attack=0.004, decay=0.32,
                                                     harmonics=((2, 0.35), (3, 0.1))),
                   0.022 + rnd.uniform(0, 0.008), pan=0.35 if s % 2 else -0.35)


def whoosh(dur=0.7):
    rnd = np.random.default_rng(4)
    n = int(SR * dur)
    noise = rnd.standard_normal(n)
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(n, 1 / SR)
    low = np.fft.irfft(spec * np.exp(-((f - 500) / 450) ** 2), n)
    high = np.fft.irfft(spec * np.exp(-((f - 2600) / 1600) ** 2), n)
    t = np.linspace(0, 1, n)
    sig = low * (1 - t) + high * t
    env = np.sin(np.pi * t) ** 2
    return sig / (np.abs(sig).max() + 1e-9) * env


def click(bright=True):
    n = int(SR * 0.04)
    t = np.arange(n) / SR
    rnd = np.random.default_rng(1 if bright else 2)
    sig = rnd.standard_normal(n) * np.exp(-t / 0.0022) * 0.6
    sig += np.sin(2 * np.pi * (2100 if bright else 1500) * t) * np.exp(-t / 0.006)
    return sig


def shimmer(seed):
    rnd = random.Random(seed)
    out = np.zeros(int(SR * 1.4))
    for k in range(7):
        s = note(rnd.choice((2093, 2349, 2637, 3136, 3520)), 0.9, attack=0.003, decay=0.18,
                 harmonics=((2, 0.2),))
        a = int(SR * k * 0.055)
        out[a:a + len(s)] += s * (0.5 + 0.5 * rnd.random())
    return out


def soundtrack():
    from dictation.sounds import _tone          # the app's own cue sounds
    track = np.zeros((2, int(SR * DURATION)))
    music(track)
    fade = np.ones(track.shape[1])
    fi, fo = int(SR * 1.2), int(SR * 2.4)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo)
    track *= fade

    def cue(name, notes, vol=0.16):
        return _tone(notes, vol).astype(np.float64) / 32767 * 2.2

    start, stop = cue("start", [(784, 0.07), (1175, 0.11)]), cue("stop", [(1047, 0.07), (784, 0.11)])
    done = cue("done", [(1319, 0.09)], vol=0.10)
    for at, sig, gain, pan in (
            (WORD_IN - 0.05, whoosh(), 0.16, -0.2),
            (WORD_PRESS - 0.06, click(), 0.12, 0), (WORD_PRESS, start, 1, 0),
            (WORD_RELEASE, click(False), 0.1, 0), (WORD_RELEASE + 0.02, stop, 1, 0),
            (WORD_TEXT, done, 1.4, 0), (WORD_TEXT + 0.03, shimmer(1), 0.07, 0.2),
            (SWITCH, whoosh(), 0.16, 0.2),
            (CODE_TAP1 - 0.06, click(), 0.12, 0), (CODE_TAP1, start, 1, 0),
            (CODE_TAP2 - 0.06, click(), 0.12, 0), (CODE_TAP2 + 0.02, stop, 1, 0),
            (CODE_TEXT, done, 1.4, 0), (CODE_TEXT + 0.03, shimmer(2), 0.07, -0.2),
            (OUTRO_IN - 0.1, whoosh(0.9), 0.14, 0)):
        mix_in(track, at, sig, gain, pan)
    for k, m in enumerate((72, 76, 79, 84)):                            # a warm closing arpeggio
        mix_in(track, OUTRO_IN + 0.35 + k * 0.11, note(midi(m), 2.2, attack=0.004, decay=0.7,
                                                       harmonics=((2, 0.3), (3, 0.08))), 0.09)
    track = np.tanh(track * 1.2) / np.tanh(1.2)                          # soft limiter
    return (track / np.abs(track).max() * 0.84).astype(np.float32)       # peak at -1.5 dBFS


# ---------------- output ----------------
def to_rgb(img):
    img = img.convertToFormat(QImage.Format_RGB888)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return arr[:, : img.width() * 3].reshape(img.height(), img.width(), 3).copy()


def encode(demo, out):
    audio = soundtrack()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".partial.mp4")
    container = av.open(str(tmp), "w", options={"movflags": "+faststart"})
    v = container.add_stream("libx264", rate=FPS,
                             options={"crf": "21", "preset": "slow", "tune": "animation", "profile": "high"})
    v.width, v.height, v.pix_fmt = W, H, "yuv420p"
    a = container.add_stream("aac", rate=SR, layout="stereo")
    a.bit_rate = 160_000
    n_frames = int(DURATION * FPS)
    apos = 0
    for i in range(n_frames):
        frame = av.VideoFrame.from_ndarray(to_rgb(demo.frame(i)), format="rgb24")
        frame.pts = i
        for packet in v.encode(frame):
            container.mux(packet)
        until = int((i + 1) / FPS * SR)
        while apos < min(until, audio.shape[1]):
            chunk = audio[:, apos:apos + 1024]
            if chunk.shape[1] < 1024:
                chunk = np.pad(chunk, ((0, 0), (0, 1024 - chunk.shape[1])))
            af = av.AudioFrame.from_ndarray(np.ascontiguousarray(chunk), format="fltp", layout="stereo")
            af.sample_rate, af.pts = SR, apos
            for packet in a.encode(af):
                container.mux(packet)
            apos += 1024
        if i % 90 == 0:
            print(f"  {i / FPS:4.1f}s", flush=True)
    for stream in (v, a):
        for packet in stream.encode(None):
            container.mux(packet)
    container.close()
    tmp.replace(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", help="comma-separated times (s): save PNG stills only")
    ap.add_argument("--out", default=str(SITE))
    args = ap.parse_args()
    app = QApplication(sys.argv)  # Qt needs an application for fonts and widgets
    app.setApplicationName("MH-Speech to Text demo")
    demo = Demo()
    out = Path(args.out)
    if args.frames:
        out.mkdir(parents=True, exist_ok=True)
        for s in args.frames.split(","):
            demo.frame(int(float(s) * FPS)).save(str(out / f"demo_{float(s):05.1f}.png"))
        print("stills ->", out)
        return
    video = out / "media" / "demo.mp4"
    print(f"rendering {DURATION:.0f}s at {W}x{H}, {FPS} fps")
    encode(demo, video)
    poster = Image.fromarray(to_rgb(demo.frame(int((WORD_TEXT + 0.9) * FPS))))
    poster.resize((1280, 720), Image.LANCZOS).save(out / "img" / "demo-poster.webp", quality=84)
    print(f"{video.relative_to(ROOT)}: {video.stat().st_size / 1e6:.1f} MB; poster img/demo-poster.webp")


if __name__ == "__main__":
    main()
