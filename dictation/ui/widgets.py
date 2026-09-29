"""Small reusable widgets for the Persian RTL interface."""
import re

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt,
                            Signal)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import theme
from .theme import c


RLM = "‏"  # makes a line right-to-left even if it starts with Latin
LRM = "‎"  # keeps a Latin run's trailing punctuation, e.g. ")", with that run


def rtl(text: str) -> str:
    return RLM + text


def ltr(text: str) -> str:
    return LRM + text + LRM


def label(text="", obj=None, wrap=False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse if wrap else Qt.NoTextInteraction)
    return lb


def set_msg(lb: QLabel, text: str, kind="Hint"):
    """Show a status line (Hint / Success / Warning / Danger); hidden when empty
    so it doesn't leave a gap in the card."""
    lb.setObjectName(kind)
    lb.setText(text)
    lb.setVisible(bool(text))
    lb.style().unpolish(lb)
    lb.style().polish(lb)


def device_label(name: str) -> str:
    """A microphone name for display in the RTL interface. Parentheses become a
    dot: a Latin name ending in ")" is laid out with the bracket flipped to the
    wrong side, and Windows often cuts names mid-parenthesis anyway.
    "Microphone (USB Audio)" -> "Microphone · USB Audio"."""
    name = re.sub(r"\s*\(\s*", " · ", name.strip()).replace(")", "").strip(" ·")
    return ltr(name)


class Card(QFrame):
    """Rounded surface grouping related settings."""

    def __init__(self, title=None, text=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(10)
        if title:
            self.body.addWidget(label(title, "CardTitle"))
        if text:
            self.body.addWidget(label(text, "CardText", wrap=True))

    def add(self, widget_or_layout):
        if isinstance(widget_or_layout, QWidget):
            self.body.addWidget(widget_or_layout)
        else:
            self.body.addLayout(widget_or_layout)
        return widget_or_layout

    def separator(self):
        line = QFrame()
        line.setObjectName("Separator")
        self.body.addWidget(line)


class SettingRow(QWidget):
    """Title and description on the right, the control on the left (RTL)."""

    def __init__(self, title, text=None, control=None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "CardTitle"))
        if text:
            self.text_label = label(text, "CardText", wrap=True)
            texts.addWidget(self.text_label)
        row.addLayout(texts, 1)
        if control is not None:
            row.addWidget(control, 0, Qt.AlignVCenter)


class ToggleSwitch(QAbstractButton):
    """An animated on/off switch; in RTL the knob sits on the left when on."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(46, 26)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        on = QColor(c("primary"))
        off = QColor(c("track"))
        mix = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(mix if self.isEnabled() else QColor(c("track")))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        travel = r.width() - d - 6
        rtl = self.layoutDirection() == Qt.RightToLeft
        x = r.x() + 3 + (travel * (1 - self._pos) if rtl else travel * self._pos)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 3, d, d))


class SegmentedControl(QFrame):
    """A row of mutually exclusive options, like a pill tab bar."""
    changed = Signal(str)

    def __init__(self, options, value=None, parent=None):
        """options: list of (value, label)."""
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, text in options:
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            row.addWidget(b)
        self.set_value(value if value is not None else options[0][0])

    def set_value(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def value(self):
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return None


class LevelMeter(QWidget):
    """Microphone level bar with a smooth fall-off and a peak marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(14)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._value = 0.0
        self._peak = 0.0

    def set_level(self, rms: float):
        # speech RMS is ~0.01–0.2; a square root spreads that over the bar
        v = min(1.0, (max(rms, 0.0) ** 0.5) * 2.2)
        self._value = max(v, self._value * 0.82)
        self._peak = max(v, self._peak - 0.012)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c("track")))
        p.drawRoundedRect(r, rad, rad)
        rtl = self.layoutDirection() == Qt.RightToLeft
        w = r.width() * self._value
        if w > 1:
            fill = QRectF(r.right() - w, 0, w, r.height()) if rtl else QRectF(0, 0, w, r.height())
            g = QLinearGradient(fill.topRight() if rtl else fill.topLeft(),
                                fill.topLeft() if rtl else fill.topRight())
            g.setColorAt(0, QColor(c("accent")))
            g.setColorAt(1, QColor(c("primary")))
            p.setBrush(g)
            p.drawRoundedRect(fill, rad, rad)
        if self._peak > 0.02:
            x = r.width() * (1 - self._peak) if rtl else r.width() * self._peak
            p.setBrush(QColor(c("text")))
            p.drawRoundedRect(QRectF(max(0, x - 1.5), 2, 3, r.height() - 4), 1.5, 1.5)


KEY_LABELS = {
    "ctrl": "Ctrl", "lctrl": "Ctrl چپ", "rctrl": "Ctrl راست", "shift": "Shift",
    "lshift": "Shift چپ", "rshift": "Shift راست", "alt": "Alt", "lalt": "Alt چپ",
    "ralt": "Alt راست", "win": "Win", "lwin": "Win", "rwin": "Win راست", "space": "Space",
    "esc": "Esc", "capslock": "Caps Lock", "tab": "Tab", "enter": "Enter",
    "insert": "Insert", "pause": "Pause", "scrolllock": "Scroll Lock",
}


def key_label(name: str) -> str:
    return KEY_LABELS.get(name, name.upper())


def combo_text(combo: str) -> str:
    return " + ".join(key_label(k) for k in combo.split("+") if k)


class KeyCaps(QWidget):
    """Shows a key combination as keyboard keycaps (always left-to-right, like
    shortcuts are written)."""

    def __init__(self, combo="", parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LeftToRight)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self.set_combo(combo)

    def set_combo(self, combo, placeholder=None):
        while self._row.count():
            w = self._row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._row.addStretch(1)  # keycaps hug the right edge, like the rest of the RTL page
        if placeholder:
            lb = label(placeholder, "Muted")
            self._row.addWidget(lb)
            return
        for i, k in enumerate(k for k in combo.split("+") if k):
            if i:
                self._row.addWidget(label("+", "Muted"))
            self._row.addWidget(_Cap(key_label(k)))


class _Cap(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(34)
        self.setFont(theme.font(10, 600))

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(max(s.width() + 22, 36), s.height() + 12)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c("border")))
        p.drawRoundedRect(r.translated(0, 2), 8, 8)
        p.setBrush(QColor(c("surface")))
        p.setPen(QPen(QColor(c("border")), 1))
        p.drawRoundedRect(r, 8, 8)
        p.setPen(QColor(c("text")))
        p.drawText(r, Qt.AlignCenter, self.text())


def rounded_pixmap_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path
