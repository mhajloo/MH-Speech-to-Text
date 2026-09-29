"""First-run setup: welcome, system check, speech model, microphone test, done."""
import threading

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import autostart, devices, modelstore
from ..audio import default_input_name, input_devices
from ..branding import APP_DESCRIPTION, APP_NAME
from . import theme
from .icons import BRAND_A, BRAND_B, LOGO_SVG, line_icon, logo_icon, svg_pixmap
from .theme import c, fa
from .widgets import Card, KeyCaps, LevelMeter, combo_text, device_label, label, set_msg

STEPS = ["خوش آمدید", "بررسی سیستم", "اجزای گفتار", "میکروفون", "آماده است"]
LOW_MEMORY_MB = 3000  # the model and its buffers take ≈2.5 GB of graphics memory


class _BrandPanel(QWidget):
    """The gradient side panel with the logo and the list of steps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(230)
        self.step = 0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor(BRAND_A))
        g.setColorAt(1, QColor(BRAND_B))
        p.fillRect(self.rect(), g)
        # soft decorative circles
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(QRectF(-60, self.height() - 170, 220, 220))
        p.drawEllipse(QRectF(self.width() - 90, -40, 160, 160))
        pm = svg_pixmap(LOGO_SVG, 64, self.devicePixelRatioF())
        p.drawPixmap(self.width() - 64 - 26, 34, pm)
        p.setPen(QColor("#ffffff"))
        p.setLayoutDirection(Qt.RightToLeft)
        p.setFont(theme.font(12.5, 700))
        p.drawText(QRectF(16, 108, self.width() - 42, 30), Qt.AlignRight | Qt.AlignVCenter, APP_NAME)
        y = 170
        for i, s in enumerate(STEPS):
            done, cur = i < self.step, i == self.step
            cx = self.width() - 40
            p.setPen(QPen(QColor(255, 255, 255, 230 if cur or done else 120), 2))
            p.setBrush(QColor("#ffffff") if done or cur else Qt.NoBrush)
            p.drawEllipse(QRectF(cx - 11, y - 11, 22, 22))
            if done:  # a drawn check mark: the font has no ✓ glyph
                p.setPen(QPen(QColor(BRAND_A), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline([QPointF(cx - 5, y), QPointF(cx - 1.5, y + 4), QPointF(cx + 5.5, y - 4)])
            else:
                p.setPen(QColor(BRAND_A) if cur else QColor(255, 255, 255, 170))
                p.setFont(theme.font(9, 700))
                p.drawText(QRectF(cx - 11, y - 11, 22, 22), Qt.AlignCenter, fa(i + 1))
            p.setPen(QColor(255, 255, 255, 255 if cur else 190))
            p.setFont(theme.font(10.5, 700 if cur else 400))
            p.drawText(QRectF(16, y - 14, cx - 26 - 16, 28), Qt.AlignRight | Qt.AlignVCenter, s)
            y += 46


class SetupWizard(QDialog):
    progress = Signal(float, float, float, str)
    download_done = Signal(object)
    import_done = Signal(object, object)

    def __init__(self, app, only_model=False):
        super().__init__()
        self.app = app
        self.only_model = only_model
        self.setWindowTitle(f"راه‌اندازی {APP_NAME}")
        self.setWindowIcon(logo_icon())
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(780, 540)
        self._cancel = threading.Event()
        self._downloading = False
        # finding the graphics cards loads Vulkan (about a second): done by the system page
        threading.Thread(target=devices.cards, daemon=True).start()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = _BrandPanel()
        root.addWidget(self.panel)
        right = QVBoxLayout()
        right.setContentsMargins(32, 30, 32, 22)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.back = QPushButton("قبلی")
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next = QPushButton("بعدی")
        self.next.setObjectName("Primary")
        self.next.setMinimumWidth(130)
        self.next.clicked.connect(self._next_clicked)
        nav.addWidget(self.next)
        nav.addWidget(self.back)
        nav.addStretch(1)
        right.addLayout(nav)
        root.addLayout(right, 1)

        for build in (self._welcome, self._system, self._model, self._mic, self._finish):
            self.stack.addWidget(build())
        self.progress.connect(self._on_progress)
        self.download_done.connect(self._on_download_done)
        self.import_done.connect(self._on_import_done)
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(40)
        self._meter_timer.timeout.connect(lambda: self.meter.set_level(self.app.recorder.level))
        self._go(2 if only_model else 0)

    # ----- pages -----
    def _col(self, title, text=None):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        col.addWidget(label(title, "PageTitle"))
        if text:
            col.addWidget(label(text, "PageSubtitle", wrap=True))
        col.addSpacing(6)
        w.col = col
        return w

    def _welcome(self):
        w = self._col(f"به {APP_NAME} خوش آمدید", APP_DESCRIPTION)
        card = Card()
        for icon, title, text in (
                ("keyboard", "در هر برنامه‌ای", "کلید میان‌بر را نگه دارید، صحبت کنید و رها کنید؛ متن "
                                                "همان‌جایی نوشته می‌شود که مکان‌نما هست."),
                ("shield", "آفلاین و خصوصی", "صدای شما از کامپیوترتان خارج نمی‌شود."),
                ("bolt", "دقیق و سریع", "با مدل فارسی دقیق، روی کارت گرافیک NVIDIA، AMD یا Intel و "
                                        "بدون آن روی پردازنده.")):
            row = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(line_icon(icon, c("primary")).pixmap(26, 26))
            ic.setAlignment(Qt.AlignTop)
            row.addWidget(ic)
            texts = QVBoxLayout()
            texts.setSpacing(0)
            texts.addWidget(label(title, "CardTitle"))
            texts.addWidget(label(text, "CardText", wrap=True))
            row.addLayout(texts, 1)
            card.add(row)
        w.col.addWidget(card)
        w.col.addStretch(1)
        return w

    def _system(self):
        w = self._col("بررسی سیستم", "تبدیل گفتار روی کارت گرافیک سریع‌تر است؛ بدون آن، برنامه روی "
                                     "پردازنده کار می‌کند.")
        self.sys_card = Card()
        w.col.addWidget(self.sys_card)
        w.col.addStretch(1)
        return w

    def _fill_system(self):
        card = self.sys_card
        while card.body.count():
            item = card.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        gpu = devices.best_card()
        if gpu:
            memory = f"حافظه‌ی گرافیک: {fa(f'{gpu.memory_mb / 1024:.1f}'.removesuffix('.0'))} گیگابایت"
            if gpu.memory_mb < LOW_MEMORY_MB:
                card.add(self._status_row(
                    "info", "warning", f"کارت گرافیک پیدا شد: {gpu.name}",
                    f"{memory}؛ شاید برای مدل فارسی دقیق کافی نباشد. در این صورت برنامه خودکار روی "
                    "پردازنده کار می‌کند."))
            else:
                card.add(self._status_row("check", "success", f"کارت گرافیک پیدا شد: {gpu.name}", memory))
            return
        text = ("برنامه روی پردازنده کار می‌کند. این کار کندتر است: بعد از رها کردن کلید، چند ثانیه طول "
                "می‌کشد تا متن نوشته شود.")
        integrated = next((g for g in devices.cards() if g.integrated), None)
        if integrated:
            text += (f" کارت گرافیک مجتمع ({integrated.name}) را هم می‌توانید بعداً در تنظیمات امتحان "
                     "کنید؛ در سیستم‌های جدید ممکن است سریع‌تر از پردازنده باشد.")
        card.add(self._status_row("info", "warning", "کارت گرافیک جداگانه پیدا نشد", text))

    def _status_row(self, icon, color, title, text):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        ic = QLabel()
        ic.setPixmap(line_icon(icon, c(color)).pixmap(28, 28))
        ic.setAlignment(Qt.AlignTop)
        lay.addWidget(ic)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "CardTitle"))
        texts.addWidget(label(text, "CardText", wrap=True))
        lay.addLayout(texts, 1)
        return row

    def _model(self):
        w = self._col("اجزای گفتار", "این اجزا یک بار دانلود می‌شوند و بعد از آن برنامه کاملاً آفلاین کار "
                                     "می‌کند.")
        self.model_card = Card()  # which model depends on the graphics card: see _refresh_model_page
        self.model_title = self.model_card.add(label("", "CardTitle"))
        self.model_text = self.model_card.add(label("", "CardText", wrap=True))
        self.model_status = self.model_card.add(label("", "Success"))
        w.col.addWidget(self.model_card)
        gpu_size = modelstore.GPU_SOURCES[0][2]
        self.gpu_card = Card(modelstore.GPU_PACK_TITLE, "برای تبدیل سریع روی کارت گرافیک NVIDIA (کتابخانه‌ی "
                                                        f"cuBLAS از NVIDIA) · حجم: {modelstore.size_text(gpu_size)}")
        self.gpu_status = label("", "Success")
        self.gpu_card.add(self.gpu_status)
        w.col.addWidget(self.gpu_card)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        w.col.addWidget(self.bar)
        self.bar_text = label("", "Hint", wrap=True)
        set_msg(self.bar_text, "")
        w.col.addWidget(self.bar_text)
        row = QHBoxLayout()
        self.dl_btn = QPushButton("دانلود")
        self.dl_btn.setObjectName("Primary")
        self.dl_btn.setIcon(line_icon("download", "#ffffff"))
        self.dl_btn.clicked.connect(self._download)
        imp = QPushButton("از فایل…")
        imp.clicked.connect(self._import)
        row.addWidget(self.dl_btn)
        row.addWidget(imp)
        row.addStretch(1)
        w.col.addLayout(row)
        w.col.addWidget(label("اگر اینترنت کند است، فایل این اجزا (zip یا bin) را از کسی که برنامه را نصب "
                              "کرده بگیرید و از همین‌جا اضافه کنید.", "Hint", wrap=True))
        w.col.addStretch(1)
        return w

    def _targets(self):
        return devices.targets(self.app.cfg.device, self.app.cfg.model)

    def _model_ok(self):
        """Some installed model can run, even if not the best one for this PC."""
        return bool(self._targets())

    def _refresh_model_page(self):
        model_id, pack = devices.requirements(self.app.cfg.device)
        info = modelstore.catalog_entry(model_id)
        need = devices.needs(self.app.cfg.device)
        self.model_title.setText(info.title)
        self.model_text.setText(f"مدل تبدیل گفتار فارسی · حجم: {modelstore.size_text(info.size)}")
        set_msg(self.model_status, "" if need["model"] else "نصب شده و آماده است.", "Success")
        self.gpu_card.setVisible(pack)
        set_msg(self.gpu_status, "" if need["gpu_pack"] else "نصب شده و آماده است.", "Success")
        missing = bool(need["model"] or need["gpu_pack"])
        self.bar.setVisible(self._downloading)
        self.dl_btn.setVisible(missing or self._downloading)
        self.dl_btn.setText("لغو دانلود" if self._downloading else "دانلود")
        if (not self._downloading and missing and self._model_ok() and not self.bar_text.text()
                and all(t.device == "cpu" for t in self._targets())):
            set_msg(self.bar_text, "تا این اجزا دانلود نشوند، تبدیل گفتار روی پردازنده و کندتر انجام می‌شود.",
                    "Warning")
        self._update_nav()

    def _mic(self):
        w = self._col("آزمایش میکروفون", "یک جمله بگویید؛ نوار زیر باید با صدای شما حرکت کند.")
        card = Card()
        self.dev = QComboBox()
        default = default_input_name()
        self.dev.addItem(f"پیش‌فرض ویندوز: {device_label(default) if default else 'پیدا نشد'}", None)
        for n in input_devices():
            self.dev.addItem(device_label(n), n)
        idx = self.dev.findData(self.app.cfg.mic_device) if self.app.cfg.mic_device else 0
        self.dev.setCurrentIndex(max(idx, 0))
        self.dev.currentIndexChanged.connect(
            lambda _: self.app.update_config(mic_device=self.dev.currentData()))
        card.add(self.dev)
        self.meter = LevelMeter()
        card.add(self.meter)
        w.col.addWidget(card)
        w.col.addWidget(label("اگر نوار حرکت نمی‌کند، میکروفون دیگری انتخاب کنید یا دسترسی برنامه‌ها "
                              "به میکروفون را در تنظیمات حریم خصوصی ویندوز باز کنید.", "Hint", wrap=True))
        w.col.addStretch(1)
        return w

    def _finish(self):
        w = self._col("همه‌چیز آماده است!", "از این به بعد برنامه در کنار ساعت ویندوز منتظر شماست.")
        card = Card("نحوه‌ی استفاده")
        self.finish_caps = KeyCaps(self.app.cfg.hotkey)
        card.add(self.finish_caps)
        self.finish_text = label("", "CardText", wrap=True)
        card.add(self.finish_text)
        w.col.addWidget(card)
        self.auto = QCheckBox("اجرا با شروع ویندوز")
        self.auto.setChecked(True)
        w.col.addWidget(self.auto)
        w.col.addWidget(label("کلید و بقیه‌ی تنظیمات را هر وقت خواستید از منوی آیکون برنامه، بخش "
                              "«تنظیمات» عوض کنید.", "Hint", wrap=True))
        w.col.addStretch(1)
        return w

    # ----- navigation -----
    def _go(self, i):
        if i < 0 or i >= self.stack.count():
            return
        self.stack.setCurrentIndex(i)
        self.panel.step = i
        self.panel.update()
        if i == 1:
            self._fill_system()
        if i == 2:
            self._refresh_model_page()
        mic = i == 3
        self.app.recorder.monitor(mic)
        (self._meter_timer.start if mic else self._meter_timer.stop)()
        if i == 4:
            self.finish_caps.set_combo(self.app.cfg.hotkey)
            key = combo_text(self.app.cfg.hotkey)
            self.finish_text.setText(
                f"مکان‌نما را در هر جایی که می‌خواهید بنویسید بگذارید، {key} را نگه دارید، صحبت "
                "کنید و رها کنید. برای لغو، وسط ضبط Esc بزنید.")
        self._update_nav()

    def _update_nav(self):
        i = self.stack.currentIndex()
        last = i == self.stack.count() - 1 or (self.only_model and i == 2)
        self.back.setVisible(0 < i and not self.only_model)
        self.next.setText({0: "شروع", }.get(i, "پایان" if last else "بعدی"))
        blocked = i == 2 and not self._model_ok()
        self.next.setEnabled(not blocked and not self._downloading)

    def _next_clicked(self):
        i = self.stack.currentIndex()
        if i == self.stack.count() - 1 or (self.only_model and i == 2):
            self._complete()
        else:
            self._go(i + 1)

    def _complete(self):
        if not modelstore.is_installed(self.app.cfg.model) and modelstore.is_installed(modelstore.DEFAULT_MODEL):
            self.app.cfg.model = modelstore.DEFAULT_MODEL
        if not self.only_model:
            self.app.cfg.first_run_done = True
            try:
                autostart.set_enabled(self.auto.isChecked())
            except OSError:
                pass
        self.app.save_config()
        self.accept()

    def reject(self):
        if self._downloading:
            self._cancel.set()
        self.app.recorder.monitor(False)
        super().reject()

    def accept(self):
        self.app.recorder.monitor(False)
        super().accept()

    # ----- download / import -----
    def _download(self):
        if self._downloading:
            self._cancel.set()
            return
        need = devices.needs(self.app.cfg.device)
        model = modelstore.catalog_entry(need["model"]) if need["model"] else None
        self._cancel.clear()
        self._downloading = True
        self.bar.setValue(0)
        set_msg(self.bar_text, "در حال اتصال…")
        self._refresh_model_page()

        def work():
            try:
                if need["gpu_pack"]:
                    modelstore.download_gpu_pack(progress=lambda d, t, v, src: self.progress.emit(
                        d, t, v, f"{modelstore.GPU_PACK_TITLE} · {src}"), cancel=self._cancel)
                if model:
                    modelstore.download(model, None, lambda d, t, v, src: self.progress.emit(
                        d, t, v, f"مدل گفتار · {src}"), self._cancel)
                self.download_done.emit(None)
            except modelstore.Cancelled:
                self.download_done.emit("cancelled")
            except Exception as e:
                self.download_done.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, done, total, speed, what):
        self.bar.setValue(int(done / total * 1000))
        if speed <= 0 and done >= total:
            set_msg(self.bar_text, f"در حال بررسی و آماده‌سازی…  ·  {what}")
            return
        left = (total - done) / speed if speed > 0 else 0
        eta = f"حدود {fa(max(1, round(left / 60)))} دقیقه مانده" if left > 60 else "کمتر از یک دقیقه مانده"
        set_msg(self.bar_text, f"{fa(round(done / 1e6))} از {fa(round(total / 1e6))} مگابایت  ·  "
                               f"{fa(f'{speed / 1e6:.1f}')} مگابایت در ثانیه  ·  {eta}  ·  {what}")

    def _on_download_done(self, error):
        self._downloading = False
        if error == "cancelled":
            set_msg(self.bar_text, "دانلود متوقف شد؛ دفعه‌ی بعد از همین‌جا ادامه پیدا می‌کند.", "Warning")
        elif error:
            set_msg(self.bar_text, f"دانلود انجام نشد: {error}. اتصال اینترنت را بررسی کنید و دوباره "
                                   "امتحان کنید.", "Danger")
        else:
            if self._model_ok() and not modelstore.is_installed(self.app.cfg.model):
                self.app.cfg.model = modelstore.DEFAULT_MODEL
            set_msg(self.bar_text, "")
        self._refresh_model_page()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل", "", "فایل zip یا مدل (*.zip *.whl *.bin)")
        if not path:
            return
        set_msg(self.bar_text, "در حال کپی و بررسی فایل…")

        def work():
            try:
                kind, model_id = modelstore.import_file(path)
                self.import_done.emit(model_id, None)
            except Exception as e:
                self.import_done.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_import_done(self, model_id, error):
        if model_id:
            self.app.cfg.model = model_id
        set_msg(self.bar_text, error or "", "Danger")
        self._refresh_model_page()
