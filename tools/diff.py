"""Show word-level differences between reference transcripts and model outputs,
ignoring orthography (spaces vs نیم‌فاصله, ی/ي, punctuation, diacritics).

Usage: .venv/Scripts/python tools/diff.py bench_results/<model>_<mode>.json [...]
"""
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")
from benchmark import normalize  # noqa: E402


def words(text):
    # join everything, then re-split on the reference's spacing is impossible;
    # instead compare word lists after removing intra-word spaces variance by
    # normalising and treating "X Y" == "XY" through a character-level check
    return normalize(text).split()


def diff(ref, hyp):
    r, h = words(ref), words(hyp)
    sm = difflib.SequenceMatcher(a=r, b=h, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a, b = " ".join(r[i1:i2]), " ".join(h[j1:j2])
        if a.replace(" ", "") == b.replace(" ", ""):
            continue  # only spacing differs (نرم افزار / نرمافزار)
        out.append(f"{a or '∅'}  →  {b or '∅'}")
    return out


def main():
    for path in sys.argv[1:]:
        outputs = json.loads(Path(path).read_text(encoding="utf-8"))
        print(f"=== {Path(path).stem}")
        total = 0
        for name, hyp in outputs.items():
            ref_path = ROOT / "samples" / Path(name).with_suffix(".txt")
            if not ref_path.exists():
                continue
            errs = diff(ref_path.read_text(encoding="utf-8-sig"), hyp)
            total += len(errs)
            print(f"  {name}: {len(errs)} real differences")
            for e in errs:
                print(f"     {e}")
        print(f"  total: {total}")


if __name__ == "__main__":
    main()
