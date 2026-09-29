"""Where the app keeps its files.

From source: everything lives in the project folder, as during development.
Installed (frozen by PyInstaller): read-only assets ship with the program;
settings and history go to %APPDATA%, and the large models to %LOCALAPPDATA%.
"""
import os
import sys
from pathlib import Path

from .branding import APP_DIR_NAME

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    APP_ROOT = Path(sys.executable).resolve().parent
    ASSETS_DIR = Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "assets"
    WHISPERCPP_DIR = Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "whispercpp"
    DATA_DIR = Path(os.environ.get("APPDATA") or APP_ROOT) / APP_DIR_NAME
    MODELS_DIR = Path(os.environ.get("LOCALAPPDATA") or APP_ROOT) / APP_DIR_NAME / "models"
else:
    APP_ROOT = Path(__file__).resolve().parent.parent
    ASSETS_DIR = APP_ROOT / "assets"
    WHISPERCPP_DIR = APP_ROOT / "build_cache" / "whispercpp" / "bin"  # tools/build_whispercpp.py
    DATA_DIR = APP_ROOT
    MODELS_DIR = APP_ROOT / "models"
GPU_DIR = MODELS_DIR.parent / "gpu"  # the downloaded NVIDIA cuBLAS DLLs

CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"
LOG_PATH = DATA_DIR / ("app.log" if FROZEN else "dictation.log")
FONTS_DIR = ASSETS_DIR / "fonts"
ICONS_DIR = ASSETS_DIR / "icons"
ZWNJ_WORDS_PATH = ASSETS_DIR / "data" / "zwnj_words.txt"
NOTICE_PATH = ASSETS_DIR / "NOTICE.txt"


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
