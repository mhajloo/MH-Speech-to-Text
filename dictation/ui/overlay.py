"""The recording bar: a dark glass pill at the bottom of the screen.

It must never take the keyboard focus (the text goes to whatever window the
user is typing in), so it is a frameless tool window that is shown without
activation, cannot be focused and lets mouse clicks pass through.
"""
import ctypes
import math
import time
from collections import deque

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QCursor, QGuiApplication, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient, QTextOption)
from PySide6.QtWidgets import QWidget

from . import theme
from .theme import fa

W, H = 340, 66          # the pill
MARGIN = 20             # room for the soft shadow
BOTTOM_GAP = 26         # distance above the taskbar
BARS = 22

GLASS_TOP = QColor(34, 30, 54, 242)
GLASS_BOTTOM = QColor(22, 20, 36, 242)
TEXT = QColor("#FFFFFF")
SUBTEXT = QColor("#B9B5D8")
RED_A, RED_B = QColor("#FF6B86"), QColor("#FF2D55")
VIOLET, CYAN = QColor("#8B73FF"), QColor("#2CCBEF")
GREEN_A, GREEN_B = QColor("#4BE39A"), QColor("#16B368")
AMBER_A, AMBER_B = QColor("#FFD166"), QColor("#F29E0C")

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT = 0x08000000, 0x80, 0x20


class RecordingBar(QWidget):
    # thread-safe entry points: emit from any thread
    request = Signal(str, str, str)  # state, title, subtitle

    def __init__(self, level_source=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(W + 2 * MARGIN, H + 2 * MARGIN)
        self.level_source = level_source or (lambda: 0.0)

        self.state = "hidden"
        self.title = ""
        self.subtitle = ""
        self.started = 0.0
        self.levels = deque([0.0] * BARS, maxlen=BARS)
        self._smooth = 0.0
        self._tick = 0
        self._hide_at = None
        self._styled = False

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._frame)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.finished.connect(self._fade_done)
        self.request.connect(self._apply)

    # ----- public API (call from any thread) -----
    def recording(self, subtitle=""):
        self.request.emit("recording", "در حال شنیدن…", subtitle)

    def busy(self):
        self.request.emit("busy", "در حال نوشتن متن…", "چند لحظه صبر کنید")

    def done(self, words: int):
        self.request.emit("done", "متن درج شد", f"{fa(words)} کلمه")

    def message(self, kind, title, subtitle=""):
        """kind: info | warning | error"""
        self.request.emit(kind, title, subtitle)

    def hide_bar(self):
        self.request.emit("hidden", "", "")

    # ----- internals (UI thread) -----
    def _apply(self, state, title, subtitle):
        if state == "hidden":
            self._start_fade_out()
            return
        prev = self.state
        self.state, self.title, self.subtitle = state, title, subtitle
        if state == "recording" and prev != "recording":
            self.started = time.monotonic()
            self.levels = deque([0.0] * BARS, maxlen=BARS)
        linger = {"done": 1.3, "info": 3.5, "warning": 4.0, "error": 4.5}.get(state)
        self._hide_at = time.monotonic() + linger if linger else None
        if not self.isVisible() or self._fade.endValue() == 0.0:
            self._place()
            self._fade.stop()
            self.setWindowOpacity(0.0)
            self.show()
            self._make_noactivate()
            self._fade.setDuration(140)
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(1.0)
            self._fade.setEasingCurve(QEasingCurve.OutCubic)
            self._fade.start()
        self._timer.start()
        self.update()

    def _start_fade_out(self):
        if not self.isVisible() or self._fade.endValue() == 0.0:
            return
        self._fade.stop()
        self._fade.setDuration(220)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.InCubic)
        self._fade.start()

    def _fade_done(self):
        if self._fade.endValue() == 0.0:
            self.hide()
            self._timer.stop()
            self.state = "hidden"

    def _make_noactivate(self):
        if self._styled:
            return
        hwnd = int(self.winId())
        u = ctypes.windll.user32
        u.GetWindowLongW.restype = ctypes.c_long
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT)
        self._styled = True

    def _place(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.bottom() - self.height() - BOTTOM_GAP + MARGIN)

    def _frame(self):
        self._tick += 1
        if self.state == "recording":
            lv = min(1.0, (max(self.level_source(), 0.0) ** 0.5) * 2.4)
            self._smooth = max(lv, self._smooth * 0.8)
            self.levels.append(lv)
        if self._hide_at and time.monotonic() >= self._hide_at:
            self._hide_at = None
            self._start_fade_out()
        self.update()

    # ----- painting -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setLayoutDirection(Qt.RightToLeft)
        pill = QRectF(MARGIN, MARGIN, W, H)
        self._paint_shadow(p, pill)

        g = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        g.setColorAt(0, GLASS_TOP)
        g.setColorAt(1, GLASS_BOTTOM)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(g)
        p.drawRoundedRect(pill, H / 2, H / 2)

        orb = QRectF(pill.right() - 14 - 42, pill.center().y() - 21, 42, 42)
        self._paint_orb(p, orb)

        text_right = orb.left() - 12
        wave_w = 118 if self.state in ("recording", "busy") else 0
        text_rect = QRectF(pill.left() + 18 + wave_w, pill.top() + 10,
                           text_right - pill.left() - 18 - wave_w, H - 20)
        self._paint_text(p, text_rect)
        if wave_w:
            self._paint_wave(p, QRectF(pill.left() + 20, pill.top() + 14, wave_w - 14, H - 28))

    def _paint_shadow(self, p, pill):
        p.setPen(Qt.NoPen)
        for i in range(10, 0, -1):
            p.setBrush(QColor(8, 6, 20, int(7 + (10 - i) * 1.6)))
            r = pill.adjusted(-i, -i + 4, i, i + 4)
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

    def _orb_colors(self):
        return {"recording": (RED_A, RED_B), "done": (GREEN_A, GREEN_B),
                "warning": (AMBER_A, AMBER_B), "error": (RED_A, RED_B),
                "info": (CYAN, VIOLET)}.get(self.state, (VIOLET, CYAN))

    def _paint_orb(self, p, orb):
        a, b = self._orb_colors()
        center = orb.center()
        if self.state == "recording":  # halo breathing with the voice
            halo = 6 + self._smooth * 10 + math.sin(self._tick / 6) * 1.5
            rg = QRadialGradient(center, orb.width() / 2 + halo)
            rg.setColorAt(0.55, QColor(a.red(), a.green(), a.blue(), 110))
            rg.setColorAt(1.0, QColor(a.red(), a.green(), a.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(rg)
            p.drawEllipse(center, orb.width() / 2 + halo, orb.width() / 2 + halo)
        g = QLinearGradient(orb.topRight(), orb.bottomLeft())
        g.setColorAt(0, a)
        g.setColorAt(1, b)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(orb)

        if self.state == "busy":  # spinning ring
            ring = orb.adjusted(-4, -4, 4, 4)
            cg = QConicalGradient(center, -(self._tick * 9) % 360)
            cg.setColorAt(0.0, CYAN)
            cg.setColorAt(0.5, QColor(139, 115, 255, 0))
            cg.setColorAt(1.0, CYAN)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(cg, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring, 0, 360 * 16)

        p.setPen(QPen(QColor("#FFFFFF"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx, cy = center.x(), center.y()
        if self.state == "recording" or self.state == "busy":
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(cx - 4.5, cy - 11, 9, 15), 4.5, 4.5)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#FFFFFF"), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(cx - 8, cy - 7, 16, 14), 180 * 16, 180 * 16)
            p.drawLine(QPointF(cx, cy + 7), QPointF(cx, cy + 11))
        elif self.state == "done":
            path = QPainterPath(QPointF(cx - 8, cy + 0.5))
            path.lineTo(cx - 2.5, cy + 6)
            path.lineTo(cx + 8.5, cy - 6)
            p.setPen(QPen(QColor("#FFFFFF"), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        elif self.state == "error":
            p.setPen(QPen(QColor("#FFFFFF"), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 6, cy - 6), QPointF(cx + 6, cy + 6))
            p.drawLine(QPointF(cx + 6, cy - 6), QPointF(cx - 6, cy + 6))
        else:  # warning / info: an exclamation or i
            p.setPen(QPen(QColor("#FFFFFF"), 3.2, Qt.SolidLine, Qt.RoundCap))
            if self.state == "warning":
                p.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 2))
                p.drawPoint(QPointF(cx, cy + 8))
            else:
                p.drawPoint(QPointF(cx, cy - 8))
                p.drawLine(QPointF(cx, cy - 2), QPointF(cx, cy + 8))

    def _paint_text(self, p, rect):
        sub = self.subtitle
        if self.state == "recording":
            secs = int(time.monotonic() - self.started)
            clock = f"{fa(secs // 60)}:{fa(f'{secs % 60:02d}')}"
            sub = f"{clock}  ·  {sub}" if sub else clock
        # force right-to-left paragraphs: a line starting with "Esc" or a digit
        # would otherwise be laid out left-to-right
        opt = QTextOption(Qt.AlignRight | Qt.AlignVCenter)
        opt.setTextDirection(Qt.RightToLeft)
        opt.setWrapMode(QTextOption.NoWrap)
        p.setPen(TEXT)
        p.setFont(theme.font(11.2, 600))
        title_rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.56)
        p.drawText(title_rect, self._elide(p, self.title, rect.width()), opt)
        if sub:
            p.setPen(SUBTEXT)
            p.setFont(theme.font(9, 400))
            sub_rect = QRectF(rect.left(), rect.top() + rect.height() * 0.56, rect.width(), rect.height() * 0.44)
            p.drawText(sub_rect, self._elide(p, sub, rect.width()), opt)

    @staticmethod
    def _elide(p, text, width):
        # eliding works on the logical order: ElideRight drops the end of the
        # sentence (the visual left of a right-to-left line) and keeps the clock
        return p.fontMetrics().elidedText(text, Qt.ElideRight, int(width))

    def _paint_wave(self, p, rect):
        n = BARS
        gap = rect.width() / n
        bw = max(2.2, gap * 0.5)
        mid = rect.center().y()
        p.setPen(Qt.NoPen)
        g = QLinearGradient(rect.topLeft(), rect.topRight())
        g.setColorAt(0, CYAN)
        g.setColorAt(1, VIOLET)
        p.setBrush(g)
        for i in range(n):
            if self.state == "recording":
                # newest level at the right (next to the orb), older ones drift left
                v = self.levels[i]
                h = 3 + v * (rect.height() - 3)
            else:  # busy: a calm travelling wave
                v = 0.5 + 0.5 * math.sin(self._tick / 4 - i * 0.55)
                h = 3 + v * (rect.height() * 0.45)
            x = rect.left() + i * gap + (gap - bw) / 2
            p.drawRoundedRect(QRectF(x, mid - h / 2, bw, h), bw / 2, bw / 2)
