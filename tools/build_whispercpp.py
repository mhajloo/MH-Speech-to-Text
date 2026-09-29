"""Build whisper.cpp with Vulkan (any graphics card) for the app.

Output: build_cache/whispercpp/bin, the DLLs the app loads (see
dictation/whispercpp.py). whisper-quantize.exe and whisper-cli.exe, for making
and testing models (not shipped), stay in build_cache/whispercpp/build/bin/Release.

Needs Visual Studio 2022 (Build Tools with C++), CMake and the Vulkan SDK
(VULKAN_SDK set, or installed in C:\\VulkanSDK). GitHub Actions has the first
two; the workflow installs the SDK.

Usage: .venv/Scripts/python tools/build_whispercpp.py [--force]
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "v1.9.4"
COMMIT = "927cfce34f31707e17f2bff35c349632fb9e2c3a"  # what VERSION pointed to when tested
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "build_cache" / "whisper.cpp"
BUILD = ROOT / "build_cache" / "whispercpp" / "build"
BIN = ROOT / "build_cache" / "whispercpp" / "bin"

CMAKE_OPTIONS = [
    "-DBUILD_SHARED_LIBS=ON",
    "-DGGML_VULKAN=ON",            # AMD, Intel and NVIDIA graphics cards
    "-DGGML_BACKEND_DL=ON",        # backends are separate DLLs, loaded if their driver exists
    "-DGGML_CPU_ALL_VARIANTS=ON",  # CPU code for every instruction set, picked at run time
    "-DGGML_NATIVE=OFF",
    "-DGGML_OPENMP=OFF",           # OpenMP would need vcomp140.dll on the user's PC
    "-DWHISPER_BUILD_TESTS=OFF",
    "-DWHISPER_BUILD_SERVER=OFF",
    "-DWHISPER_SDL2=OFF",
    # binaries from recent MSVC crash with an older msvcp140.dll already in the process;
    # *_FLAGS_INIT keeps CMake's default MSVC flags and adds this define
    "-DCMAKE_CXX_FLAGS_INIT=/D_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR",
    "-DCMAKE_C_FLAGS_INIT=/D_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR",
]


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def find_cmake():
    found = shutil.which("cmake")
    if found:
        return found
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                   "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if vswhere.exists():
        vs = subprocess.run([vswhere, "-latest", "-products", "*", "-property", "installationPath"],
                            capture_output=True, text=True).stdout.strip()
        cmake = Path(vs, "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "CMake", "bin",
                     "cmake.exe")
        if cmake.exists():
            return str(cmake)
    raise SystemExit("CMake not found: install Visual Studio Build Tools with C++ (it includes CMake)")


def vulkan_env():
    env = dict(os.environ)
    if not env.get("VULKAN_SDK"):
        sdks = sorted(Path(r"C:\VulkanSDK").glob("*")) if Path(r"C:\VulkanSDK").exists() else []
        if not sdks:
            raise SystemExit("Vulkan SDK not found: https://vulkan.lunarg.com/sdk/home#windows")
        env["VULKAN_SDK"] = str(sdks[-1])
    env["PATH"] = str(Path(env["VULKAN_SDK"], "Bin")) + os.pathsep + env["PATH"]
    print(f"Vulkan SDK: {env['VULKAN_SDK']}")
    return env


def main():
    if (BIN / "whisper.dll").exists() and "--force" not in sys.argv:
        print(f"whisper.cpp already built in {BIN.relative_to(ROOT)} (--force rebuilds)")
        return
    if not SRC.exists():
        run(["git", "clone", "--depth", "1", "--branch", VERSION,
             "https://github.com/ggml-org/whisper.cpp", SRC])
    head = subprocess.run(["git", "-C", SRC, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != COMMIT:
        raise SystemExit(f"{SRC} is at {head or 'no commit'}, expected {VERSION} ({COMMIT})")

    cmake, env = find_cmake(), vulkan_env()
    run([cmake, "-S", SRC, "-B", BUILD, "-G", "Visual Studio 17 2022", "-A", "x64", *CMAKE_OPTIONS],
        env=env)
    run([cmake, "--build", BUILD, "--config", "Release", "--parallel"], env=env)

    out = BUILD / "bin" / "Release"
    shutil.rmtree(BIN, ignore_errors=True)
    BIN.mkdir(parents=True)
    dlls = sorted(out.glob("whisper.dll")) + sorted(out.glob("ggml*.dll"))
    for dll in dlls:
        shutil.copy2(dll, BIN / dll.name)
    total = sum(f.stat().st_size for f in BIN.iterdir())
    print(f"\n{len(dlls)} DLLs -> {BIN.relative_to(ROOT)} ({total / 1e6:.0f} MB)")
    for f in sorted(BIN.iterdir()):
        print(f"  {f.name}  {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
