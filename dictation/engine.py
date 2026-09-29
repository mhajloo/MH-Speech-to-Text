"""Speech-to-text engine: one resident Whisper model, one worker thread.

Pieces of a dictation are decoded strictly in order, each prompted with the
user's vocabulary plus the text before it. The piece left over at release can
use a smaller beam (Config.final_beam_size) because the user is waiting for it.
On the CPU and integrated graphics every piece is decoded greedily (beam 1), so
decoding keeps up with speech.

Where the model runs is decided by devices.targets(): CTranslate2 on NVIDIA
cards or the CPU, whisper.cpp (Vulkan) on any other card; the first target
that loads and passes a warm-up decode is used.

With USE_CONTEXT a piece is also decoded together with up to CONTEXT_S of the
audio before it (its text forced). Measured on real speech this was slower and
less accurate than long plain pieces, so it is off.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import devices, modelstore
from .audio import CONTEXT_S, SR, Piece, trim_silence
from .config import Config
from .textfix import is_hallucination

USE_CONTEXT = False
USE_PROMPT = True        # prompt each piece with the text before it
MAX_PREV_PIECE_S = 12.0  # context: always hear the previous piece if at most this long


class Engine:
    def __init__(self, cfg: Config, on_status=None):
        self.cfg = cfg
        self.model = self.decoder = None
        self.ready = threading.Event()
        self.error = None
        self.target = None  # devices.Target once loaded
        self.device = None  # "cuda", "gpu" or "cpu" once loaded
        self.failed = []    # (target, error) tried before the one that loaded
        self.on_status = on_status or (lambda s: None)
        self.last_mode = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
        self._pool.submit(self._load)

    def _load(self):
        try:
            self._load_model()
        except Exception as e:  # runs in the worker thread: make failures visible
            import traceback
            traceback.print_exc()
            self.error = str(e)
            self.on_status("error")

    def _load_model(self):
        self.on_status("loading")
        t0 = time.perf_counter()
        plan = devices.targets(self.cfg.device, self.cfg.model)
        if not plan:
            raise RuntimeError("no speech model is installed")
        for target in plan:
            try:
                decoder = self._open(target)
                # the first real request should not pay for GPU/kernel init, and a
                # GPU that can't really run (driver, cuBLAS) fails here, not mid-dictation
                decoder.warm_up()
                self.model = self.decoder = decoder
                self.target, self.device = target, target.device
                break
            except Exception as e:
                self.failed.append((target, e))
                print(f"[engine] {target.engine} on {target.label} failed ({e})", flush=True)
        else:
            raise self.failed[-1][1]
        print(f"[engine] {self.target.model} ready on {self.target.label} ({self.target.engine}) "
              f"in {time.perf_counter() - t0:.1f}s", flush=True)
        self.ready.set()
        self.on_status("ready")

    def _open(self, target):
        path = modelstore.model_file(target.model)
        if target.engine == "whispercpp":
            from .whispercpp import WhisperCppDecoder
            return WhisperCppDecoder(path, gpu=target.card.vulkan if target.device == "gpu" else None)
        from faster_whisper import WhisperModel

        from .fastdecode import FastDecoder
        compute = self.cfg.compute_type if target.device == "cuda" else "int8"
        return FastDecoder(WhisperModel(str(path), device=target.device, compute_type=compute), language="fa")

    def _step(self, d, start, end, final):
        """Decode d's audio [start, end) as the next piece of dictation d."""
        piece = Piece(start, end)
        before = list(d.pieces)
        d.pieces.append(piece)
        audio = trim_silence(d.samples(start, end))
        if self.model is None or audio is None or len(audio) < 0.2 * SR:
            return ""

        ctx = []  # with USE_CONTEXT: the pieces just before, heard with their text forced
        for p in reversed(before if USE_CONTEXT else []):
            if ctx and start - p.start > CONTEXT_S * SR:
                break
            if not ctx and p.end - p.start > MAX_PREV_PIECE_S * SR:
                break
            ctx.insert(0, p)
        context_text = " ".join(p.text for p in ctx if p.text)
        context_audio = d.samples(ctx[0].start, start) if ctx and context_text else None
        earlier = " ".join(p.text for p in before[:len(before) - len(ctx)] if p.text)
        earlier = earlier[-160:] if USE_PROMPT else ""
        prompt = " ".join(t for t in ("، ".join(self.cfg.vocabulary), earlier) if t)

        beam = self.cfg.final_beam_size if final and self.cfg.final_beam_size else self.cfg.beam_size
        if self.target and self.target.fast_decoding:
            beam = 1
        r = self.decoder.transcribe(audio, prompt or None, beam, fast=self.cfg.fast_context,
                                    context_audio=context_audio, context_text=context_text)
        self.last_mode = r.mode
        text = r.text
        if not text or is_hallucination(text):
            return ""
        if r.mode != "context" and r.no_speech_prob > 0.7 and r.avg_logprob < -1.0:
            return ""
        piece.text = text
        return text

    def release(self):
        """Free the model and its GPU memory (before another model is loaded)."""
        def free():
            import gc
            close = getattr(self.decoder, "close", None)
            if close:  # whisper.cpp: give the graphics memory back now
                close()
            self.model = self.decoder = None
            self.ready.clear()
            gc.collect()
        self._pool.submit(free).result()
        self._pool.shutdown(wait=False)

    def submit_step(self, d, start, end, final=False):
        return self._pool.submit(self._step, d, start, end, final)
