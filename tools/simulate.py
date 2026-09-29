"""Feed an audio file through the real Session/Engine pipeline at real-time speed,
as if it were spoken while holding the hotkey, and report latency after "release".

Usage: .venv/Scripts/python tools/simulate.py audio.mp3 [--model turbo] [--compute float16]
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dictation.cuda import add_cuda_dlls  # noqa: E402

add_cuda_dlls()
sys.stdout.reconfigure(encoding="utf-8")
from faster_whisper import decode_audio  # noqa: E402

from dictation.audio import BLOCK, SR, Session  # noqa: E402
from dictation.config import Config  # noqa: E402
from dictation.engine import Engine  # noqa: E402
from dictation.textfix import fix  # noqa: E402


class FakeRecorder:
    def __init__(self, audio, speed=1.0):
        self.audio, self.speed, self.level = audio, speed, 0.0
        self.done = threading.Event()

    def start_capture(self):
        sink = []

        def feed():
            for i in range(0, len(self.audio), BLOCK):
                sink.append(self.audio[i:i + BLOCK])
                time.sleep(BLOCK / SR / self.speed)
            self.done.set()
        threading.Thread(target=feed, daemon=True).start()
        return sink

    def stop_capture(self):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="+")
    ap.add_argument("--model", default="turbo")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--speed", type=float, default=1.0, help=">1 feeds faster than real time")
    args = ap.parse_args()

    cfg = Config(model=args.model, compute_type=args.compute, beam_size=args.beam)
    t0 = time.perf_counter()
    engine = Engine(cfg)
    engine.ready.wait()
    print(f"model load+warmup: {time.perf_counter() - t0:.1f}s")

    for path in args.audio:
        audio = decode_audio(path)
        rec = FakeRecorder(audio, args.speed)
        s = Session(rec, engine, tail_ms=0)
        rec.done.wait()
        released = time.perf_counter()
        raw = s.finish()
        wait = time.perf_counter() - released
        print(f"\n{Path(path).name}: {len(audio) / SR:.1f}s audio, {len(s.futures)} chunk(s), "
              f"{wait:.2f}s after release")
        print(fix(raw))


if __name__ == "__main__":
    main()
