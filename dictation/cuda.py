import os
import site
from pathlib import Path

from .paths import FROZEN, GPU_DIR

_added = set()


def add_cuda_dlls():
    """Make NVIDIA's cuBLAS visible to CTranslate2: the downloaded GPU pack, or,
    when running from source, pip's nvidia-* wheels. Safe to call again after the
    GPU pack has been downloaded."""
    dirs = [GPU_DIR]
    if not FROZEN:
        dirs += [Path(sp) / "nvidia" / sub / "bin" for sp in site.getsitepackages()
                 for sub in ("cublas", "cudnn", "cuda_nvrtc")]
    for d in dirs:
        if d.is_dir() and str(d) not in _added:
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
            _added.add(str(d))
