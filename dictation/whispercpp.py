"""The whisper.cpp engine: runs the GGML model on any graphics card through
Vulkan (AMD, Intel or NVIDIA) or on the CPU, via ctypes bindings to whisper.dll.

The DLLs are built by tools/build_whispercpp.py (whisper.cpp with GGML_VULKAN
and dynamically loaded backends) and live in paths.WHISPERCPP_DIR. Decoding
mirrors fastdecode.FastDecoder: the encoder only sees the real audio length
(+0.5 s, rounded up for flash attention), the previous text is the prompt, and
an implausible result is decoded again with the full 30 s window.

Measured on the user's voice through Vulkan on a T500: nearly the same words as
CTranslate2 (WER 11.3% vs 10.9%) at 0.39 s per second of audio (CTranslate2 on
CUDA: 0.30). On the CPU it is 2.4x slower than CTranslate2, so devices.py only
uses it there when the CTranslate2 model is missing.
"""
import ctypes as C
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fastdecode import FULL_FRAMES, SR, Result, plausible

GREEDY, BEAM_SEARCH = 0, 1
DEV_GPU, DEV_IGPU = 1, 2
PROMPT_TOKENS = 150  # same as FastDecoder: the last 150 tokens of earlier text
FA_PAD = 256         # whisper.cpp's flash-attention padding (GGML_PAD(n_ctx, 256))
TOKENS_PER_S = 15    # at most this many tokens per second of audio (+10): Persian speech
                     # is ≈ 7/s, and a repetition loop on noise then stops early instead of
                     # running to whisper.cpp's 220-token limit (14 s on a T500)

LOG_CB = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_void_p)
READ_CB = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_void_p, C.c_size_t)
EOF_CB = C.CFUNCTYPE(C.c_bool, C.c_void_p)
CLOSE_CB = C.CFUNCTYPE(None, C.c_void_p)


class ContextParams(C.Structure):
    _fields_ = [("use_gpu", C.c_bool), ("flash_attn", C.c_bool), ("gpu_device", C.c_int),
                ("dtw_token_timestamps", C.c_bool), ("dtw_aheads_preset", C.c_int),
                ("dtw_n_top", C.c_int), ("dtw_aheads_n_heads", C.c_size_t),
                ("dtw_aheads_heads", C.c_void_p), ("dtw_mem_size", C.c_size_t)]


class FullParams(C.Structure):
    """whisper_full_params of whisper.cpp v1.9.4 (nested structs flattened; same layout)."""
    _fields_ = [
        ("strategy", C.c_int), ("n_threads", C.c_int), ("n_max_text_ctx", C.c_int),
        ("offset_ms", C.c_int), ("duration_ms", C.c_int),
        ("translate", C.c_bool), ("no_context", C.c_bool), ("no_timestamps", C.c_bool),
        ("single_segment", C.c_bool), ("print_special", C.c_bool), ("print_progress", C.c_bool),
        ("print_realtime", C.c_bool), ("print_timestamps", C.c_bool),
        ("token_timestamps", C.c_bool), ("thold_pt", C.c_float), ("thold_ptsum", C.c_float),
        ("max_len", C.c_int), ("split_on_word", C.c_bool), ("max_tokens", C.c_int),
        ("debug_mode", C.c_bool), ("audio_ctx", C.c_int), ("tdrz_enable", C.c_bool),
        ("suppress_regex", C.c_char_p), ("initial_prompt", C.c_char_p),
        ("carry_initial_prompt", C.c_bool), ("prompt_tokens", C.POINTER(C.c_int32)),
        ("prompt_n_tokens", C.c_int), ("language", C.c_char_p), ("detect_language", C.c_bool),
        ("suppress_blank", C.c_bool), ("suppress_nst", C.c_bool),
        ("temperature", C.c_float), ("max_initial_ts", C.c_float), ("length_penalty", C.c_float),
        ("temperature_inc", C.c_float), ("entropy_thold", C.c_float),
        ("logprob_thold", C.c_float), ("no_speech_thold", C.c_float),
        ("greedy_best_of", C.c_int), ("beam_size", C.c_int), ("beam_patience", C.c_float),
        ("new_segment_callback", C.c_void_p), ("new_segment_callback_user_data", C.c_void_p),
        ("progress_callback", C.c_void_p), ("progress_callback_user_data", C.c_void_p),
        ("encoder_begin_callback", C.c_void_p), ("encoder_begin_callback_user_data", C.c_void_p),
        ("abort_callback", C.c_void_p), ("abort_callback_user_data", C.c_void_p),
        ("logits_filter_callback", C.c_void_p), ("logits_filter_callback_user_data", C.c_void_p),
        ("grammar_rules", C.c_void_p), ("n_grammar_rules", C.c_size_t), ("i_start_rule", C.c_size_t),
        ("grammar_penalty", C.c_float),
        ("vad", C.c_bool), ("vad_model_path", C.c_char_p),
        ("vad_threshold", C.c_float), ("vad_min_speech_duration_ms", C.c_int),
        ("vad_min_silence_duration_ms", C.c_int), ("vad_max_speech_duration_s", C.c_float),
        ("vad_speech_pad_ms", C.c_int), ("vad_samples_overlap", C.c_float),
    ]


class TokenData(C.Structure):
    _fields_ = [("id", C.c_int32), ("tid", C.c_int32), ("p", C.c_float), ("plog", C.c_float),
                ("pt", C.c_float), ("ptsum", C.c_float), ("t0", C.c_int64), ("t1", C.c_int64),
                ("t_dtw", C.c_int64), ("vlen", C.c_float)]


class ModelLoader(C.Structure):
    _fields_ = [("context", C.c_void_p), ("read", READ_CB), ("eof", EOF_CB), ("close", CLOSE_CB)]


@dataclass
class Gpu:
    index: int          # whisper_context_params.gpu_device
    name: str
    integrated: bool
    memory_mb: int


def _log(level, text, _user):
    """whisper.cpp/ggml log lines: keep warnings, errors and which device is used."""
    line = (text or b"").decode("utf-8", "replace").rstrip()
    if line and (level in (3, 4) or line.startswith(("ggml_vulkan: ", "whisper_backend_init_gpu: using"))):
        print(f"[whisper.cpp] {line}", flush=True)


class _Lib:
    def __init__(self, dll_dir: Path):
        self.dir = Path(dll_dir)
        # the DLLs' folder, and the one above it: the installed app keeps its own C++
        # runtime (msvcp140.dll, ...) there, for PCs without the VC++ redistributable
        for d in (self.dir, self.dir.parent):
            os.add_dll_directory(str(d))
        self.dlls = [C.CDLL(str(self.dir / n)) for n in ("whisper.dll", "ggml.dll", "ggml-base.dll")]
        self._log_cb = LOG_CB(_log)  # keep a reference: C holds the pointer
        self.fn("ggml_log_set", None, LOG_CB, C.c_void_p)(self._log_cb, None)
        self.fn("whisper_log_set", None, LOG_CB, C.c_void_p)(self._log_cb, None)
        self.fn("ggml_backend_load_all_from_path", None, C.c_char_p)(str(self.dir).encode("utf-8"))

        self.dev_count = self.fn("ggml_backend_dev_count", C.c_size_t)
        self.dev_get = self.fn("ggml_backend_dev_get", C.c_void_p, C.c_size_t)
        self.dev_type = self.fn("ggml_backend_dev_type", C.c_int, C.c_void_p)
        self.dev_description = self.fn("ggml_backend_dev_description", C.c_char_p, C.c_void_p)
        self.dev_memory = self.fn("ggml_backend_dev_memory", None, C.c_void_p,
                                  C.POINTER(C.c_size_t), C.POINTER(C.c_size_t))
        self.context_default_params = self.fn("whisper_context_default_params", ContextParams)
        self.init_with_params = self.fn("whisper_init_with_params", C.c_void_p,
                                        C.POINTER(ModelLoader), ContextParams)
        self.free = self.fn("whisper_free", None, C.c_void_p)
        self.full_default_params = self.fn("whisper_full_default_params", FullParams, C.c_int)
        self.full = self.fn("whisper_full", C.c_int, C.c_void_p, FullParams,
                            C.POINTER(C.c_float), C.c_int)
        self.n_segments = self.fn("whisper_full_n_segments", C.c_int, C.c_void_p)
        self.segment_text = self.fn("whisper_full_get_segment_text", C.c_char_p, C.c_void_p, C.c_int)
        self.no_speech_prob = self.fn("whisper_full_get_segment_no_speech_prob", C.c_float,
                                      C.c_void_p, C.c_int)
        self.n_tokens = self.fn("whisper_full_n_tokens", C.c_int, C.c_void_p, C.c_int)
        self.token_data = self.fn("whisper_full_get_token_data", TokenData, C.c_void_p, C.c_int, C.c_int)
        self.token_eot = self.fn("whisper_token_eot", C.c_int32, C.c_void_p)
        self.n_text_ctx = self.fn("whisper_n_text_ctx", C.c_int, C.c_void_p)
        self.tokenize = self.fn("whisper_tokenize", C.c_int, C.c_void_p, C.c_char_p,
                                C.POINTER(C.c_int32), C.c_int)
        self._check_layout()

    def fn(self, name, restype, *argtypes):
        for dll in self.dlls:
            f = getattr(dll, name, None)
            if f is not None:
                f.restype, f.argtypes = restype, list(argtypes)
                return f
        raise AttributeError(f"{name} not found in {self.dir}")

    def _check_layout(self):
        """Our struct mirrors must match the DLL's: compare the known defaults,
        up to the last field. A mismatch would corrupt memory, so refuse to run."""
        p = self.full_default_params(BEAM_SEARCH)
        c = self.context_default_params()
        ok = (p.strategy == BEAM_SEARCH and p.n_max_text_ctx == 16384 and p.no_context
              and abs(p.thold_pt - 0.01) < 1e-6 and p.max_initial_ts == 1.0
              and abs(p.entropy_thold - 2.4) < 1e-6 and p.logprob_thold == -1.0
              and p.greedy_best_of == -1 and p.beam_size == 5 and p.beam_patience == -1.0
              and p.grammar_penalty == 100.0 and p.vad_threshold == 0.5
              and p.vad_min_speech_duration_ms == 250 and p.vad_min_silence_duration_ms == 100
              and p.vad_speech_pad_ms == 30 and abs(p.vad_samples_overlap - 0.1) < 1e-6
              and c.use_gpu and c.gpu_device == 0)
        if not ok:
            raise RuntimeError("whisper.cpp DLLs do not match this app's bindings")

    def gpus(self) -> list[Gpu]:
        """Graphics cards in the order whisper_context_params.gpu_device counts them."""
        found = []
        for i in range(self.dev_count()):
            dev = self.dev_get(i)
            kind = self.dev_type(dev)
            if kind not in (DEV_GPU, DEV_IGPU):
                continue
            free, total = C.c_size_t(), C.c_size_t()
            self.dev_memory(dev, C.byref(free), C.byref(total))
            name = (self.dev_description(dev) or b"").decode("utf-8", "replace").strip()
            found.append(Gpu(len(found), name, kind == DEV_IGPU, total.value // (1 << 20)))
        return found


_lib = None
_lib_lock = threading.Lock()


def library(dll_dir=None) -> _Lib:
    global _lib
    with _lib_lock:  # the engine thread and the UI may both ask first
        if _lib is None:
            from .paths import WHISPERCPP_DIR
            _lib = _Lib(dll_dir or WHISPERCPP_DIR)
        return _lib


def available() -> bool:
    from .paths import WHISPERCPP_DIR
    return (WHISPERCPP_DIR / "whisper.dll").exists()


def gpus() -> list[Gpu]:
    """Graphics cards whisper.cpp can use; empty when the DLLs or Vulkan are missing."""
    try:
        return library().gpus() if available() else []
    except Exception as e:  # no Vulkan driver, missing DLL, ...
        print(f"[whisper.cpp] no graphics cards: {e}", flush=True)
        return []


class WhisperCppDecoder:
    """Same interface as fastdecode.FastDecoder, on whisper.cpp."""

    def __init__(self, model_path, gpu: int | None = None, language="fa", pad_s=0.5, threads=None,
                 flash_attn=True):
        self.lib = library()
        self.language = language.encode()
        self.pad = np.zeros(int(pad_s * SR), dtype=np.float32)
        self.threads = threads or max(1, min(8, (os.cpu_count() or 2) // 2))
        cp = self.lib.context_default_params()
        cp.use_gpu = gpu is not None
        cp.gpu_device = gpu or 0
        cp.flash_attn = self.flash_attn = flash_attn
        self.ctx = self._load(Path(model_path), cp)
        self.eot = self.lib.token_eot(self.ctx)
        self.max_tokens = self.lib.n_text_ctx(self.ctx) // 2 - 4  # whisper.cpp's decode limit

    def _load(self, path, cp):
        """Read the model through Python, so non-ASCII paths (e.g. a Persian
        Windows user name) work; whisper.cpp's own fopen can't open those."""
        f = path.open("rb")
        size = path.stat().st_size

        def read(_ctx, out, n):
            return f.readinto((C.c_char * n).from_address(out))

        def eof(_ctx):
            return f.tell() >= size

        def close(_ctx):
            pass

        loader = ModelLoader(None, READ_CB(read), EOF_CB(eof), CLOSE_CB(close))
        try:
            ctx = self.lib.init_with_params(C.byref(loader), cp)
        finally:
            f.close()
        if not ctx:
            raise RuntimeError(f"whisper.cpp could not load {path.name}")
        return ctx

    def close(self):
        if self.ctx:
            self.lib.free(self.ctx)
            self.ctx = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _prompt(self, text):
        if not text:
            return None
        encoded = (" " + text.strip()).encode("utf-8")
        buf = (C.c_int32 * 1024)()
        n = self.lib.tokenize(self.ctx, encoded, buf, len(buf))
        if n < 0:  # longer than the buffer: -n tokens needed
            buf = (C.c_int32 * -n)()
            n = self.lib.tokenize(self.ctx, encoded, buf, len(buf))
        keep = buf[max(0, n - PROMPT_TOKENS):n]
        return (C.c_int32 * len(keep))(*keep) if keep else None

    def _run(self, samples, prompt, beam_size, audio_ctx, max_tokens):
        """One deterministic decode -> (text, avg log-prob, no-speech prob, runaway)."""
        p = self.lib.full_default_params(BEAM_SEARCH if beam_size > 1 else GREEDY)
        p.n_threads = self.threads
        p.no_context = p.no_timestamps = p.single_segment = True
        p.print_progress = p.print_timestamps = p.print_realtime = p.print_special = False
        p.language, p.detect_language = self.language, False
        p.suppress_blank = p.suppress_nst = True
        p.temperature, p.temperature_inc = 0.0, 0.0  # no sampling fallback
        p.beam_size, p.greedy_best_of = max(1, beam_size), 1
        p.audio_ctx = audio_ctx
        p.max_tokens = max_tokens = min(max_tokens, self.max_tokens)
        if prompt is not None:
            p.prompt_tokens, p.prompt_n_tokens = C.cast(prompt, C.POINTER(C.c_int32)), len(prompt)
        ptr = samples.ctypes.data_as(C.POINTER(C.c_float))
        if self.lib.full(self.ctx, p, ptr, len(samples)) != 0:
            raise RuntimeError("whisper.cpp decoding failed")
        text, logprobs, n_tok = [], [], 0
        segments = self.lib.n_segments(self.ctx)
        for s in range(segments):
            text.append((self.lib.segment_text(self.ctx, s) or b"").decode("utf-8", "replace"))
            for t in range(self.lib.n_tokens(self.ctx, s)):
                td = self.lib.token_data(self.ctx, s, t)
                if td.id < self.eot:
                    logprobs.append(td.plog)
                    n_tok += 1
        nsp = self.lib.no_speech_prob(self.ctx, 0) if segments else 1.0
        score = float(np.mean(logprobs)) if logprobs else -10.0
        return "".join(text).strip(), score, nsp, n_tok >= max_tokens - 1

    def warm_up(self):
        """A first tiny decode, so GPU buffers are set up before the first dictation
        and a card that can't run the model fails now. (Silence would make the model
        repeat itself up to the token limit, hence max 4 tokens.)"""
        samples = np.zeros(SR + len(self.pad), dtype=np.float32)
        self._run(samples, None, 1, self._audio_ctx(int(len(samples) / SR * 100)), 4)

    def transcribe(self, audio: np.ndarray, prompt_text=None, beam_size=5, fast=True,
                   context_audio=None, context_text=None) -> Result:
        """Transcribe `audio`; `prompt_text` is earlier text. Context decoding
        (engine.USE_CONTEXT) is not supported here: its text joins the prompt."""
        if context_text:
            prompt_text = f"{prompt_text or ''} {context_text}".strip()
        samples = np.ascontiguousarray(np.concatenate([audio, self.pad]), dtype=np.float32)
        prompt = self._prompt(prompt_text)
        max_tokens = int(len(audio) / SR * TOKENS_PER_S) + 10
        audio_ctx = self._audio_ctx(int(len(samples) / SR * 100)) if fast else 0
        if audio_ctx:
            text, score, nsp, runaway = self._run(samples, prompt, beam_size, audio_ctx, max_tokens)
            if not runaway and score > -1.0 and plausible(text, len(audio) / SR):
                return Result(text, score, nsp)
        text, score, nsp, _ = self._run(samples, prompt, beam_size, 0, max_tokens)  # the full 30 s window
        return Result(text, score, nsp, mode="full")

    def _audio_ctx(self, frames):
        """Encoder positions for `frames` mel frames, 0 for the full window.
        With flash attention whisper.cpp pads the attended positions to a multiple
        of 256 without masking them, so the padding would hold stale data from an
        earlier piece (measured: twice the word errors). Rounding up instead lets
        the encoder hear a little more of the silence after the audio."""
        n = frames // 2
        if self.flash_attn:
            n = -(-n // FA_PAD) * FA_PAD
        return n if n < FULL_FRAMES // 2 else 0
