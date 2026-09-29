"""Persian orthography fixes for model output. Never changes words, only:
Arabic ي/ك → Persian ی/ک, Persian punctuation and spacing, the half-space
(ZWNJ) where it is unambiguous (می/نمی prefix, ها suffixes, ه + ای/ام/اند...,
a few common compounds), digits, and the user's own replacement list.
"""
import re
from functools import lru_cache
from .paths import ZWNJ_WORDS_PATH

ZWNJ = "‌"
# Persian/Arabic letters only (not the punctuation, digits or signs that share
# the Unicode block): ء–غ, ف–ي, ٔ, ٰ, پ, چ, ژ, ک, گ, ۀ, ی
FA = "ء-غف-ئٰپچژکگۀی"
FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

CHARS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک",
                       **{a: FA_DIGITS[i] for i, a in enumerate("٠١٢٣٤٥٦٧٨٩")}})

# Whisper's well-known inventions on silence/noise (learned from subtitled video)
HALLUCINATIONS = re.compile(
    r"زیرنویس|ترجمه (و|توسط)|امیدوارم (از )?این ویدیو|ممنون (که|از) (تماشا|دیدن)|"
    r"لایک (و|یادتون)|سابسکرایب|کانال ما|subtitles? by|amara\.org|thanks for watching",
    re.IGNORECASE,
)

_PREFIX_MI = re.compile(rf"(?<![{FA}{ZWNJ}])(ن?می) (?=[{FA}])")
# a suffix written as a separate word: joined only if the result is a known word,
# so the spoken filler «ها» (می‌گم ها) stays apart
_SPACED_SUFFIX = re.compile(
    rf"(?<![{FA}{ZWNJ}])([{FA}]+) (ها|های|هایی|هایم|هایت|هایش|هایمان|هایتان|هایشان"
    rf"|ای|ام|ات|اش|ایم|اید|اند)(?![{FA}])")

# Compounds the model writes joined or with a space; suffixes are kept (نرمافزاری → نرم‌افزاری)
COMPOUNDS = ("نرم‌افزار", "سخت‌افزار", "برنامه‌نویس", "وب‌سایت")
_COMPOUNDS = [(re.compile(rf"(?<![{FA}{ZWNJ}]){re.escape(c.split(ZWNJ)[0])} ?"
                          rf"{re.escape(c.split(ZWNJ)[1])}"), c) for c in COMPOUNDS]

# Words the model writes joined ("میگیریم", "دادهها", "بودجهی") get a half-space
# only at a real prefix/suffix boundary, and only if that spelling is a known word.
ZWNJ_WORDS = ZWNJ_WORDS_PATH
PREFIXES = ("نمی", "می")
HA_SUFFIXES = ("هایشان", "هایتان", "هایمان", "هایش", "هایت", "هایم", "هایی", "های", "ها")
HE_SUFFIXES = ("ایم", "اید", "اند", "ای", "ام", "ات", "اش", "ی")  # after a final ه


@lru_cache(maxsize=1)
def _zwnj_words():
    try:
        return frozenset(ZWNJ_WORDS.read_text(encoding="utf-8").split())
    except OSError:
        return frozenset()


def _join_fix(word: str) -> str:
    if len(word) < 4:
        return word
    known = _zwnj_words()
    for p in PREFIXES:
        if word.startswith(p) and p + ZWNJ + word[len(p):] in known:
            return p + ZWNJ + word[len(p):]
    cands = [word[:-len(suf)] + ZWNJ + suf
             for suf in HA_SUFFIXES + HE_SUFFIXES
             if word.endswith(suf) and len(word) - len(suf) >= 2
             and (suf in HA_SUFFIXES or word[:-len(suf)].endswith("ه"))
             and word[:-len(suf)] + ZWNJ + suf in known]
    # longest stem wins: خانهای → خانه‌ای rather than خان‌های
    return max(cands, key=lambda c: c.index(ZWNJ)) if cands else word


def preload():
    """Load the word list ahead of the first dictation (~0.5 s)."""
    _zwnj_words()


def _join_spaced(m) -> str:
    joined = m.group(1) + ZWNJ + m.group(2)
    return joined if joined in _zwnj_words() else m.group()


def is_hallucination(text: str) -> bool:
    return bool(HALLUCINATIONS.search(text))


def _fix_punct(text: str) -> str:
    text = re.sub(rf"(?<=[{FA}])\s*,", "،", text)
    text = re.sub(rf"(?<=[{FA}])\s*\?", "؟", text)
    text = re.sub(rf"(?<=[{FA}])\s*;", "؛", text)
    text = re.sub(r"\s+([،؛؟!:.)»])", r"\1", text)          # no space before
    text = re.sub(r"([،؛؟!:])(?=[^\s\d])", r"\1 ", text)      # one space after
    text = re.sub(rf"(?<=[{FA}])\.(?=[{FA}])", ". ", text)
    return text


def _fix_digits(text: str, mode: str) -> str:
    if mode == "persian":
        # whole number tokens (1402, 3.5, 12:30); leave Latin context alone:
        # v2, mp3, COVID-19, "Python 3.12"
        to_fa = str.maketrans("0123456789", FA_DIGITS)

        def repl(m):
            if re.search(r"[A-Za-z]\s*$", text[:m.start()]):
                return m.group()
            return m.group().translate(to_fa)
        return re.sub(r"(?<![\w\-/])\d+(?:[.:/]\d+)*(?![\w\-/])", repl, text)
    if mode == "latin":
        return text.translate(str.maketrans(FA_DIGITS, "0123456789"))
    return text


def fix(text: str, digits="persian", replacements=None) -> str:
    text = " ".join(text.translate(CHARS).split())
    text = _PREFIX_MI.sub(rf"\1{ZWNJ}", text)
    text = _SPACED_SUFFIX.sub(_join_spaced, text)
    for pattern, compound in _COMPOUNDS:
        text = pattern.sub(compound, text)
    # word by word, so a half-space already in a word doesn't block its other parts
    text = re.sub(rf"[{FA}]+", lambda m: _join_fix(m.group()), text)
    text = _fix_punct(text)
    text = _fix_digits(text, digits)
    for wrong, right in (replacements or {}).items():
        text = re.sub(rf"(?<![\w{ZWNJ}]){re.escape(wrong)}(?![\w{ZWNJ}])", right, text)
    return text.strip()
