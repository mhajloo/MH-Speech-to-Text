"""Microphone capture and live, piece-by-piece decoding.

The Recorder keeps a short ring buffer of audio from before the hotkey press, so
the first syllable is never cut off. A Session collects audio while the key is
held and, whenever the speaker pauses and the GPU is free, hands the next piece
to the engine, so a 2-minute dictation is transcribed by the time the key is
released except for its last few words.
"""
import collections
import ctypes
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from faster_whisper.vad import VadOptions, get_speech_timestamps

SR = 16000
BLOCK = 800  # 50 ms

# Speech is decoded piece by piece while the key is held, so at release only
# the part after the last piece is left. Whisper is most accurate on long
# stretches, so pieces are long unless the speaker clearly pauses.
# Tuned on the user's own recordings (tools/benchmark.py): pieces under ~6 s
# cost accuracy; longer ones leave more to decode after release.
FIRST_STEP_S = 3.0    # no piece shorter than this until some text exists
MIN_STEP_S = 6.0      # an ordinary pause only ends a piece at least this long
END_PAUSE_S = 0.7     # a pause this long at the live edge (end of a sentence) ...
END_PAUSE_MIN_S = 3.0  # ... ends a piece at least this long
MAX_STEP_S = 12.0     # cut somewhere before undecoded audio grows past this
SAFE_TAIL_S = 0.3     # never cut this close to the live edge
# Pause needed to end a piece, by the length of the piece it would end
GAP_SCHEDULE = ((8.0, 0.18), (0.0, 0.30))
CONTEXT_S = 8.0       # context decoding (engine.USE_CONTEXT): audio heard before a piece


class MicError(Exception):
    """The microphone could not be opened (unplugged, busy, or access denied)."""


# Keeping a Bluetooth headset's microphone open switches the headset to its
# low-quality "hands-free" mode for as long as the app runs, so those devices
# are only opened while dictating.
BLUETOOTH_HINTS = ("bluetooth", "hands-free", "handsfree", "headset", "airpods", "buds", " bt")


def is_bluetooth(name) -> bool:
    n = f" {(name or '').lower()}"
    return any(h in n for h in BLUETOOTH_HINTS)


def _mme():
    """MME is the Windows audio API that converts any microphone to 16 kHz for us."""
    for i, api in enumerate(sd.query_hostapis()):
        if api["name"] == "MME":
            return i, api
    return None, None


def input_devices():
    """Names of the microphones Windows currently offers."""
    idx, _ = _mme()
    return [d["name"] for d in sd.query_devices()
            if d["hostapi"] == idx and d["max_input_channels"] > 0
            and "sound mapper" not in d["name"].lower()]


def default_input_name():
    idx, api = _mme()
    if api is None or api["default_input_device"] < 0:
        return None
    return sd.query_devices(api["default_input_device"])["name"]


class _WAVEINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
                ("dwFormats", wintypes.DWORD), ("wChannels", wintypes.WORD),
                ("wReserved1", wintypes.WORD)]


def _device_signature():
    """(number of microphones, Windows' preferred one), read straight from the
    OS: PortAudio's own list only changes after re-initialising it."""
    try:
        winmm = ctypes.windll.winmm
        winmm.waveInMessage.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
        count = winmm.waveInGetNumDevs()
        dev, flags = wintypes.DWORD(), wintypes.DWORD()
        winmm.waveInMessage(ctypes.c_void_p(0xFFFFFFFF), 0x2015,  # WAVE_MAPPER, DRVM_MAPPER_PREFERRED_GET
                            ctypes.byref(dev), ctypes.byref(flags))
        caps = _WAVEINCAPSW()
        winmm.waveInGetDevCapsW(dev.value, ctypes.byref(caps), ctypes.sizeof(caps))
        return count, caps.szPname
    except Exception:
        return None


class Recorder:
    """The microphone. Kept open (with a short pre-roll buffer) when allowed, so
    dictation starts instantly; re-opened automatically when devices change."""

    def __init__(self, device_name=None, preroll_ms=400, keep_open=True, on_devices_changed=None):
        self.device_name = device_name      # None = Windows default
        self.want_open = keep_open
        self.on_devices_changed = on_devices_changed
        self.active_name = None
        self.error = None
        self.level = 0.0
        self._ring = collections.deque(maxlen=max(1, preroll_ms * SR // 1000 // BLOCK))
        self._sink = None
        self._buf_lock = threading.Lock()   # ring/sink, shared with the audio callback
        self._lock = threading.RLock()      # the stream itself
        self._stream = None
        self._dirty = False                 # devices changed while dictating
        self._monitoring = False            # a level meter is on screen
        self._signature = _device_signature()
        self._stop = threading.Event()
        if self.keep_open:
            self._try_open()
        threading.Thread(target=self._watch, name="mic-watch", daemon=True).start()

    @property
    def keep_open(self) -> bool:
        name = self.device_name or default_input_name()
        return self.want_open and not is_bluetooth(name)

    @property
    def capturing(self) -> bool:
        return self._sink is not None

    # --- stream management ---
    def _resolve(self):
        idx, api = _mme()
        if self.device_name:
            for i, d in enumerate(sd.query_devices()):
                if d["hostapi"] == idx and d["max_input_channels"] > 0 and d["name"] == self.device_name:
                    return i, d["name"]
        if api is None or api["default_input_device"] < 0:
            raise MicError("no microphone")
        i = api["default_input_device"]
        return i, sd.query_devices(i)["name"]

    def _open(self):
        with self._lock:
            index, name = self._resolve()
            stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK,
                                    device=index, callback=self._callback)
            stream.start()
            self._stream, self.active_name, self.error = stream, name, None

    def _try_open(self):
        try:
            self._open()
        except Exception as e:
            self.error = str(e)
            print(f"[mic] cannot open: {e}", flush=True)

    def _close(self):
        with self._lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def reopen(self):
        """Re-read the device list and open the chosen microphone again."""
        with self._lock:
            self._close()
            try:  # PortAudio only sees new/removed devices after re-initialising
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
            if self.keep_open or self._monitoring:
                self._try_open()

    def monitor(self, on: bool):
        """Keep the microphone open while a level meter is on screen."""
        self._monitoring = on
        if on and self._stream is None:
            self._try_open()
        elif not on and not self.keep_open and not self.capturing:
            self._close()

    def configure(self, device_name=None, keep_open=True):
        self.device_name, self.want_open = device_name, keep_open
        if not self.capturing:
            self.reopen()

    def _callback(self, indata, frames, t, status):
        block = indata[:, 0].copy()
        self.level = float(np.sqrt(np.mean(block * block)))
        with self._buf_lock:
            if self._sink is not None:
                self._sink.append(block)
            else:
                self._ring.append(block)

    def _watch(self):
        while not self._stop.wait(2.0):
            sig = _device_signature()
            if sig is None or sig == self._signature:
                continue
            self._signature = sig
            print(f"[mic] devices changed: {sig}", flush=True)
            if self.capturing:
                self._dirty = True
            else:
                self.reopen()
            if self.on_devices_changed:
                self.on_devices_changed()

    # --- dictation ---
    def start_capture(self) -> list:
        """Start collecting; returns the live list that blocks get appended to."""
        with self._lock:
            if self._stream is None or not self._stream.active:
                if self._stream is not None:  # died (unplugged?): refresh devices first
                    self.reopen()
                if self._stream is None:
                    try:
                        self._open()
                    except Exception as e:
                        self.error = str(e)
                        raise MicError(str(e)) from e
        with self._buf_lock:
            self._sink = list(self._ring)
            self._ring.clear()
            return self._sink

    def stop_capture(self):
        with self._buf_lock:
            self._sink = None
        self.level = 0.0
        if self._dirty:
            self._dirty = False
            self.reopen()
        elif not self.keep_open and not self._monitoring:
            self._close()

    def close(self):
        self._stop.set()
        self._close()


def _vad(audio, min_silence_ms):
    # no padding: padding shrinks every pause and hides real cut points;
    # callers add their own margins
    opts = VadOptions(min_silence_duration_ms=min_silence_ms, speech_pad_ms=0)
    return get_speech_timestamps(audio, opts)


def _required_gap(piece_s):
    for at_least, gap in GAP_SCHEDULE:
        if piece_s >= at_least:
            return gap
    return GAP_SCHEDULE[-1][1]


def plan_step(new: np.ndarray, first: bool):
    """Where to end the next piece of the not-yet-decoded audio `new`: None =
    keep listening, else an index into `new`.

    Pieces end inside pauses so no word is ever split. The session only asks
    when the GPU is idle, so on a busy GPU pieces simply grow longer.
    """
    n = len(new)
    min_piece = max(MIN_STEP_S, FIRST_STEP_S if first else 0) * SR
    min_end_piece = max(END_PAUSE_MIN_S, FIRST_STEP_S if first else 0) * SR
    if n < min(min_piece, min_end_piece):
        return None
    speech = _vad(new, 100)
    if not speech:  # only silence: hand it over (the engine skips it) to keep up
        return n - int(0.5 * SR) if n >= 2 * SR else None
    last_end = speech[-1]["end"]
    limit = n - SAFE_TAIL_S * SR

    # 1. a clear pause at the live edge (end of a sentence): take what was said
    if n - last_end >= END_PAUSE_S * SR and last_end >= min_end_piece:
        return min(n, last_end + int(0.2 * SR))
    # 2. the latest pause long enough for the piece it would end
    for a, b in reversed(list(zip(speech, speech[1:]))):
        mid = (a["end"] + b["start"]) // 2
        if (min_piece <= mid <= limit
                and b["start"] - a["end"] >= _required_gap(mid / SR) * SR):
            return int(mid)
    # 3. too long without a usable pause: cut at the longest one there is
    if n >= MAX_STEP_S * SR:
        gaps = [(b["start"] - a["end"], (a["end"] + b["start"]) // 2)
                for a, b in zip(speech, speech[1:])]
        return int(max(gaps)[1]) if gaps else int(limit)
    return None


def trim_silence(audio: np.ndarray, keep_s=0.25):
    """Crop leading/trailing non-speech; Whisper invents words in silence.
    Returns None if there is no speech at all."""
    speech = _vad(audio, 300)
    if not speech:
        return None
    pad = int(keep_s * SR)
    return audio[max(0, speech[0]["start"] - pad):speech[-1]["end"] + pad]


@dataclass
class Piece:
    start: int  # sample range in the dictation
    end: int
    text: str = ""


class Dictation:
    """The audio of one dictation and the pieces of text decoded from it so far.
    Audio is only appended, so ranges handed to the engine never change."""

    def __init__(self):
        self._buf = np.zeros(30 * SR, dtype=np.float32)
        self.n = 0          # samples recorded
        self.done = 0       # samples before this were handed to the engine
        self.pieces = []    # appended in order by the engine

    def append(self, block):
        if self.n + len(block) > len(self._buf):
            grown = np.zeros(max(2 * len(self._buf), self.n + len(block)), dtype=np.float32)
            grown[:self.n] = self._buf[:self.n]
            self._buf = grown
        self._buf[self.n:self.n + len(block)] = block
        self.n += len(block)

    def samples(self, start, end) -> np.ndarray:
        return self._buf[start:end].copy()

    def undecoded(self) -> np.ndarray:
        return self._buf[self.done:self.n]

    def has_text(self) -> bool:
        return any(p.text for p in self.pieces)

    def text(self) -> str:
        return " ".join(p.text for p in self.pieces if p.text)


class Session:
    """One press-hold-release of the hotkey."""

    def __init__(self, recorder: Recorder, engine, tail_ms=250):
        self.recorder = recorder
        self.engine = engine
        self.tail_ms = tail_ms
        self.started = time.monotonic()
        self.frames = recorder.start_capture()
        self.consumed = 0
        self.d = Dictation()
        self.futures = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="segmenter", daemon=True)
        self._thread.start()

    def _pull(self):
        n = len(self.frames)
        for block in self.frames[self.consumed:n]:
            self.d.append(block)
        self.consumed = n

    def _submit(self, end, final=False):
        self.futures.append(self.engine.submit_step(self.d, self.d.done, end, final))
        self.d.done = end

    def _loop(self):
        while not self._stop.wait(0.25):
            self._pull()
            if self.futures and not self.futures[-1].done():
                continue  # GPU busy: the next piece just grows
            cut = plan_step(self.d.undecoded(), first=not self.d.has_text())
            if cut:
                self._submit(self.d.done + cut)

    def held_ms(self) -> float:
        return (time.monotonic() - self.started) * 1000

    def finish(self) -> str:
        time.sleep(self.tail_ms / 1000)  # catch the end of the last word
        self._stop.set()
        self._thread.join()
        self.recorder.stop_capture()
        self._pull()
        if self.d.n - self.d.done > 0.3 * SR:
            self._submit(self.d.n, final=True)
        for f in self.futures:
            f.result()
        return self.d.text()

    def cancel(self):
        self._stop.set()
        self.recorder.stop_capture()
        for f in self.futures:
            f.cancel()
