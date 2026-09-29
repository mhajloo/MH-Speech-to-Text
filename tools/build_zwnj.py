"""Build assets/data/zwnj_words.txt, the list of known half-space (ZWNJ)
spellings that textfix uses, from permissively licensed sources only:

- Common Voice Persian sentences (CC0): the spellings real text uses, and which
  joined spellings are genuine words (ماهی، تنها، توجهی) and must stay joined.
- Hazm word and verb lists (MIT, Roshan): noun/adjective lemmas and verb stems,
  from which inflected forms the sentences don't contain are generated
  (plural ‌ها, ezafe/indefinite after a silent ه, می‌/نمی‌ verbs, perfect ‌اند).

Downloads into build_cache/ (not shipped). Usage:
    .venv/Scripts/python tools/build_zwnj.py
"""
import collections
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "build_cache"
OUT = ROOT / "assets" / "data" / "zwnj_words.txt"

CV_URL = "https://raw.githubusercontent.com/common-voice/common-voice/main/server/data/fa/{}"
CV_FILES = ["sentence-collector.txt"] + [f"sentences{i:02d}.txt" for i in range(1, 21)]
HAZM_URL = "https://raw.githubusercontent.com/roshan-research/hazm/master/hazm/data/{}"

Z = "‌"
LETTERS = "ء-غف-يپچژکگی"
TOKEN = re.compile(f"[{LETTERS}{Z}]+")

HA = ["ها", "های", "هایی", "هایم", "هایت", "هایش", "هایمان", "هایتان", "هایشان"]
AFTER_SILENT_HE = ["ی", "ای", "ام", "ات", "اش", "ایم", "اید", "اند"] + HA
PRESENT_END = ["م", "ی", "د", "یم", "ید", "ند", "ه", "ن", "ین"]   # formal + colloquial
PAST_END = ["م", "ی", "", "یم", "ید", "ند", "ن", "ین"]
CLITICS = ["", "ش", "ت", "م", "مون", "تون", "شون"]
PERFECT_END = ["ام", "ای", "ایم", "اید", "اند"]
# spoken present stems that differ from the written ones (می‌خوام، می‌گم، می‌شه...)
COLLOQUIAL_STEMS = ["خوا", "تون", "دون", "گ", "ر", "ش", "د", "ذار", "آ", "ی", "بر", "کن",
                    "زن", "بین", "گیر", "خور", "کش", "شین", "مون", "رس", "گرد", "پرس"]
# nouns whose final ه is pronounced (h), so suffixes join directly: توجهی، فقهی
CONSONANTAL_HE = {"توجه", "تنبه", "تفقه", "تشبه", "تشابه", "تنزه", "فقه", "وجه", "مشابه",
                  "متوجه", "مواجه", "مشتبه", "منزه", "شبه", "مه", "ده", "به", "که", "نه",
                  "چه", "مکروه", "انتباه", "اشتباه", "جبه", "تبه", "کله"}


def fetch(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print("downloading", url)
        urllib.request.urlretrieve(url, path)
    return path.read_text(encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fix_chars = str.maketrans("يك", "یک")

    # --- Common Voice: attested spellings ---
    text = "".join(fetch(CV_URL.format(f), CACHE / "cv" / f) for f in CV_FILES)
    counts = collections.Counter(t.strip(Z) for t in TOKEN.findall(text.translate(fix_chars)))
    joined_count = collections.Counter()
    for w, c in counts.items():
        if Z in w:
            joined_count[w.replace(Z, "")] += c

    # --- Hazm: lemmas with a real part-of-speech tag, and verb stems ---
    tagged = {}
    for line in fetch(HAZM_URL.format("words.dat"), CACHE / "words.dat").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] != "0":
            tagged[parts[0].translate(fix_chars)] = set(parts[2].split(","))
    verbs = [line.split("#") for line in
             fetch(HAZM_URL.format("verbs.dat"), CACHE / "verbs.dat").translate(fix_chars).splitlines()
             if "#" in line]

    def is_tagged_word(joined):
        return bool(tagged.get(joined, set()) - {"RES"})

    def is_usual_joined(joined):
        """Real sentences clearly prefer the joined spelling (ماهی، توجهی)."""
        c = counts.get(joined, 0)
        return c >= 3 and c >= 3 * joined_count.get(joined, 0)

    forms = set()

    def add(form, check_usage):
        """check_usage: also keep a joined spelling that real text prefers. Off for
        verbs and plurals, where joining is only informal writing (میخوام، چیزهایی)."""
        joined = form.replace(Z, "")
        if is_tagged_word(joined) or (check_usage and is_usual_joined(joined)):
            return
        forms.add(form)

    nouns = {w for w, tags in tagged.items() if tags & {"N", "AJ"} and Z not in w and len(w) >= 2}

    def is_verb_or_plural(w):
        head, _, tail = w.partition(Z)
        return head in ("می", "نمی") or (head in nouns and tail in HA)

    # 1. every half-space spelling real text uses
    for w in counts:
        if Z in w and all(w.split(Z)):
            add(w, check_usage=not is_verb_or_plural(w))

    # 2. plurals of nouns and adjectives
    for n in nouns:
        for s in HA:
            add(n + Z + s, check_usage=False)

    # 3. ezafe / indefinite / copula after a silent final ه (بودجه‌ی، خانه‌ای، نامه‌ام)
    for n in nouns:
        if n.endswith("ه") and len(n) >= 3 and n[-2] not in "اوی" and n not in CONSONANTAL_HE:
            for s in AFTER_SILENT_HE:
                add(n + Z + s, check_usage=s not in HA)

    # 4. می‌/نمی‌ verbs, written and spoken stems, with object clitics
    present = {p for _, p in verbs if p} | set(COLLOQUIAL_STEMS)
    past = {p for p, _ in verbs if p}
    for prefix in ("می", "نمی"):
        for stem in present:
            for end in PRESENT_END:
                for cl in CLITICS:
                    add(prefix + Z + stem + end + cl, check_usage=False)
                    if stem[-1] in "او":  # گوید، گوییم
                        add(prefix + Z + stem + "ی" + end + cl, check_usage=False)
        for stem in past:
            for end in PAST_END:
                for cl in CLITICS:
                    add(prefix + Z + stem + end + cl, check_usage=False)

    # 5. present perfect: رفته‌اند، گفته‌ام
    for stem in past:
        for end in PERFECT_END:
            add(stem + "ه" + Z + end, check_usage=False)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(sorted(forms)) + "\n", encoding="utf-8")
    print(f"{len(forms)} forms -> {OUT.relative_to(ROOT)} "
          f"(Common Voice types: {len(counts)}, Hazm lemmas: {len(tagged)}, verbs: {len(verbs)})")


if __name__ == "__main__":
    main()
