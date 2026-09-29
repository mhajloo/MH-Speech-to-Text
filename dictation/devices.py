"""Where speech recognition runs, and what that needs.

Two engines run the same Persian model, each in its own format:
- CTranslate2 ("ct2"): NVIDIA cards through CUDA (with the downloaded GPU pack),
  and the CPU. The fastest on both.
- whisper.cpp ("ggml"): any graphics card through Vulkan: AMD, Intel and NVIDIA.

Measured on a laptop (i7-1185G7, T500, Iris Xe) with the user's voice, as wait
after releasing the key / word error rate:
  CT2 on the T500 1.3 s / 10.9%        whisper.cpp on the T500 1.6 s / 11.3%
  whisper.cpp on the Iris Xe, greedy 2.7 s / 13.5%   CT2 on the CPU, greedy 3.6 s / 13.5%
"auto" skips integrated graphics: older ones are slower than the CPU.

Config.device is "auto", "cpu" or "gpu:<card name>" (a name, because card
numbers can change when drivers or cards do).
"""
import threading
from dataclasses import dataclass

from . import modelstore, sysinfo, whispercpp

CT2_MODEL = modelstore.DEFAULT_MODEL
GGML_MODEL = next((m.id for m in modelstore.CATALOG if m.kind == "ggml"), None)


@dataclass(frozen=True)
class Card:
    name: str
    integrated: bool
    memory_mb: int
    vulkan: int | None  # whisper.cpp gpu_device, None if whisper.cpp can't use it
    nvidia: bool


@dataclass(frozen=True)
class Target:
    engine: str             # "ct2" or "whispercpp"
    device: str             # "cuda", "gpu" (Vulkan) or "cpu"
    model: str              # model id in the format this engine reads
    card: Card | None = None

    @property
    def label(self) -> str:
        return f"کارت گرافیک {self.card.name}" if self.card else "پردازنده"

    @property
    def fast_decoding(self) -> bool:
        """Greedy decoding keeps weak processors up with speech (measured on a
        4-core laptop CPU: 3-4 s wait after release instead of 7-13 s)."""
        return self.device == "cpu" or bool(self.card and self.card.integrated)


_cards = None
_cards_lock = threading.Lock()


def cards() -> tuple[Card, ...]:
    """Graphics cards the app can use: discrete ones first, the most memory first.
    Found once (loading Vulkan takes about a second), from any thread."""
    global _cards
    with _cards_lock:
        if _cards is None:
            nv = sysinfo.nvidia_gpu()
            found = [Card(g.name, g.integrated, g.memory_mb, g.index, "nvidia" in g.name.lower())
                     for g in whispercpp.gpus()]
            if nv and not any(c.nvidia for c in found):  # CUDA works without Vulkan too
                found.append(Card(nv[0], False, nv[1], None, True))
            _cards = tuple(sorted(found, key=lambda c: (c.integrated, -c.memory_mb)))
        return _cards


def find_card(name):
    return next((c for c in cards() if c.name == name), None)


def any_model_installed(preferred=None) -> bool:
    return any(modelstore.is_installed(m) for m in {preferred, CT2_MODEL, GGML_MODEL} if m)


def _models(preferred):
    """(ct2 model, ggml model, whether ggml was chosen): the model chosen in the
    settings (e.g. added from a file) for its format, the catalog one for the other."""
    ct2, ggml, chose_ggml = CT2_MODEL, GGML_MODEL, False
    if preferred and modelstore.is_installed(preferred):
        if modelstore.model_kind(preferred) == "ggml":
            ggml, chose_ggml = preferred, True
        else:
            ct2 = preferred
    have = modelstore.is_installed
    return (ct2 if have(ct2) else None), (ggml if ggml and have(ggml) else None), chose_ggml


def _gpu_targets(card: Card, ct2, ggml, chose_ggml) -> list[Target]:
    out = []
    if card.nvidia and ct2 and modelstore.gpu_pack_installed():
        out.append(Target("ct2", "cuda", ct2, card))
    if card.vulkan is not None and ggml:  # on NVIDIA cards second, unless its model was chosen
        out.insert(0 if chose_ggml else len(out), Target("whispercpp", "gpu", ggml, card))
    return out


def targets(device: str, model: str | None = None) -> list[Target]:
    """What to try, best first; the engine uses the first one that loads."""
    ct2, ggml, chose_ggml = _models(model)
    chosen = []
    if device.startswith("gpu:"):
        card = find_card(device[4:])
        chosen = _gpu_targets(card, ct2, ggml, chose_ggml) if card else []
    elif device != "cpu":  # auto: a separate graphics card; integrated ones only if chosen
        for card in cards():
            if not card.integrated:
                chosen += _gpu_targets(card, ct2, ggml, chose_ggml)
    cpu = [Target("ct2", "cpu", ct2)] if ct2 else []
    if ggml:  # 2.4x slower than CTranslate2 on the CPU: only when its model is missing
        cpu.append(Target("whispercpp", "cpu", ggml))
    return chosen + cpu


def best_card() -> Card | None:
    return next((c for c in cards() if not c.integrated), None)


def requirements(device: str) -> tuple[str, bool]:
    """(catalog model id, whether the NVIDIA GPU pack is needed) to run on `device`."""
    card = find_card(device[4:]) if device.startswith("gpu:") else (
        None if device == "cpu" else best_card())
    if card and card.nvidia:
        return CT2_MODEL, True
    if card and card.vulkan is not None and GGML_MODEL:
        return GGML_MODEL, False
    return CT2_MODEL, False  # the CPU runs CTranslate2's format: whisper.cpp is 2.4x slower there


def needs(device: str) -> dict:
    """What to download so `device` can be used: {"model": id or None, "gpu_pack": bool}."""
    model, pack = requirements(device)
    return {"model": None if modelstore.is_installed(model) else model,
            "gpu_pack": pack and not modelstore.gpu_pack_installed()}


def options() -> list[tuple[str, str]]:
    """(Config.device value, Persian label) for the settings."""
    out = [("auto", "خودکار")]
    for c in cards():
        out.append((f"gpu:{c.name}", f"کارت گرافیک {c.name}" + (" (مجتمع)" if c.integrated else "")))
    out.append(("cpu", "پردازنده"))
    return out
