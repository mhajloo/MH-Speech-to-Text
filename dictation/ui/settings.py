"""The settings window: a right-hand sidebar and five pages. Every change is
applied and saved immediately (no OK/Apply buttons)."""
import os
import threading

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QRadioButton, QScrollArea,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import autostart, modelstore, sysinfo
from ..branding import (APP_DESCRIPTION, APP_NAME, APP_TAGLINE, APP_VERSION, AUTHOR, GITHUB,
                        GITHUB_LABEL, LICENSE_NAME, WEBSITE, WEBSITE_LABEL)
from ..hotkey import check_combo
from ..paths import MODELS_DIR, NOTICE_PATH
from ..audio import default_input_name, input_devices, is_bluetooth
from .icons import LOGO_SVG, line_icon, logo_icon, svg_pixmap
from .theme import c, fa
from .widgets import (Card, KeyCaps, LevelMeter, SegmentedControl, SettingRow, ToggleSwitch,
                      combo_text, device_label, label, ltr, rtl, set_msg)

ABOUT_TEXT = [
    "MH-Speech to Text گفتار فارسی را در هر برنامه‌ای به متن تبدیل می‌کند. کلید میان‌بر را "
    "نگه دارید، صحبت کنید و رها کنید؛ متن همان‌جایی نوشته می‌شود که مکان‌نما هست، چه در Word "
    "و مرورگر، چه در تلگرام یا هر برنامه‌ی دیگری.",
    "کلمات همان‌طور که گفته‌اید نوشته می‌شوند و فقط املا، نیم‌فاصله و علائم نگارشی مرتب می‌شود.",
    "تبدیل گفتار کاملاً روی کامپیوتر خودتان انجام می‌شود؛ صدای شما به هیچ سروری فرستاده "
    "نمی‌شود و جایی ذخیره نمی‌شود.",
    "این برنامه متن‌باز است و کد آن در گیت‌هاب در دسترس همه است.",
]

CREDITS = [
    ("مدل گفتار", "Whisper از OpenAI، نسخه‌ی فارسی AmirMohseni", "Apache-2.0"),
    ("موتور تبدیل", "faster-whisper و CTranslate2", "MIT"),
    ("رابط کاربری", "Qt و PySide6", "LGPL-3.0"),
    ("قلم", "وزیرمتن، طراحی زنده‌یاد صابر راستی‌کردار", "OFL-1.1"),
    ("واژه‌های نیم‌فاصله", "Hazm و Common Voice", "MIT / CC0"),
]

PAGES = [("general", "general", "عمومی"), ("mic", "mic", "میکروفون"),
         ("text", "text", "متن و املا"), ("model", "model", "مدل گفتار"),
         ("about", "info", "درباره‌ی برنامه")]


def nav_icon(name):
    icon = QIcon()
    for s in (18, 24, 36):
        icon.addPixmap(line_icon(name, c("muted")).pixmap(s, s), QIcon.Normal, QIcon.Off)
        icon.addPixmap(line_icon(name, c("primary")).pixmap(s, s), QIcon.Normal, QIcon.On)
    return icon


class SettingsWindow(QWidget):
    hotkey_captured = Signal(object)
    import_finished = Signal(object, object)  # model id, error

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("Window")
        self.setWindowTitle(f"تنظیمات {APP_NAME}")
        self.setWindowIcon(logo_icon())
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(940, 660)
        self.setMinimumSize(820, 560)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.pages = {}
        for key, _, _ in PAGES:
            page = getattr(self, f"_page_{key}")()
            self.pages[key] = page
            self.stack.addWidget(page)
        self.stack.currentChanged.connect(self._page_changed)

        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(40)
        self._meter_timer.timeout.connect(lambda: self.meter.set_level(self.app.recorder.level))
        self.hotkey_captured.connect(self._hotkey_captured)
        self.import_finished.connect(self._import_finished)
        app.engine_status_changed.connect(self._refresh_model)
        app.devices_changed.connect(self._refresh_devices)
        self.show_page("general")

    # ----- frame -----
    def _sidebar(self):
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(236)
        col = QVBoxLayout(side)
        col.setContentsMargins(16, 22, 16, 16)
        col.setSpacing(4)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(svg_pixmap(LOGO_SVG, 44, self.devicePixelRatioF()))
        head.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label(rtl(APP_NAME), "AppName"))
        names.addWidget(label(APP_TAGLINE, "AppTagline"))
        head.addLayout(names, 1)
        col.addLayout(head)
        col.addSpacing(20)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for key, icon, text in PAGES:
            b = QPushButton(text)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setIcon(nav_icon(icon))
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            col.addWidget(b)
        col.addStretch(1)
        col.addWidget(label(f"نسخه‌ی {fa(APP_VERSION)}", "Faint"))
        return side

    def _page(self, title, subtitle):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(32, 28, 32, 28)
        col.setSpacing(14)
        col.addWidget(label(title, "PageTitle"))
        col.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        col.addSpacing(6)
        scroll.setWidget(body)
        scroll.col = col
        return scroll

    def show_page(self, key):
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])

    def _page_changed(self, _):
        self._update_monitoring()

    def _update_monitoring(self):
        on = self.isVisible() and self.stack.currentWidget() is self.pages.get("mic")
        self.app.recorder.monitor(on)
        (self._meter_timer.start if on else self._meter_timer.stop)()

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_devices()
        self._refresh_model()
        self.autostart_switch.setChecked(autostart.is_enabled())
        self._update_monitoring()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._update_monitoring()
        if self.app.hotkey:
            self.app.hotkey.end_capture()

    def closeEvent(self, e):
        e.ignore()  # the app lives in the tray; closing only hides the window
        self.hide()

    # ----- general -----
    def _page_general(self):
        page = self._page("عمومی", "کلید میان‌بر، شیوه‌ی ضبط و رفتار برنامه.")
        cfg = self.app.cfg

        card = Card("کلید میان‌بر", "این کلید را در هر برنامه‌ای نگه دارید و صحبت کنید؛ "
                                    "با رها کردنش، متن همان‌جا نوشته می‌شود.")
        row = QHBoxLayout()
        self.keycaps = KeyCaps(cfg.hotkey)
        row.addWidget(self.keycaps, 1)
        self.change_key = QPushButton("تغییر کلید")
        self.change_key.setIcon(line_icon("keyboard", c("text")))
        self.change_key.setCursor(Qt.PointingHandCursor)
        self.change_key.clicked.connect(self._toggle_capture)
        row.addWidget(self.change_key)
        card.add(row)
        self.key_msg = label("", "Hint", wrap=True)
        set_msg(self.key_msg, "")
        card.add(self.key_msg)
        page.col.addWidget(card)

        card = Card("شیوه‌ی ضبط")
        self.mode = SegmentedControl([("hold", "نگه داشتن کلید"), ("toggle", "یک بار زدن")],
                                     cfg.record_mode)
        self.mode.changed.connect(self._mode_changed)
        card.add(self.mode)
        self.mode_text = label("", "CardText", wrap=True)
        card.add(self.mode_text)
        self._mode_changed(cfg.record_mode, save=False)
        page.col.addWidget(card)

        card = Card("رفتار برنامه")
        self.autostart_switch = ToggleSwitch(autostart.is_enabled())
        self.autostart_switch.toggled.connect(self._autostart)
        card.add(SettingRow("اجرا با شروع ویندوز", "برنامه در پس‌زمینه آماده می‌ماند.",
                            self.autostart_switch))
        card.separator()
        card.add(self._switch_row("صدای شروع و پایان", "بوق کوتاه هنگام شروع و پایان ضبط.", "sounds"))
        card.separator()
        card.add(self._switch_row("نوار ضبط", "نمایش وضعیت ضبط در پایین صفحه.", "show_overlay"))
        card.separator()
        card.add(self._switch_row("ذخیره‌ی تاریخچه", "متن‌های دیکته‌شده روی همین کامپیوتر نگه داشته "
                                                    "می‌شوند.", "save_history"))
        page.col.addWidget(card)

        card = Card("ظاهر")
        seg = SegmentedControl([("system", "مطابق ویندوز"), ("light", "روشن"), ("dark", "تیره")],
                               cfg.theme)
        seg.changed.connect(lambda v: self.app.update_config(theme=v))
        card.add(seg)
        page.col.addWidget(card)
        page.col.addStretch(1)
        return page

    def _switch_row(self, title, text, field):
        sw = ToggleSwitch(bool(getattr(self.app.cfg, field)))
        sw.toggled.connect(lambda on: self.app.update_config(**{field: on}))
        return SettingRow(title, text, sw)

    def _mode_changed(self, mode, save=True):
        combo = self.app.cfg.hotkey
        if mode == "toggle":
            text = (f"یک بار {combo_text(combo)} را بزنید، صحبت کنید و برای پایان دوباره بزنید. "
                    "برای دیکته‌های طولانی راحت‌تر است.")
        else:
            text = f"تا وقتی {combo_text(combo)} را نگه داشته‌اید ضبط ادامه دارد."
        self.mode_text.setText(text)
        if save:
            self.app.update_config(record_mode=mode)

    def _autostart(self, on):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            set_msg(self.key_msg, f"تنظیم اجرای خودکار ممکن نشد: {e}", "Danger")

    def _toggle_capture(self):
        hk = self.app.hotkey
        if hk is None:
            return
        if hk._capture is not None:
            hk.end_capture()
            self._capture_ui(False)
            return
        self._capture_ui(True)
        hk.begin_capture(self.hotkey_captured.emit)

    def _capture_ui(self, on):
        if on:
            self.keycaps.set_combo("", placeholder="کلیدهای جدید را فشار دهید…")
            self.change_key.setText("انصراف")
            set_msg(self.key_msg, "ترکیب دلخواه را فشار دهید و رها کنید؛ Esc برای انصراف.")
        else:
            self.keycaps.set_combo(self.app.cfg.hotkey)
            self.change_key.setText("تغییر کلید")

    def _hotkey_captured(self, combo):
        self._capture_ui(False)
        if combo is None:
            set_msg(self.key_msg, "")
            return
        problem = check_combo(combo)
        if problem:
            set_msg(self.key_msg, problem, "Danger")
        else:
            self.app.update_config(hotkey=combo)
            self.keycaps.set_combo(combo)
            set_msg(self.key_msg, "کلید جدید ذخیره شد.", "Success")
            self._mode_changed(self.app.cfg.record_mode, save=False)

    # ----- microphone -----
    def _page_mic(self):
        page = self._page("میکروفون", "میکروفونی که صدایتان را ضبط می‌کند.")
        card = Card("انتخاب میکروفون")
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        card.add(self.device_combo)
        card.add(label("سطح صدا؛ چیزی بگویید تا نوار حرکت کند:", "CardText"))
        self.meter = LevelMeter()
        card.add(self.meter)
        self.mic_msg = label("", "Hint", wrap=True)
        set_msg(self.mic_msg, "")
        card.add(self.mic_msg)
        page.col.addWidget(card)

        card = Card()
        self.keep_open_switch = ToggleSwitch(self.app.cfg.keep_mic_open)
        self.keep_open_switch.toggled.connect(lambda on: self.app.update_config(keep_mic_open=on))
        self.keep_open_row = SettingRow(
            "میکروفون همیشه آماده",
            "شروع ضبط بدون تأخیر و بدون جا افتادن اولین کلمه. تا وقتی برنامه باز است، "
            "ویندوز نشانگر استفاده از میکروفون را نشان می‌دهد؛ صدا جایی ذخیره نمی‌شود.",
            self.keep_open_switch)
        card.add(self.keep_open_row)
        self.bt_note = label("", "Warning", wrap=True)
        set_msg(self.bt_note, "")
        card.add(self.bt_note)
        page.col.addWidget(card)

        card = Card("نوار حرکت نمی‌کند؟", "ممکن است دسترسی برنامه‌ها به میکروفون در تنظیمات حریم خصوصی "
                                         "ویندوز بسته باشد.")
        b = QPushButton("باز کردن تنظیمات حریم خصوصی میکروفون")
        b.setIcon(line_icon("shield", c("text")))
        b.clicked.connect(lambda: os.startfile("ms-settings:privacy-microphone"))
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        card.add(row)
        page.col.addWidget(card)
        page.col.addStretch(1)
        return page

    def _refresh_devices(self):
        combo = self.device_combo
        combo.blockSignals(True)
        combo.clear()
        default = default_input_name()
        combo.addItem(f"پیش‌فرض ویندوز: {device_label(default) if default else 'پیدا نشد'}", None)
        for name in input_devices():
            combo.addItem(device_label(name), name)
        idx = combo.findData(self.app.cfg.mic_device) if self.app.cfg.mic_device else 0
        combo.setCurrentIndex(max(idx, 0))
        combo.blockSignals(False)
        self._update_mic_notes()

    def _device_changed(self, _):
        self.app.update_config(mic_device=self.device_combo.currentData())
        self._update_mic_notes()

    def _update_mic_notes(self):
        name = self.app.cfg.mic_device or default_input_name()
        set_msg(self.bt_note, "این میکروفون بلوتوثی است؛ برای حفظ کیفیت صدای هدست، فقط هنگام "
                              "دیکته باز می‌شود." if is_bluetooth(name) else "", "Warning")
        err = self.app.recorder.error
        set_msg(self.mic_msg, "میکروفون باز نشد؛ اتصالش را بررسی کنید." if err else "", "Danger")

    # ----- text -----
    def _page_text(self):
        page = self._page("متن و املا", "نوشتن متن فقط شکل نوشتاری را درست می‌کند؛ کلمات همان‌هایی "
                                        "است که گفته‌اید.")
        cfg = self.app.cfg
        card = Card("اعداد")
        seg = SegmentedControl([("persian", "فارسی ۱۲۳"), ("latin", "انگلیسی 123"),
                                ("keep", "بدون تغییر")], cfg.digits)
        seg.changed.connect(lambda v: self.app.update_config(digits=v))
        card.add(seg)
        page.col.addWidget(card)

        card = Card("روش نوشتن متن")
        seg = SegmentedControl([("clipboard", "چسباندن"), ("type", "تایپ حرف‌به‌حرف")],
                               cfg.inject_method)
        seg.changed.connect(lambda v: self.app.update_config(inject_method=v))
        card.add(seg)
        card.add(label("«چسباندن» سریع است و در همه‌جا کار می‌کند و محتوای قبلی کلیپ‌بورد را هم "
                       "برمی‌گرداند. «تایپ حرف‌به‌حرف» برای برنامه‌هایی است که چسباندن را قبول "
                       "نمی‌کنند.", "CardText", wrap=True))
        card.separator()
        card.add(self._switch_row("فاصله بعد از متن", "تا دیکته‌های پشت سر هم به هم نچسبند.",
                                  "trailing_space"))
        page.col.addWidget(card)

        card = Card("جایگزینی کلمات", "اگر کلمه‌ای همیشه به شکل دیگری نوشته می‌شود، اینجا "
                                      "املای دلخواهتان را بنویسید.")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["نوشته‌ی مدل", "جایگزین"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(190)
        for wrong, right in cfg.replacements.items():
            self._add_row(wrong, right)
        self.table.itemChanged.connect(self._save_replacements)
        card.add(self.table)
        row = QHBoxLayout()
        add = QPushButton("افزودن")
        add.setIcon(line_icon("plus", c("text")))
        add.clicked.connect(lambda: (self._add_row("", ""), self.table.editItem(
            self.table.item(self.table.rowCount() - 1, 0))))
        rm = QPushButton("حذف ردیف")
        rm.setIcon(line_icon("trash", c("danger")))
        rm.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        card.add(row)
        page.col.addWidget(card)
        page.col.addStretch(1)
        return page

    def _add_row(self, a, b):
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(a))
        self.table.setItem(r, 1, QTableWidgetItem(b))
        self.table.blockSignals(False)

    def _remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._save_replacements()

    def _save_replacements(self, *_):
        out = {}
        for r in range(self.table.rowCount()):
            a, b = self.table.item(r, 0), self.table.item(r, 1)
            if a and b and a.text().strip():
                out[a.text().strip()] = b.text().strip()
        self.app.update_config(replacements=out)

    # ----- model -----
    def _page_model(self):
        page = self._page("مدل گفتار", "مدلی که گفتار را به متن تبدیل می‌کند؛ همه‌چیز روی همین "
                                       "کامپیوتر انجام می‌شود.")
        card = Card()
        self.model_title = label("", "CardTitle")
        card.add(self.model_title)
        self.model_desc = label("", "CardText", wrap=True)
        card.add(self.model_desc)
        self.model_status = label("", "Hint", wrap=True)
        set_msg(self.model_status, "")
        card.add(self.model_status)
        page.col.addWidget(card)

        self.gpu_card = Card(modelstore.GPU_PACK_TITLE,
                             "کتابخانه‌ی cuBLAS از NVIDIA که تبدیل را روی کارت گرافیک چند برابر سریع‌تر "
                             "می‌کند. جداگانه دانلود می‌شود، چون متن‌باز نیست و فقط به کار کامپیوترهای "
                             "دارای کارت گرافیک NVIDIA می‌آید.")
        self.gpu_status = label("", "Hint", wrap=True)
        self.gpu_card.add(self.gpu_status)
        row = QHBoxLayout()
        self.gpu_btn = QPushButton("دانلود شتاب‌دهنده")
        self.gpu_btn.setObjectName("Primary")
        self.gpu_btn.setIcon(line_icon("download", "#ffffff"))
        self.gpu_btn.clicked.connect(lambda: self.app.open_wizard("model"))
        row.addWidget(self.gpu_btn)
        row.addStretch(1)
        self.gpu_card.add(row)
        page.col.addWidget(self.gpu_card)

        card = Card("مدل‌های نصب‌شده")
        self.models_box = QVBoxLayout()
        card.add(self.models_box)
        self.model_group = QButtonGroup(self)
        self.model_group.idClicked.connect(self._model_clicked)
        row = QHBoxLayout()
        self.download_btn = QPushButton("دانلود مدل پیشنهادی")
        self.download_btn.setObjectName("Primary")
        self.download_btn.setIcon(line_icon("download", "#ffffff"))
        self.download_btn.clicked.connect(lambda: self.app.open_wizard("model"))
        imp = QPushButton("افزودن از فایل zip…")
        imp.setIcon(line_icon("plus", c("text")))
        imp.clicked.connect(self._import_zip)
        folder = QPushButton("افزودن از پوشه…")
        folder.setIcon(line_icon("folder", c("text")))
        folder.clicked.connect(self._import_folder)
        row.addWidget(self.download_btn)
        row.addWidget(imp)
        row.addWidget(folder)
        row.addStretch(1)
        card.add(row)
        self.import_msg = label("", "Hint", wrap=True)
        set_msg(self.import_msg, "")
        card.add(self.import_msg)
        open_dir = QPushButton("باز کردن پوشه‌ی مدل‌ها")
        open_dir.setObjectName("Link")
        open_dir.clicked.connect(lambda: os.startfile(MODELS_DIR))
        row2 = QHBoxLayout()
        row2.addWidget(open_dir)
        row2.addStretch(1)
        card.add(row2)
        page.col.addWidget(card)
        page.col.addStretch(1)
        return page

    def _refresh_model(self):
        st = self.app.engine_status()
        info = modelstore.catalog_entry(st["model"])
        self.model_title.setText(info.title if info else st["model"])
        self.model_desc.setText(info.description if info else "")
        colors = {"ready": "Success", "loading": "Hint", "error": "Danger", "nomodel": "Warning"}
        set_msg(self.model_status, st["text"], colors.get(st["state"], "Hint"))

        while self.models_box.count():
            w = self.models_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for b in self.model_group.buttons():
            self.model_group.removeButton(b)
        self._model_ids = modelstore.installed_models()
        for i, mid in enumerate(self._model_ids):
            entry = modelstore.catalog_entry(mid)
            rb = QRadioButton(entry.title if entry else mid)
            rb.setChecked(mid == st["model"])
            self.model_group.addButton(rb, i)
            self.models_box.addWidget(rb)
        if not self._model_ids:
            self.models_box.addWidget(label("هنوز مدلی نصب نشده است.", "Warning"))
        self.download_btn.setVisible(not modelstore.is_installed(modelstore.DEFAULT_MODEL))

        gpu = sysinfo.nvidia_gpu()
        installed = modelstore.gpu_pack_installed()
        self.gpu_card.setVisible(gpu is not None)
        self.gpu_btn.setVisible(gpu is not None and not installed)
        if installed:
            set_msg(self.gpu_status, "نصب شده است.", "Success")
        else:
            set_msg(self.gpu_status, "نصب نشده؛ فعلاً تبدیل روی پردازنده و کندتر انجام می‌شود.", "Warning")

    def _model_clicked(self, i):
        mid = self._model_ids[i]
        if mid != self.app.cfg.model:
            self.app.switch_model(mid)

    def _import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل مدل یا شتاب‌دهنده", "",
                                              "فایل zip (*.zip *.whl)")
        if path:
            self._run_import(path)

    def _import_folder(self):
        path = QFileDialog.getExistingDirectory(self, "انتخاب پوشه‌ی مدل")
        if path:
            self._run_import(path)

    def _run_import(self, path):
        set_msg(self.import_msg, "در حال کپی مدل… (ممکن است یکی دو دقیقه طول بکشد)")

        def work():
            try:
                kind, model_id = modelstore.import_file(path)
                self.import_finished.emit(model_id or "gpu", None)
            except Exception as e:
                self.import_finished.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _import_finished(self, model_id, error):
        done = "شتاب‌دهنده نصب شد." if model_id == "gpu" else "مدل اضافه شد."
        set_msg(self.import_msg, error or done, "Danger" if error else "Success")
        if model_id == "gpu":
            self.app.switch_model(self.app.cfg.model)  # reload so the GPU is used
        elif model_id:
            self.app.switch_model(model_id)
        self._refresh_model()

    # ----- about -----
    def _page_about(self):
        page = self._page("درباره‌ی برنامه", APP_DESCRIPTION)
        hero = Card()
        row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(svg_pixmap(LOGO_SVG, 88, self.devicePixelRatioF()))
        row.addWidget(logo)
        texts = QVBoxLayout()
        texts.addWidget(label(rtl(APP_NAME), "PageTitle"))
        texts.addWidget(label(APP_TAGLINE, "PageSubtitle"))
        texts.addWidget(label(f"نسخه‌ی {fa(APP_VERSION)}", "Faint"))
        row.addLayout(texts, 1)
        hero.add(row)
        page.col.addWidget(hero)

        card = Card("معرفی")
        for text in ABOUT_TEXT:
            card.add(label(rtl(text), "CardText", wrap=True))
        page.col.addWidget(card)

        card = Card("طراح و توسعه‌دهنده")
        card.add(label(AUTHOR, "PageTitle"))
        links = QHBoxLayout()
        for icon, text, url in (("globe", WEBSITE_LABEL, WEBSITE), ("github", GITHUB_LABEL, GITHUB)):
            b = QPushButton(text)
            b.setIcon(line_icon(icon, c("primary")))
            b.setCursor(Qt.PointingHandCursor)
            b.setLayoutDirection(Qt.LeftToRight)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            links.addWidget(b)
        links.addStretch(1)
        card.add(links)
        page.col.addWidget(card)

        card = Card("مجوزها")
        card.add(label(f"این برنامه متن‌باز است و با مجوز {ltr(LICENSE_NAME)} منتشر شده است. "
                       "اجزایی که در آن به کار رفته‌اند:", "CardText", wrap=True))
        for part, who, lic in CREDITS:
            card.add(label(f"•  {part}: {who}  ·  مجوز {ltr(lic)}", "CardText", wrap=True))
        b = QPushButton("متن کامل مجوزها")
        b.setObjectName("Link")
        b.clicked.connect(lambda: NOTICE_PATH.exists() and os.startfile(NOTICE_PATH))
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        card.add(row)
        page.col.addWidget(card)
        page.col.addStretch(1)
        return page

    def restyle(self):
        """Re-apply icons and colors after a theme change."""
        for key, icon, _ in PAGES:
            self.nav_buttons[key].setIcon(nav_icon(icon))
        self.update()
