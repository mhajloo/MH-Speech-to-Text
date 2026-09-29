"""What hardware the speech model can use."""
import subprocess
from functools import lru_cache

CREATE_NO_WINDOW = 0x08000000


@lru_cache(maxsize=1)
def nvidia_gpu():
    """(name, memory in MB) of the first NVIDIA GPU, or None."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, creationflags=CREATE_NO_WINDOW).stdout
        name, mem = out.strip().splitlines()[0].rsplit(",", 1)
        return name.strip(), int(float(mem))
    except Exception:
        return None


def cuda_usable() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
