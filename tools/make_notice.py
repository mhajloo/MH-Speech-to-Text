"""Write assets/NOTICE.txt: the licenses of everything shipped with the app.

Python packages are found by checking which of them PyInstaller actually put in
the build, and their license files are copied from the installed metadata; the
models, whisper.cpp, font, word lists and NVIDIA libraries are described by hand.

Usage (after a PyInstaller build): .venv/Scripts/python tools/make_notice.py
"""
import importlib.metadata as md
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "dist" / "MH-Speech to Text" / "_internal"
WORK = ROOT / "build" / "work" / "mhstt"
OUT = ROOT / "assets" / "NOTICE.txt"
WHISPERCPP_LICENSE = ROOT / "build_cache" / "whisper.cpp" / "LICENSE"  # tools/build_whispercpp.py
sys.path.insert(0, str(ROOT))
from dictation.branding import APP_NAME, APP_VERSION, AUTHOR_EN, GITHUB, WEBSITE  # noqa: E402

HEADER = f"""{APP_NAME} {APP_VERSION}
Copyright (c) 2026 {AUTHOR_EN} - {WEBSITE} - {GITHUB}

{APP_NAME} is free and open-source software, released under the MIT License:

{(ROOT / "LICENSE").read_text(encoding="utf-8").strip()}

It includes the third-party components listed below, each under its own
license. Full license texts follow the list.

Components that are not Python packages
---------------------------------------
* Speech model: OpenAI Whisper large-v3 (MIT License, https://github.com/openai/whisper),
  Persian fine-tune "AmirMohseni/whisper-large-v3-persian-ct2-int8" (Apache License 2.0,
  https://huggingface.co/AmirMohseni/whisper-large-v3-persian-ct2-int8). For AMD and Intel
  graphics cards the same fine-tune comes in whisper.cpp's format, converted by this project
  (tools/convert_ggml.py) from "AmirMohseni/whisper-large-v3-persian-bf16", the checkpoint
  the model above was made from, which is based on
  "MohammadGholizadeh/whisper-large-v3-persian-common-voice-17" (Apache License 2.0).
  The models are downloaded on first use and are not part of the installer.
* whisper.cpp and ggml (whispercpp/whisper.dll, ggml*.dll): MIT License, Copyright (c)
  2023-2026 The ggml authors, https://github.com/ggml-org/whisper.cpp (full text below).
  ggml-vulkan.dll contains the Khronos Group's Vulkan C++ headers (Apache License 2.0 or
  MIT, https://github.com/KhronosGroup/Vulkan-Hpp). The Vulkan loader (vulkan-1.dll) is not
  included: it comes with the graphics driver.
* NVIDIA cuBLAS (cublas64_12.dll, cublasLt64_12.dll) is NOT included in the installer. On PCs
  with an NVIDIA GPU the app downloads it on first use; it is licensed under the NVIDIA CUDA
  Toolkit End User License Agreement, https://docs.nvidia.com/cuda/eula/
* Vazirmatn font, designed by the late Saber Rastikerdar (Copyright 2015 The Vazirmatn
  Project Authors): SIL Open Font License 1.1 (full text in assets/fonts/OFL.txt),
  https://github.com/rastikerdar/vazirmatn
* Half-space word list (assets/data/zwnj_words.txt), generated from:
  - Hazm word and verb lists, Copyright (c) Roshan / Sobhe: MIT License,
    https://github.com/roshan-research/hazm
  - Mozilla Common Voice Persian sentences: CC0 1.0 (public domain),
    https://github.com/common-voice/common-voice
* Qt 6 via PySide6 / Shiboken6: GNU LGPL v3. Qt is used as unmodified shared libraries;
  its source code is available at https://download.qt.io/official_releases/qt/ and
  https://code.qt.io/, and you may replace the Qt DLLs in this program's folder with
  compatible versions.
* Silero VAD model (bundled with faster-whisper): MIT License, https://github.com/snakers4/silero-vad
* pywin32 (win32clipboard, pywintypes): Python Software Foundation License,
  https://github.com/mhammond/pywin32
* PortAudio (bundled with sounddevice): MIT-style license, http://www.portaudio.com/

Python packages
---------------
"""


def bundled_distributions():
    """Distributions whose modules PyInstaller put in the build: folders and DLLs in
    _internal, plus the pure-Python modules listed in the PYZ archive's TOC."""
    names = {p.name.split(".")[0] for p in BUILD.iterdir()} if BUILD.exists() else set()
    toc = WORK / "PYZ-00.toc"
    if toc.exists():
        names |= set(re.findall(r"\(\s*'([A-Za-z0-9_]+)[.']", toc.read_text(errors="replace")))
    owners = md.packages_distributions()
    dist_names = {d for n in names for d in owners.get(n, [])}
    found = {}
    for name in dist_names:
        try:
            d = md.distribution(name)
            found[d.metadata["Name"].lower()] = d
        except md.PackageNotFoundError:
            pass
    return [found[k] for k in sorted(found)]


def license_texts(dist):
    texts = []
    for f in dist.files or []:
        name = Path(str(f)).name.upper()
        if name.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")) and str(f).count("/") <= 3:
            try:
                raw = Path(f.locate()).read_bytes().decode("utf-8", errors="replace")
                # some license files use CRLF; mixed endings would double the line breaks
                texts.append((str(f), raw.replace("\r\n", "\n").replace("\r", "\n").strip()))
            except (OSError, ValueError):
                pass
    return texts


def main():
    if not WHISPERCPP_LICENSE.exists():
        sys.exit(f"{WHISPERCPP_LICENSE} not found: run tools/build_whispercpp.py")
    dists = bundled_distributions()
    parts = [HEADER]
    for d in dists:
        m = d.metadata
        first_line = ((m.get("License") or "").strip().splitlines() or [""])[0][:80]
        classifiers = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or []
                       if c.startswith("License ::")]
        lic = m.get("License-Expression") or first_line or ", ".join(classifiers) or "see text"
        parts.append(f"* {m['Name']} {d.version}: {lic}  {m.get('Home-page') or ''}".rstrip())
    parts.append("\n\nLicense texts\n=============\n")
    ggml = WHISPERCPP_LICENSE.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    parts.append(f"\n----- whisper.cpp and ggml (LICENSE) -----\n\n{ggml}\n")
    for d in dists:
        for path, text in license_texts(d):
            parts.append(f"\n----- {d.metadata['Name']} ({path}) -----\n\n{text}\n")
    text = "\n".join(parts)
    OUT.write_text(text, encoding="utf-8")
    if BUILD.exists():
        (BUILD / "assets" / "NOTICE.txt").write_text(text, encoding="utf-8")
    print(f"{len(dists)} packages -> {OUT.relative_to(ROOT)} ({len(text) // 1024} KB)")


if __name__ == "__main__":
    main()
