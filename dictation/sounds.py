"""Short, soft cue sounds, generated once into the temp folder."""
import os
import tempfile
import wave
import winsound

import numpy as np

SR = 44100


def _tone(notes, vol=0.16):
    """notes: list of (frequency, seconds). A soft sine with a warm overtone,
    gentle attack and a smooth decay, so the cue never clicks."""
    parts = []
    for freq, dur in notes:
        t = np.arange(int(SR * dur)) / SR
        sig = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
        env = np.minimum(1, t / 0.008) * np.exp(-t / (dur * 0.45))
        parts.append(sig * env)
    data = np.concatenate(parts) / 1.25 * vol
    return (data * 32767).astype(np.int16)


def _write(name, samples):
    path = os.path.join(tempfile.gettempdir(), f"mh_stt_{name}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())
    return path


class Sounds:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.files = {
            "start": _write("start", _tone([(784, 0.07), (1175, 0.11)])),
            "stop": _write("stop", _tone([(1047, 0.07), (784, 0.11)])),
            "done": _write("done", _tone([(1319, 0.09)], vol=0.10)),
            "error": _write("error", _tone([(330, 0.12), (262, 0.16)], vol=0.18)),
        }

    def play(self, name):
        if self.enabled and name in self.files:
            winsound.PlaySound(self.files[name],
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
