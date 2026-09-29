"""Build the Windows installer in one go:
icons → whisper.cpp → PyInstaller app folder → NOTICE.txt → (signing) → Inno Setup installer.

Usage: .venv/Scripts/python tools/build.py [--skip-app]
Output: build/installer/MH-Speech-to-Text-Setup-<version>.exe

Signing happens automatically when a certificate is configured through the
MHSTT_SIGN_* environment variables described in tools/sign.ps1.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = Path(sys.executable)
APP_EXE = ROOT / "build" / "dist" / "MH-Speech to Text" / "MH-Speech to Text.exe"
SIGN_PS1 = ROOT / "tools" / "sign.ps1"
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]


def run(*cmd):
    print("\n>", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=ROOT, check=True)


def signing_configured() -> bool:
    return bool(os.environ.get("MHSTT_SIGN_THUMBPRINT") or os.environ.get("MHSTT_SIGN_PFX"))


def find_iscc() -> Path:
    """Inno Setup's compiler, installed per user (winget), for all users (Chocolatey
    on GitHub Actions) or anywhere on PATH (Chocolatey puts it there too)."""
    dirs = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    candidates = [d / "Inno Setup 6" / "ISCC.exe" for d in dirs]
    found = next((p for p in candidates if p.exists()), None) or shutil.which("ISCC")
    if not found:
        sys.exit("Inno Setup 6 not found; looked in:\n  " + "\n  ".join(map(str, candidates))
                 + "\n  and on PATH")
    return Path(found)


def main():
    iscc_exe = find_iscc()
    sign = signing_configured()
    run(PY, "tools/make_assets.py")
    if "--skip-app" not in sys.argv:
        run(PY, "tools/build_whispercpp.py")  # once: kept in build_cache/
        shutil.rmtree(ROOT / "build" / "dist", ignore_errors=True)
        shutil.rmtree(ROOT / "build" / "work", ignore_errors=True)
        run(PY.with_name("pyinstaller.exe"), "installer/mhstt.spec", "--noconfirm",
            "--distpath", "build/dist", "--workpath", "build/work", "--log-level", "WARN")
    run(PY, "tools/make_notice.py")
    iscc = [iscc_exe, "/Q"]
    if sign:
        run(*POWERSHELL, SIGN_PS1, APP_EXE)
        # Inno Setup signs the installer and the uninstaller with this command
        # ($f = the file, $q = a quote: literal quotes would break ISCC's command line)
        iscc += ["/DSIGN", f"/Smhsign={' '.join(POWERSHELL)} $q{SIGN_PS1}$q $f"]
    else:
        print("\n(no code-signing certificate configured: building unsigned)")
    run(*iscc, "installer/mhstt.iss")
    out = sorted((ROOT / "build" / "installer").glob("*.exe"))[-1]
    print(f"\ninstaller: {out} ({out.stat().st_size / 1e6:.0f} MB, {'signed' if sign else 'unsigned'})")


if __name__ == "__main__":
    main()
