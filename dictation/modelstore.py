"""Downloadable parts of the app: speech models and the NVIDIA GPU pack.

Neither ships in the installer: the model is 1.6 GB, and NVIDIA's cuBLAS is
proprietary (the installer contains only open-source code) and only useful on
PCs with an NVIDIA graphics card. Both are fetched on first run, first from the
project's own site, then from public mirrors.

Downloads resume after an interruption, fall back to the next source when one
fails, and check sizes and SHA-256 hashes before anything is used, so a broken
download can never crash the app later. Both can also be installed from a .zip
(e.g. copied from another computer).
"""
import hashlib
import shutil
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .branding import SITE_MODELS_URL, SITE_RUNTIME_URL
from .paths import FROZEN, GPU_DIR, MODELS_DIR

# what faster-whisper actually reads
REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.json",
                  "preprocessor_config.json")


@dataclass
class ModelInfo:
    id: str
    title: str
    description: str
    repo: str
    revision: str
    files: dict = field(default_factory=dict)  # name -> (size, sha256 or None)

    @property
    def size(self) -> int:
        return sum(s for s, _ in self.files.values())


CATALOG = [
    ModelInfo(
        id="fa-amirmohseni-large-v3",
        title="فارسی دقیق (Whisper large-v3)",
        description="دقیق‌ترین مدل در آزمایش‌ها؛ کلمات محاوره را همان‌طور که گفته می‌شوند می‌نویسد. "
                    "به کارت گرافیک NVIDIA نیاز دارد.",
        repo="AmirMohseni/whisper-large-v3-persian-ct2-int8",
        revision="5f850f99dc4db15a526e42b73027481a9f24327d",
        files={
            "model.bin": (1551326177, "cb84937d374e11a96879f774404cb5c3d5e52b06b145aa9acd7a67c0d193991d"),
            "config.json": (2263, "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e"),
            "tokenizer.json": (3930645, "5c1bf30c9e716e1477bedef846b01be0013daecb89e9e3ef7ab89b23c178df1b"),
            "vocabulary.json": (1068114, "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1"),
            "preprocessor_config.json": (340, "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711"),
        },
    ),
]
DEFAULT_MODEL = CATALOG[0].id

# (name, URL template). Templates use {repo} {revision} {model} {file}.
MIRRORS = ([("سایت برنامه", SITE_MODELS_URL.rstrip("/") + "/{model}/{file}")] if SITE_MODELS_URL else []) + [
    ("Hugging Face", "https://huggingface.co/{repo}/resolve/{revision}/{file}"),
    ("hf-mirror", "https://hf-mirror.com/{repo}/resolve/{revision}/{file}"),
]

# NVIDIA cuBLAS: the two DLLs CTranslate2 loads to run on the GPU (measured: nothing else)
GPU_PACK_TITLE = "شتاب‌دهنده‌ی کارت گرافیک NVIDIA"
GPU_FILES = {
    "cublas64_12.dll": (102518272, "52ce5ba0ec5327d39be6021f0f9362d2ed4d64d7206f9b5afc06398d827b8e82"),
    "cublasLt64_12.dll": (668673536, "71705a7cf0923f4ab034d0d2620bbfc989ff669ac3d79f868b7a7c597ca559c5"),
}
# (name, archive URL, archive size): any zip holding the DLLs works, e.g. NVIDIA's pip wheel
GPU_SOURCES = ([("سایت برنامه", SITE_RUNTIME_URL.rstrip("/") + "/cublas-12.9-win64.zip", 450752886)]
               if SITE_RUNTIME_URL else []) + [
    ("PyPI", "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1"
             "a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl", 553162896),
]


def catalog_entry(model_id):
    return next((m for m in CATALOG if m.id == model_id), None)


def model_dir(model_id) -> Path:
    return MODELS_DIR / model_id


def is_installed(model_id) -> bool:
    d = model_dir(model_id)
    if not all((d / f).is_file() for f in REQUIRED_FILES):
        return False
    info = catalog_entry(model_id)
    if info:  # a half-copied model.bin must not count as installed
        return all((d / n).stat().st_size == s for n, (s, _) in info.files.items())
    return True


def installed_models():
    if not MODELS_DIR.exists():
        return []
    return sorted(p.name for p in MODELS_DIR.iterdir()
                  if p.is_dir() and not p.name.endswith(".partial") and is_installed(p.name))


def gpu_pack_installed() -> bool:
    if all((GPU_DIR / n).is_file() and (GPU_DIR / n).stat().st_size == s
           for n, (s, _) in GPU_FILES.items()):
        return True
    if not FROZEN:  # from source, pip's nvidia-cublas-cu12 package provides the DLLs
        import site
        return any((Path(sp) / "nvidia" / "cublas" / "bin" / "cublasLt64_12.dll").exists()
                   for sp in site.getsitepackages())
    return False


def size_text(n: int) -> str:
    from .ui.theme import fa
    if n >= 1e9:
        return f"{fa(f'{n / 1e9:.2f}'.rstrip('0').rstrip('.'))} گیگابایت"
    return f"{fa(round(n / 1e6))} مگابایت"


class Cancelled(Exception):
    pass


class DownloadError(Exception):
    pass


def _sha256(path: Path, cancel=None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            if cancel and cancel.is_set():
                raise Cancelled()
            h.update(chunk)
    return h.hexdigest()


def _fetch(url, dest: Path, size, on_bytes, cancel):
    """Download url into dest until it holds `size` bytes, resuming what is
    already there. on_bytes(n) is called for every chunk received."""
    have = dest.stat().st_size if dest.exists() else 0
    if have > size:
        dest.unlink()
        have = 0
    for attempt in range(4):
        if have == size:
            return
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "MH-Speech-to-Text",
                # shared hosts often gzip .json files; urllib would save them compressed
                "Accept-Encoding": "identity",
                **({"Range": f"bytes={have}-"} if have else {})})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if have and resp.status != 206:  # server ignored the range: start over
                    have = 0
                with open(dest, "ab" if have else "wb") as out:
                    while chunk := resp.read(1 << 20):
                        if cancel and cancel.is_set():
                            raise Cancelled()
                        out.write(chunk)
                        have += len(chunk)
                        on_bytes(len(chunk))
            if have != size:
                raise DownloadError(f"{dest.name}: incomplete ({have}/{size})")
            return
        except Cancelled:
            raise
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
            have = dest.stat().st_size if dest.exists() else 0


class _Meter:
    """Turns chunk callbacks into progress(done, total, bytes_per_s, source)."""

    def __init__(self, progress, total, done=0):
        self.progress, self.total, self.done = progress, total, done
        self.started, self.got, self.source = time.monotonic(), 0, ""

    def __call__(self, n):
        self.done += n
        self.got += n
        if self.progress:
            rate = self.got / max(time.monotonic() - self.started, 1e-3)
            self.progress(self.done, self.total, rate, self.source)


def download(info: ModelInfo, mirrors=None, progress=None, cancel=None, log=print):
    """Download a speech model into the models folder. progress(done, total,
    bytes_per_s, source). Raises DownloadError after every mirror failed, or Cancelled."""
    part = MODELS_DIR / f"{info.id}.partial"
    part.mkdir(parents=True, exist_ok=True)
    have = sum(min((part / n).stat().st_size, s) for n, (s, _) in info.files.items() if (part / n).exists())
    meter = _Meter(progress, info.size, have)
    last_error = None
    for name_, template in mirrors or MIRRORS:
        meter.source = name_
        try:
            for name, (size, _) in info.files.items():
                url = template.format(repo=info.repo, revision=info.revision, model=info.id, file=name)
                _fetch(url, part / name, size, meter, cancel)
            break
        except Cancelled:
            raise
        except Exception as e:  # try the next mirror; partial files are kept for resuming
            last_error = e
            log(f"[download] {name_} failed: {e}")
    else:
        raise DownloadError(str(last_error))

    if progress:  # hashing 1.6 GB takes a few seconds: show it isn't stuck
        progress(info.size, info.size, 0.0, meter.source)
    for name, (size, digest) in info.files.items():
        f = part / name
        if f.stat().st_size != size or (digest and _sha256(f, cancel) != digest):
            f.unlink(missing_ok=True)
            raise DownloadError(f"{name}: فایل دانلودشده سالم نیست")
    final = model_dir(info.id)
    if final.exists():
        shutil.rmtree(final)
    part.rename(final)


def download_gpu_pack(sources=None, progress=None, cancel=None, log=print):
    """Download the cuBLAS archive, unpack the two DLLs into GPU_DIR, verify them."""
    GPU_DIR.mkdir(parents=True, exist_ok=True)
    last_error = None
    for name, url, size in sources or GPU_SOURCES:
        archive = GPU_DIR / f"download-{name.encode().hex()[:8]}.partial"
        meter = _Meter(progress, size, archive.stat().st_size if archive.exists() else 0)
        meter.source = name
        try:
            _fetch(url, archive, size, meter, cancel)
            if progress:  # unpacking and checking ~770 MB takes a while
                progress(size, size, 0.0, name)
            _install_gpu_archive(archive, cancel)
            archive.unlink(missing_ok=True)
            return
        except Cancelled:
            raise
        except Exception as e:
            last_error = e
            log(f"[gpu pack] {name} failed: {e}")
            if isinstance(e, (zipfile.BadZipFile, DownloadError)) and archive.exists() \
                    and archive.stat().st_size >= size:
                archive.unlink()  # complete but wrong: don't resume from it
    raise DownloadError(str(last_error))


def _install_gpu_archive(archive: Path, cancel=None):
    """Unpack cuBLAS from any zip (our pack or NVIDIA's wheel) and verify it."""
    with zipfile.ZipFile(archive) as z:
        members = {Path(i.filename).name: i for i in z.infolist() if Path(i.filename).name in GPU_FILES}
        if set(members) != set(GPU_FILES):
            raise DownloadError("فایل‌های شتاب‌دهنده در این بسته پیدا نشد.")
        for name, info in members.items():
            tmp = GPU_DIR / f"{name}.partial"
            with z.open(info) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 8 << 20)
            size, digest = GPU_FILES[name]
            if tmp.stat().st_size != size or _sha256(tmp, cancel) != digest:
                tmp.unlink(missing_ok=True)
                raise DownloadError(f"{name}: فایل سالم نیست")
            tmp.replace(GPU_DIR / name)


def _zip_names(path: Path):
    with zipfile.ZipFile(path) as z:
        return {Path(n).name for n in z.namelist()}


def import_file(source: Path):
    """Install from a .zip or folder: a speech model or the GPU pack, whichever it
    holds. Returns ("model", id) or ("gpu", None)."""
    source = Path(source)
    if source.is_file() and source.suffix.lower() in (".zip", ".whl") \
            and set(GPU_FILES) <= _zip_names(source):
        GPU_DIR.mkdir(parents=True, exist_ok=True)
        _install_gpu_archive(source)
        return "gpu", None
    return "model", import_model(source)


def import_model(source: Path) -> str:
    """Install a model from a folder or a .zip. Returns its id."""
    source = Path(source)
    staging = MODELS_DIR / "import.partial"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as z:
                z.extractall(staging)
            root = next((p.parent for p in staging.rglob("model.bin")), None)
        else:
            root = source if (source / "model.bin").exists() else next(
                (p.parent for p in source.rglob("model.bin")), None)
        if root is None or not all((root / f).is_file() for f in REQUIRED_FILES):
            raise DownloadError("در این مسیر، فایل‌های لازم مدل (model.bin و ...) پیدا نشد.")
        # recognise a catalog model by its file sizes; otherwise use the folder name
        model_id = next((m.id for m in CATALOG if all(
            (root / n).exists() and (root / n).stat().st_size == s for n, (s, _) in m.files.items())),
            root.name if root != staging else "imported-model")
        target = model_dir(model_id)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for f in REQUIRED_FILES:
            if root.is_relative_to(staging):
                shutil.move(str(root / f), target / f)
            else:
                shutil.copy2(root / f, target / f)
        return model_id
    finally:
        shutil.rmtree(staging, ignore_errors=True)
