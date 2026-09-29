"""MH-Speech to Text: application start-up and the dictation controller."""
import ctypes
import json
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import modelstore
from .branding import APP_ID, APP_NAME
from .config import Config
from .cuda import add_cuda_dlls
from .paths import FROZEN, HISTORY_PATH, LOG_PATH, ensure_dirs

SERVER_NAME = "MH-Speech-to-Text-instance"


class App(QObject):
    engine_status_changed = Signal()
    devices_changed = Signal()
    _engine_status = Signal(str)  # emitted from worker threads

    def __init__(self, qapp, cfg: Config):
        super().__init__()
        from .audio import Recorder
        from .sounds import Sounds
        from .ui.overlay import RecordingBar
        from .ui.tray import Tray
        self.qapp, self.cfg = qapp, cfg
        self.engine = None
        self.engine_state = "loading"
        self.hotkey = None
        self.session = None
        self.last_text = ""
        self._lock = threading.Lock()
        self._stop_timer = None
        self._settings = self._history = None

        self.recorder = Recorder(cfg.mic_device, cfg.preroll_ms, cfg.keep_mic_open,
                                 on_devices_changed=self.devices_changed.emit)
        self.sounds = Sounds(cfg.sounds)
        self.overlay = RecordingBar(lambda: self.recorder.level)
        self.tray = Tray(cfg.hotkey, cfg.record_mode == "toggle")
        self.tray.settings_requested.connect(lambda: self.show_settings())
        self.tray.history_requested.connect(self.show_history)
        self.tray.about_requested.connect(lambda: self.show_settings("about"))
        self.tray.copy_last_requested.connect(self.copy_last)
        self.tray.quit_requested.connect(self.quit)
        self._engine_status.connect(self._on_engine_status)

    # ---------------- start-up ----------------
    def start(self):
        from .hotkey import HoldHotkey
        from .textfix import preload
        self.tray.show()
        self.hotkey = HoldHotkey(self.cfg.hotkey, self.on_press, self.on_release, self.on_cancel,
                                 self.cfg.cancel_key)
        self.hotkey.start()
        threading.Thread(target=preload, daemon=True).start()
        self.load_engine()

    def load_engine(self):
        from .devices import any_model_installed
        from .engine import Engine
        add_cuda_dlls()  # again: the GPU pack may have been downloaded since start-up
        if not any_model_installed(self.cfg.model):
            self._engine_status.emit("nomodel")
            return
        self._engine_status.emit("loading")
        self.engine = Engine(self.cfg, on_status=self._engine_status.emit)

    def _on_engine_status(self, state):
        self.engine_state = state
        if self.session is None:
            self.tray.set_state(state)
        self.engine_status_changed.emit()
        if state == "error":
            self.tray.notify("مدل گفتار بارگذاری نشد", "برای جزئیات، تنظیمات ← مدل گفتار را ببینید.")

    def engine_status(self) -> dict:
        state = self.engine_state
        target = self.engine.target if self.engine is not None and state == "ready" else None
        if state == "ready":
            where = target.label if target else "پردازنده"
            text = f"فعال و آماده؛ اجرا روی {where}"
            if target and target.device == "cpu":
                text += " (کندتر از کارت گرافیک)"
                gpu = next((t for t, _ in self.engine.failed if t.card), None)
                if gpu:  # the error itself is in the log
                    text += f". {gpu.label} اجرا نشد."
        elif state == "loading":
            text = "در حال بارگذاری مدل… (چند ثانیه)"
        elif state == "nomodel":
            text = "این مدل نصب نیست؛ آن را دانلود کنید یا از فایل اضافه کنید."
        else:
            text = f"بارگذاری نشد: {self.engine.error if self.engine else ''}"
        return {"state": state, "model": target.model if target else self.cfg.model, "text": text}

    def set_device(self, device):
        """Where to run speech recognition: "auto", "cpu" or "gpu:<card name>"."""
        if device != self.cfg.device:
            self.cfg.device = device
            self.switch_model(self.cfg.model)  # saves the setting and reloads the engine

    def switch_model(self, model_id):
        self.cfg.model = model_id
        self.save_config()
        old, self.engine = self.engine, None
        self._engine_status.emit("loading")

        def work():  # free the old model's GPU memory before loading the next one
            if old:
                old.release()
            self.load_engine()
        threading.Thread(target=work, daemon=True).start()

    # ---------------- settings ----------------
    def save_config(self):
        self.cfg.save()

    def update_config(self, **changes):
        for k, v in changes.items():
            setattr(self.cfg, k, v)
        self.save_config()
        if "hotkey" in changes and self.hotkey:
            self.hotkey.set_combo(self.cfg.hotkey)
        if {"hotkey", "record_mode"} & changes.keys():
            self.tray.configure(self.cfg.hotkey, self.cfg.record_mode == "toggle")
        if {"mic_device", "keep_mic_open"} & changes.keys():
            self.recorder.configure(self.cfg.mic_device, self.cfg.keep_mic_open)
        if "sounds" in changes:
            self.sounds.enabled = self.cfg.sounds
        if "theme" in changes:
            self.apply_theme()

    def apply_theme(self):
        from .ui import theme
        theme.apply(self.qapp, self.cfg.theme)
        self.tray.restyle()
        for w in (self._settings, self._history):
            if w is not None:
                w.restyle() if hasattr(w, "restyle") else w.update()

    # ---------------- dictation (called on hotkey threads) ----------------
    def on_press(self):
        with self._lock:
            active = self.session is not None
        if active:
            if self.cfg.record_mode == "toggle":
                self._stop_recording()
            return
        self._start_recording()

    def on_release(self):
        if self.cfg.record_mode == "hold":
            self._stop_recording()

    def _start_recording(self):
        from .audio import MicError, Session
        from .ui.widgets import combo_text
        problem = None
        if self.engine is None or self.engine_state == "nomodel":
            problem = ("warning", "مدل گفتار نصب نیست", "از منوی برنامه: تنظیمات ← مدل گفتار")
        elif self.engine.error:
            problem = ("error", "مدل گفتار بارگذاری نشد", "تنظیمات ← مدل گفتار را ببینید")
        elif not self.engine.ready.is_set():
            problem = ("info", "مدل در حال آماده‌سازی است", "چند ثانیه دیگر دوباره امتحان کنید")
        if problem:
            self.sounds.play("error")
            self.overlay.message(*problem)
            return
        try:
            s = Session(self.recorder, self.engine, self.cfg.tail_ms)
        except MicError:
            self.sounds.play("error")
            self.overlay.message("error", "میکروفون در دسترس نیست", "اتصال میکروفون را بررسی کنید")
            return
        with self._lock:
            self.session = s
        toggle = self.cfg.record_mode == "toggle"
        if toggle:
            self.hotkey.cancel_armed = True
            self._stop_timer = threading.Timer(self.cfg.max_record_s, self._stop_recording)
            self._stop_timer.daemon = True
            self._stop_timer.start()
        self.sounds.play("start")
        if self.cfg.show_overlay:
            # one short hint: the bar has room for about 20 characters next to the clock
            if toggle:
                hint = f"پایان با {combo_text(self.cfg.hotkey)}"
            else:
                hint = f"{combo_text(self.cfg.cancel_key)} برای لغو" if self.cfg.cancel_key else ""
            self.overlay.recording(hint)
        self.tray.state_request.emit("recording")

    def _end_session(self):
        with self._lock:
            s, self.session = self.session, None
        if self.hotkey:
            self.hotkey.cancel_armed = False
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None
        return s

    def _stop_recording(self):
        s = self._end_session()
        if not s:
            return
        if self.cfg.record_mode == "hold" and s.held_ms() < self.cfg.min_hold_ms:
            s.cancel()  # a tap, not a dictation
            self.overlay.hide_bar()
            self.tray.state_request.emit(self.engine_state)
            return
        self.sounds.play("stop")
        if self.cfg.show_overlay:
            self.overlay.busy()
        self.tray.state_request.emit("busy")
        threading.Thread(target=self._finish, args=(s,), name="finish", daemon=True).start()

    def on_cancel(self):
        s = self._end_session()
        if s:
            s.cancel()
            self.sounds.play("error")
            self.overlay.message("info", "دیکته لغو شد")
            self.tray.state_request.emit(self.engine_state)

    def _finish(self, s):
        import numpy as np
        from .inject import insert
        from .textfix import fix
        released = time.perf_counter()
        try:
            raw = s.finish()
            text = fix(raw, self.cfg.digits, self.cfg.replacements)
            wait = time.perf_counter() - released
            if not text:
                if s.d.n and not np.any(s.d.samples(0, s.d.n)):
                    self.overlay.message("warning", "صدایی از میکروفون نرسید",
                                         "حریم خصوصی ویندوز ← میکروفون را بررسی کنید")
                else:
                    self.overlay.message("info", "صدایی شنیده نشد")
                return
            result = insert(text + (" " if self.cfg.trailing_space else ""), self.cfg.inject_method)
            self.last_text = text
            if result == "clipboard":
                self.overlay.message("warning", "متن در کلیپ‌بورد است",
                                     "این برنامه اجازه‌ی تایپ نمی‌دهد؛ Ctrl+V بزنید")
            elif self.cfg.show_overlay:
                self.overlay.done(len(text.split()))
            if self.cfg.save_history:
                self._log_history(s, raw, text, wait)
            print(f"[dictation] {s.held_ms() / 1000:.1f}s, {wait:.2f}s after release, "
                  f"{len(s.futures)} piece(s)", flush=True)
        except Exception:
            traceback.print_exc()
            self.sounds.play("error")
            self.overlay.message("error", "تبدیل متن انجام نشد", "جزئیات در فایل گزارش برنامه")
        finally:
            self.tray.state_request.emit(self.engine_state)

    def _log_history(self, s, raw, text, wait):
        rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "held_s": round(s.held_ms() / 1000, 1),
               "wait_s": round(wait, 2), "pieces": len(s.futures), "raw": raw, "text": text}
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------------- windows ----------------
    def copy_last(self):
        from .inject import copy_to_clipboard
        if self.last_text:
            copy_to_clipboard(self.last_text)
            self.overlay.message("info", "آخرین متن کپی شد")

    def show_settings(self, page=None):
        from .ui.settings import SettingsWindow
        if self._settings is None:
            self._settings = SettingsWindow(self)
        if page:
            self._settings.show_page(page)
        self._bring_up(self._settings)

    def show_history(self):
        from .inject import copy_to_clipboard
        from .ui.history import HistoryWindow
        if self._history is None:
            self._history = HistoryWindow(copy_to_clipboard)
        self._bring_up(self._history)

    @staticmethod
    def _bring_up(w):
        w.show()
        w.setWindowState(w.windowState() & ~Qt.WindowMinimized)
        w.raise_()
        w.activateWindow()

    def open_wizard(self, page=None):
        from .ui.wizard import SetupWizard
        before, gpu_before = self.cfg.model, modelstore.gpu_pack_installed()
        models_before = set(modelstore.installed_models())
        if self.hotkey:
            self.hotkey.suspended = True
        try:
            SetupWizard(self, only_model=page == "model").exec()
        finally:
            if self.hotkey:
                self.hotkey.suspended = False
        gpu_added = modelstore.gpu_pack_installed() and not gpu_before
        models_added = set(modelstore.installed_models()) - models_before
        if self.cfg.model != before or self.engine_state == "nomodel" or gpu_added or models_added:
            self.switch_model(self.cfg.model)  # reload: new model, or now able to use the GPU
        self.engine_status_changed.emit()

    def quit(self):
        if self.hotkey:
            self.hotkey.stop()
        self.recorder.close()
        self.tray.hide()
        self.qapp.quit()


# ---------------- process start ----------------
def _setup_logging():
    if sys.stdout is None or not sys.stdout.isatty():  # no console (installed app / pythonw)
        try:
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
                LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
            f = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = f
        except OSError:
            pass
    else:
        sys.stdout.reconfigure(encoding="utf-8")


def _already_running() -> bool:
    """If another copy runs, ask it to show its settings window and report True."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(400):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return True
    return False


def _stub_unused_modules():
    """The installed build leaves out PyAV (FFmpeg, ~65 MB): faster-whisper imports
    it at start-up but only uses it to decode audio files, never for the microphone."""
    import importlib.util
    if FROZEN and importlib.util.find_spec("av") is None:
        import types
        sys.modules["av"] = types.ModuleType("av")


def main():
    ensure_dirs()
    _setup_logging()
    _stub_unused_modules()
    print(f"[app] {APP_NAME} starting {time.strftime('%Y-%m-%d %H:%M:%S')} "
          f"({'installed' if FROZEN else 'source'})", flush=True)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setLayoutDirection(Qt.RightToLeft)
    if _already_running():
        return

    from .devices import any_model_installed
    from .ui import theme
    from .ui.icons import logo_icon
    from .ui.widgets import combo_text
    from .ui.wizard import SetupWizard
    theme.load_fonts()
    cfg = Config.load()
    theme.apply(qapp, cfg.theme)
    qapp.setWindowIcon(logo_icon())
    add_cuda_dlls()

    app = App(qapp, cfg)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), app.show_settings()))

    first_run = not cfg.first_run_done or not any_model_installed(cfg.model)
    if first_run and not SetupWizard(app).exec() and not any_model_installed(cfg.model):
        app.quit()
        return
    app.start()
    if first_run or "--autostart" not in sys.argv:
        app.tray.notify(APP_NAME, f"آماده است؛ در هر برنامه‌ای {combo_text(cfg.hotkey)} را نگه دارید "
                                  "و صحبت کنید. تنظیمات از آیکون کنار ساعت.")
    hints = qapp.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _: cfg.theme == "system" and app.apply_theme())
    sys.exit(qapp.exec())
