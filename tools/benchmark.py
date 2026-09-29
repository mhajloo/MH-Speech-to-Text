"""Score models on recordings through the app's exact pipeline (live chunking
emulation, silence trim, prompt carry-over, text fixes).

Usage: .venv/Scripts/python tools/benchmark.py MODEL [MODEL...] [--files a.m4a ...]
       [--compute int8_float16] [--modes fast,full] [--beam 5] [--quiet]
Default files: every audio file in samples/. A same-named .txt with the exact
words spoken enables WER/CER scoring; without it the output is only recorded.
Per-file outputs go to bench_results/ (.md for reading, .json for tools/diff.py).
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dictation.cuda import add_cuda_dlls  # noqa: E402

add_cuda_dlls()
sys.stdout.reconfigure(encoding="utf-8")
import jiwer  # noqa: E402
from faster_whisper import decode_audio  # noqa: E402

from dictation.audio import SR, Dictation, plan_step  # noqa: E402
from dictation.config import Config  # noqa: E402
from dictation.engine import Engine  # noqa: E402
from dictation.textfix import fix  # noqa: E402

TICK_S = 0.25  # Session loop period
AUDIO_EXT = {".wav", ".m4a", ".mp3", ".ogg", ".opus", ".flac", ".aac", ".webm", ".wma"}

# Scoring normalisation: compare words, not orthography (ZWNJ vs space,
# ی/ي, digits, punctuation, diacritics like the ezafe ٔ).
ZWNJ = "\u200c"
TRANS = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    **{p: str(i) for i, p in enumerate("۰۱۲۳۴۵۶۷۸۹")},
    **{a: str(i) for i, a in enumerate("٠١٢٣٤٥٦٧٨٩")},
})
PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
DIACRITICS = re.compile("[\u064b-\u065f\u0670]")


def normalize(text: str) -> str:
    text = DIACRITICS.sub("", text.translate(TRANS)).lower()
    text = text.replace(ZWNJ, " ")
    text = PUNCT.sub(" ", text)
    return " ".join(text.split())


TAIL_S = 0.25  # the app keeps recording this long after release (Config.tail_ms)


def emulate(engine, audio):
    """Replay a live Session on a virtual clock: audio arrives in real time, a
    piece starts only when the single GPU worker is free, and the end of the
    file is the moment the key is released.
    Returns (dictation, [(start, end, decode seconds, mode)], wait after release)."""
    d = Dictation()
    pieces = []
    gpu_free = 0.0

    def step(start, end, final=False):
        d.done = end
        t0 = time.perf_counter()
        engine.submit_step(d, start, end, final).result()
        dt = time.perf_counter() - t0
        pieces.append((start, end, dt, engine.last_mode))
        return dt

    tick = int(TICK_S * SR)
    for t in range(tick, len(audio) + tick, tick):
        now = min(t, len(audio))
        d.append(audio[d.n:now])
        if now / SR < gpu_free:
            continue
        cut = plan_step(d.undecoded(), first=not d.has_text())
        if cut:
            gpu_free = now / SR + step(d.done, d.done + cut)
    release = len(audio) / SR
    finished = max(release + TAIL_S, gpu_free)
    if d.n - d.done > 0.3 * SR:
        finished += step(d.done, d.n, final=True)
    return d, pieces, finished - release


def sample_files():
    return [f for f in sorted((ROOT / "samples").iterdir()) if f.suffix.lower() in AUDIO_EXT]


def run_model(name, files, args):
    cfg = Config(model=name, device=args.device, compute_type=args.compute, beam_size=args.beam,
                 final_beam_size=args.final_beam, vocabulary=args.vocab)
    engine = Engine(cfg)
    engine._pool.submit(lambda: None).result()  # worker is serial: returns after load
    if engine.error:
        print(f"{name}: failed to load: {engine.error}")
        return
    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    for mode in args.modes.split(","):
        cfg.fast_context = mode == "fast"
        total_t = wait_t = audio_s = 0.0
        refs, hyps, log, outputs = [], [], [], {}
        for f in files:
            ref_path = f.with_suffix(".txt")
            ref = ref_path.read_text(encoding="utf-8-sig").strip() if ref_path.exists() else None
            audio = decode_audio(str(f))
            d, pieces, wait = emulate(engine, audio)
            total_t += sum(p[2] for p in pieces)
            wait_t += wait
            audio_s += len(audio) / SR
            hyp = fix(d.text())
            outputs[f.name] = hyp
            modes = Counter(p[3] for p in pieces if p[3])
            info = (f"{len(audio) / SR:.0f}s audio, pieces "
                    + "+".join(f"{(e - s) / SR:.1f}" for s, e, _, _ in pieces)
                    + f"s {dict(modes)}, wait after release {wait:.2f}s")
            if ref:
                refs.append(normalize(ref))
                hyps.append(normalize(hyp))
                w = jiwer.wer(refs[-1], hyps[-1]) * 100
                log.append(f"## {f.name}  (WER {w:.0f}%, {info})\nREF: {ref}\nOUT: {hyp}\n")
            else:
                log.append(f"## {f.name}  ({info})\nOUT: {hyp}\n")
            if not args.quiet:
                print(f"  [{mode}] {f.name} ({info})\n    {hyp}")
        (out_dir / f"{name}_{mode}.md").write_text("\n".join(log), encoding="utf-8")
        (out_dir / f"{name}_{mode}.json").write_text(
            json.dumps(outputs, ensure_ascii=False, indent=1), encoding="utf-8")
        score = (f"WER {jiwer.wer(refs, hyps) * 100:5.1f}%  CER {jiwer.cer(refs, hyps) * 100:5.1f}%  "
                 if refs else "")
        print(f"{name:26s} {mode}: {score}speed {total_t / audio_s:.2f}s per 1s audio  "
              f"avg wait after release {wait_t / len(files):.2f}s", flush=True)
    engine._pool.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="int8_float16")
    ap.add_argument("--modes", default="fast")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--final-beam", type=int, default=1, help="beam after release (0 = --beam)")
    ap.add_argument("--vocab", nargs="*", default=[], help="Config.vocabulary terms")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="override a tuning constant, e.g. --set CONTEXT_S=6")
    args = ap.parse_args()
    import ast

    import dictation.audio
    import dictation.engine
    import dictation.fastdecode
    modules = (dictation.audio, dictation.engine, dictation.fastdecode)
    for item in args.set:
        name, value = item.split("=", 1)
        hit = [m for m in modules if hasattr(m, name)]
        if not hit:
            sys.exit(f"unknown constant {name}")
        for m in hit:  # also rebinds names copied by "from .audio import X"
            setattr(m, name, ast.literal_eval(value))
    a = dictation.audio
    print(f"first {a.FIRST_STEP_S}s, min step {a.MIN_STEP_S}s, end pause {a.END_PAUSE_S}s "
          f"(min {a.END_PAUSE_MIN_S}s), gaps {a.GAP_SCHEDULE}, max {a.MAX_STEP_S}s, "
          f"context {dictation.engine.USE_CONTEXT}; beam {args.beam}/{args.final_beam or args.beam}")
    files = [Path(f) for f in args.files] if args.files else sample_files()
    if not files:
        sys.exit("no samples: put audio files (+ same-named .txt references) in samples/")
    print(f"{len(files)} files")
    for name in args.models:
        run_model(name, files, args)


if __name__ == "__main__":
    main()
