"""The system-tray icon and its Persian menu."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..branding import APP_NAME
from . import theme
from .icons import line_icon, logo_icon, tray_icon
from .widgets import combo_text

STATUS_TEXT = {
    "loading": "در حال آماده‌سازی مدل…",
    "ready": "آماده؛ {hotkey} را نگه دارید و صحبت کنید",
    "ready_toggle": "آماده؛ {hotkey} را بزنید و صحبت کنید",
    "recording": "در حال شنیدن…",
    "busy": "در حال نوشتن متن…",
    "error": "مدل بارگذاری نشد؛ تنظیمات را ببینید",
    "nomodel": "مدل گفتار نصب نیست",
}


class Tray(QObject):
    settings_requested = Signal()
    history_requested = Signal()
    about_requested = Signal()
    copy_last_requested = Signal()
    quit_requested = Signal()
    state_request = Signal(str)  # thread-safe

    def __init__(self, hotkey="ctrl+q", toggle=False):
        super().__init__()
        self.hotkey, self.toggle = hotkey, toggle
        self.state = "loading"
        self.icon = QSystemTrayIcon(tray_icon("loading"))
        self.menu = QMenu()
        self.menu.setLayoutDirection(Qt.RightToLeft)
        # rounded corners need a frameless, translucent popup
        self.menu.setWindowFlags(self.menu.windowFlags() | Qt.FramelessWindowHint
                                 | Qt.NoDropShadowWindowHint)
        self.menu.setAttribute(Qt.WA_TranslucentBackground)
        self._build()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.state_request.connect(self.set_state)
        self.set_state("loading")

    def _build(self):
        m = self.menu
        m.clear()
        muted = theme.c("muted")
        logo = QIcon()
        for s in (16, 20, 24, 32):  # keep the logo in color although the item is disabled
            pm = logo_icon().pixmap(s, s)
            logo.addPixmap(pm, QIcon.Normal)
            logo.addPixmap(pm, QIcon.Disabled)
        head = QAction(logo, APP_NAME, m)
        head.setEnabled(False)
        font = theme.font(10.5, 700)
        head.setFont(font)
        m.addAction(head)
        self.status_action = QAction("", m)
        self.status_action.setEnabled(False)
        m.addAction(self.status_action)
        m.addSeparator()
        for icon, text, signal in (
                ("settings", "تنظیمات", self.settings_requested),
                ("history", "تاریخچه‌ی متن‌ها", self.history_requested),
                ("copy", "کپی آخرین متن", self.copy_last_requested)):
            a = QAction(line_icon(icon, muted), text, m)
            a.triggered.connect(signal.emit)
            m.addAction(a)
        m.addSeparator()
        about = QAction(line_icon("info", muted), "درباره‌ی برنامه", m)
        about.triggered.connect(self.about_requested.emit)
        m.addAction(about)
        quit_ = QAction(line_icon("power", muted), "خروج", m)
        quit_.triggered.connect(self.quit_requested.emit)
        m.addAction(quit_)

    def restyle(self):
        """Rebuild the menu after a theme change (icon colors)."""
        self._build()
        self.set_state(self.state)

    def configure(self, hotkey, toggle):
        self.hotkey, self.toggle = hotkey, toggle
        self.set_state(self.state)

    def set_state(self, state):
        self.state = state
        key = "ready_toggle" if state == "ready" and self.toggle else state
        text = STATUS_TEXT.get(key, "").format(hotkey=combo_text(self.hotkey))
        self.status_action.setText(text)
        badge = {"ready": "normal", "nomodel": "error"}.get(state, state)
        self.icon.setIcon(tray_icon(badge))
        self.icon.setToolTip(f"{APP_NAME}\n{text}")

    def notify(self, title, text, seconds=6):
        self.icon.showMessage(title, text, logo_icon(), seconds * 1000)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.settings_requested.emit()

    def show(self):
        self.icon.show()

    def hide(self):
        self.icon.hide()
