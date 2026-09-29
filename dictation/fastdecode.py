"""Whisper decoding tuned for a small GPU.

1. Encoder context sized to the audio. Stock Whisper pads every input to 30 s,
   so a 5 s piece costs as much encoder time as a 30 s one (~2.6 s on a T500).
   Feeding only the real length (+ a short silence pad) is several times faster.

2. Decoding with context. A short piece decoded on its own is misheard far more
   often than the same words inside a longer stretch. So a piece can be decoded
   together with the audio just before it, with the decoder forced to start from
   that audio's already-known text: the model hears the context but only
   generates the new words.

Whenever a decode looks unhealthy (repetition loop, runaway length, very low
confidence, nothing new found) we fall back to the plain, stock-style decode.
"""
import zlib
from dataclasses import dataclass

import ctranslate2
import numpy as np
from faster_whisper.tokenizer import Tokenizer
from faster_whisper.transcribe import get_suppressed_tokens

SR = 16000
FULL_FRAMES = 3000   # 30 s of 10 ms mel frames
MAX_LENGTH = 440     # Whisper's decoder limit is 448 tokens
MAX_CONTEXT_S = 28.0


@dataclass
class Result:
    text: str
    avg_logprob: float
    no_speech_prob: float
    mode: str = "plain"  # "context", "plain" or "full" (30 s fallback)


def _compression_ratio(text: str) -> float:
    b = text.encode("utf-8")
    return len(b) / max(1, len(zlib.compress(b)))


def _plausible(text: str, seconds: float) -> bool:
    # Persian speech runs ≈ 12–18 characters per second
    return _compression_ratio(text) < 2.4 and len(text) < seconds * 40 + 20


class FastDecoder:
    def __init__(self, model, language="fa", pad_s=0.5):
        self.m = model
        self.pad = np.zeros(int(pad_s * SR), dtype=np.float32)
        self.tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                             task="transcribe", language=language)
        self.suppress = get_suppressed_tokens(self.tok, [-1])

    def _frames(self, samples, fast=True):
        if not fast:
            return FULL_FRAMES
        frames = min(FULL_FRAMES, int((samples / SR + len(self.pad) / SR) * 100))
        return frames - frames % 2

    def _encode(self, audio, frames):
        feats = self.m.feature_extractor(np.concatenate([audio, self.pad]))
        feats = feats[:, :frames]
        if feats.shape[1] < frames:  # standard path: pad the mel to 30 s
            feats = np.pad(feats, ((0, 0), (0, frames - feats.shape[1])),
                           constant_values=feats.min())
        sv = ctranslate2.StorageView.from_array(np.ascontiguousarray(feats[None], dtype=np.float32))
        return self.m.model.encode(sv, to_cpu=False)

    def _generate(self, enc, prompt_text, beam_size, forced_text=None):
        """Returns (new text, score, no_speech_prob, runaway). With forced_text the
        decoder starts from those tokens and only the continuation is returned."""
        prev = self.tok.encode(" " + prompt_text.strip())[-150:] if prompt_text else []
        prompt = self.m.get_prompt(self.tok, prev, without_timestamps=True)
        forced = self.tok.encode(" " + forced_text.strip()) if forced_text else []
        r = self.m.model.generate(enc, [prompt + forced], beam_size=beam_size,
                                  max_length=MAX_LENGTH, return_scores=True,
                                  return_no_speech_prob=True, suppress_blank=not forced,
                                  suppress_tokens=self.suppress)[0]
        ids = r.sequences_ids[0]
        if ids[:len(forced)] == forced:  # CT2 returns the forced tokens too
            ids = ids[len(forced):]
        runaway = len(prompt) + len(forced) + len(ids) >= MAX_LENGTH - 1
        # CT2's score is length-normalised, i.e. the average token log-prob
        return self.tok.decode(ids).strip(), r.scores[0], r.no_speech_prob, runaway

    def _with_context(self, audio, prompt_text, beam_size, context_audio, context_text):
        both = np.concatenate([context_audio, audio])
        if len(both) > MAX_CONTEXT_S * SR:
            return None
        enc = self._encode(both, self._frames(len(both)))
        text, score, nsp, runaway = self._generate(enc, prompt_text, beam_size, context_text)
        if not text or runaway or score < -1.0 or not _plausible(text, len(audio) / SR):
            return None
        return Result(text, score, nsp, mode="context")

    def transcribe(self, audio: np.ndarray, prompt_text=None, beam_size=5, fast=True,
                   context_audio=None, context_text=None) -> Result:
        """Transcribe `audio`. `prompt_text` is earlier text (style/vocabulary hint).
        With `context_audio` + its known `context_text`, the model also hears the
        speech just before `audio` and returns only the words for `audio`."""
        if context_text and context_audio is not None and len(context_audio):
            r = self._with_context(audio, prompt_text, beam_size, context_audio, context_text)
            if r is not None:
                return r
            prompt_text = f"{prompt_text or ''} {context_text}".strip()

        frames = self._frames(len(audio), fast)
        if frames < FULL_FRAMES:
            text, score, nsp, runaway = self._generate(self._encode(audio, frames),
                                                        prompt_text, beam_size)
            if not runaway and score > -1.0 and _plausible(text, len(audio) / SR):
                return Result(text, score, nsp)
        text, score, nsp, _ = self._generate(self._encode(audio, FULL_FRAMES), prompt_text, beam_size)
        return Result(text, score, nsp, mode="full")
