import json
import os
from dataclasses import asdict, dataclass, field, fields

from .paths import CONFIG_PATH


@dataclass
class Config:
    # --- keys ---
    hotkey: str = "ctrl+q"            # e.g. "ctrl+q", "rctrl", "ctrl+win", "f9"
    record_mode: str = "hold"         # "hold": talk while held; "toggle": press to start, again to stop
    cancel_key: str = "esc"           # discards the current dictation
    # --- speech model ---
    model: str = "fa-amirmohseni-large-v3"  # folder name under the models dir
    device: str = "auto"              # "auto", "cpu" or "gpu:<card name>" (see devices.py)
    compute_type: str = "int8_float16"  # CTranslate2 on NVIDIA cards (the CPU always uses int8)
    beam_size: int = 5
    final_beam_size: int = 1          # beam for the piece decoded after release (0 = beam_size)
    fast_context: bool = True         # size the encoder to the audio instead of 30 s (much faster)
    vocabulary: list = field(default_factory=list)    # names/terms the model should expect
    # --- text ---
    replacements: dict = field(default_factory=dict)  # "wrong": "right", applied to output
    digits: str = "persian"           # "persian", "latin" or "keep"
    trailing_space: bool = True       # so consecutive dictations don't run together
    inject_method: str = "clipboard"  # "clipboard" (fast, any app) or "type" (unicode keystrokes)
    # --- microphone ---
    mic_device: object = None         # None = Windows default, or a device name
    keep_mic_open: bool = True        # instant start + pre-roll (off automatically for Bluetooth)
    preroll_ms: int = 400             # audio kept from just before the hotkey press
    tail_ms: int = 250                # keep recording briefly after release
    min_hold_ms: int = 300            # shorter presses are ignored
    max_record_s: int = 600           # safety stop for a forgotten toggle-mode dictation
    # --- interface ---
    sounds: bool = True
    show_overlay: bool = True
    save_history: bool = True
    theme: str = "system"             # "system", "light" or "dark"
    first_run_done: bool = False

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            return cls()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return cls()  # a broken file must not stop the app from starting
        known = {f.name for f in fields(cls)}
        if data.get("device") == "cuda":  # 1.0 saved its default; the card is now chosen by name
            data["device"] = "auto"
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)  # atomic: a crash mid-write can't corrupt the settings
