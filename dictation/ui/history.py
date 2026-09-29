"""The history window: past dictations, newest first, with search and copy."""
import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..branding import APP_NAME
from ..paths import HISTORY_PATH
from .icons import line_icon, logo_icon
from .theme import c, fa
from .widgets import Card, label

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی",
          "بهمن", "اسفند"]
LIMIT = 300


def to_jalali(gy, gm, gd):
    """Gregorian → Jalali (Solar Hijri) date."""
    days_before = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + gd + days_before[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def jalali_text(stamp: str) -> str:
    try:
        t = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return stamp
    y, m, d = to_jalali(t.year, t.month, t.day)
    return f"{fa(d)} {MONTHS[m - 1]} {fa(y)}، ساعت {fa(t.strftime('%H:%M'))}"


def load_history():
    if not HISTORY_PATH.exists():
        return []
    items = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-LIMIT:]:
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(items))


class HistoryWindow(QWidget):
    def __init__(self, copy_text):
        super().__init__()
        self.copy_text = copy_text
        self.setObjectName("Window")
        self.setWindowTitle(f"تاریخچه‌ی متن‌ها · {APP_NAME}")
        self.setWindowIcon(logo_icon())
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(720, 620)
        col = QVBoxLayout(self)
        col.setContentsMargins(28, 24, 28, 20)
        col.setSpacing(12)
        col.addWidget(label("تاریخچه‌ی متن‌ها", "PageTitle"))
        col.addWidget(label("متن‌هایی که دیکته کرده‌اید؛ فقط روی همین کامپیوتر نگه داشته می‌شوند.",
                            "PageSubtitle", wrap=True))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجو در متن‌ها…")
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)
        clear = QPushButton("پاک کردن همه")
        clear.setObjectName("Danger")
        clear.setIcon(line_icon("trash", c("danger")))
        clear.clicked.connect(self._clear)
        bar.addWidget(clear)
        col.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        col.addWidget(self.scroll, 1)
        self.items = []

    def showEvent(self, e):
        super().showEvent(e)
        self.items = load_history()
        self._fill()

    def _fill(self):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)
        q = self.search.text().strip()
        shown = [it for it in self.items if not q or q in it.get("text", "")]
        if not shown:
            empty = QLabel("هنوز متنی دیکته نشده است." if not self.items else "چیزی پیدا نشد.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignCenter)
            lay.addStretch(1)
            lay.addWidget(empty)
        for it in shown:
            card = Card()
            head = QHBoxLayout()
            head.addWidget(label(jalali_text(it.get("time", "")), "Faint"), 1)
            copy = QPushButton("کپی")
            copy.setObjectName("Link")
            copy.setIcon(line_icon("copy", c("primary")))
            copy.clicked.connect(lambda _=False, t=it.get("text", ""): self.copy_text(t))
            head.addWidget(copy)
            card.add(head)
            card.add(label(it.get("text", ""), None, wrap=True))
            lay.addWidget(card)
        lay.addStretch(1)
        self.scroll.setWidget(body)

    def _clear(self):
        box = QMessageBox(self)
        box.setLayoutDirection(Qt.RightToLeft)
        box.setWindowTitle("پاک کردن تاریخچه")
        box.setText("همه‌ی متن‌های ذخیره‌شده پاک شوند؟ این کار برگشت‌پذیر نیست.")
        yes = box.addButton("پاک کن", QMessageBox.DestructiveRole)
        box.addButton("انصراف", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            HISTORY_PATH.unlink(missing_ok=True)
            self.items = []
            self._fill()
