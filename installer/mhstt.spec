# PyInstaller build of MH-Speech to Text (one folder, no console).
# Build:  .venv/Scripts/pyinstaller installer/mhstt.spec --noconfirm --distpath build/dist --workpath build/work
import site
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
SITE = Path(next(p for p in site.getsitepackages() if p.endswith("site-packages")))

# NVIDIA's cuBLAS is NOT bundled: it is proprietary and only useful with an NVIDIA GPU,
# so the app downloads it on first run (dictation/modelstore.py, "GPU pack")
binaries = collect_dynamic_libs("ctranslate2")
# onnxruntime imports these C++ runtime DLLs, which otherwise only exist inside the
# PySide6 folder; at the top level they are found on a PC without the VC++ redistributable
binaries += [(str(SITE / "PySide6" / n), ".") for n in ("MSVCP140_1.dll", "MSVCP140_2.dll")]
# whisper.cpp with Vulkan for AMD, Intel and NVIDIA cards (tools/build_whispercpp.py), in its
# own folder. ggml-vulkan.dll uses the Vulkan loader that graphics drivers install in System32.
WHISPERCPP = ROOT / "build_cache" / "whispercpp" / "bin"
if not (WHISPERCPP / "whisper.dll").exists():
    raise SystemExit("whisper.cpp is not built: run tools/build_whispercpp.py")
binaries += [(str(p), "whispercpp") for p in sorted(WHISPERCPP.glob("*.dll"))]

datas = [(str(ROOT / "assets"), "assets")]
datas += collect_data_files("faster_whisper")      # the Silero VAD model
datas += collect_data_files("_sounddevice_data")   # PortAudio

excludes = [
    "tkinter", "pystray", "PIL", "matplotlib", "IPython", "pytest", "jiwer", "torch",
    # website tools (requirements-site.txt); urllib3 would otherwise pick up brotli
    "fontTools", "brotli", "_brotli",
    # NVIDIA's pip packages (see above) and FFmpeg, which only decodes audio files;
    # the app reads the microphone (see app._stub_unused_modules)
    "nvidia", "av", "hf_xet",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtConcurrent", "PySide6.QtPrintSupport",
]

a = Analysis(
    [str(ROOT / "MH-Speech to Text.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["win32clipboard"],
    excludes=excludes,
    noarchive=False,
)
# keep proprietary NVIDIA libraries out of the build: anything under nvidia/, and the
# cuDNN loader the CTranslate2 wheel carries (never loaded: Whisper doesn't need cuDNN)
a.binaries = [b for b in a.binaries
              if not b[0].replace("\\", "/").startswith("nvidia/")
              and not b[0].lower().endswith("cudnn64_9.dll")
              and b[0].lower() != "vulkan-1.dll"]  # part of the graphics driver
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MH-Speech to Text",
    icon=str(ROOT / "assets" / "icons" / "app.ico"),
    version=str(ROOT / "installer" / "version_info.txt"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MH-Speech to Text")
