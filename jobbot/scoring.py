"""Read a job description and score how well the job fits.

Everything here is plain rules on text, so each score comes with the
reasons that produced it (shown in the app), and is easy to tune.
"""

import re
from dataclasses import asdict, dataclass

from .filters import Match

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "אחת": 1, "שנתיים": 2, "שתיים": 2, "שלוש": 3, "ארבע": 4, "חמש": 5}

_YEARS_EN = re.compile(
    r"(\d{1,2}|one|two|three|four|five|six)\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?"
    r"(?:\s+of)?(?:\s+[\w/&+-]+){0,4}?\s+experience",
    re.I,
)
_YEARS_HE = re.compile(r"(\d{1,2}|אחת|שתיים|שלוש|ארבע|חמש)\s*\+?\s*שנ(?:ות|ים|ה)?\s+(?:של\s+)?ניסיון")
_ONE_YEAR_HE = re.compile(r"שנת\s+ניסיון|כשנת\s+ניסיון")
_TWO_YEARS_HE = re.compile(r"שנתיים\s+(?:של\s+)?ניסיון")
_NO_EXPERIENCE = re.compile(
    r"no (?:prior |previous )?experience|without experience|experience (?:is )?not required|"
    r"ללא ניסיון|אין צורך בניסיון|לא נדרש ניסיון",
    re.I,
)
_PART_TIME = re.compile(r"part[\s-]?time|משרה חלקית|חלקית|\d{2}\s*-\s*\d{2}\s*hours", re.I)
_STUDENT_JOB = re.compile(r"student position|student job|for students|משרת סטודנט|לסטודנטים|סטודנט", re.I)
_FULL_TIME = re.compile(r"full[\s-]?time|משרה מלאה", re.I)
_HYBRID = re.compile(r"hybrid|remote|work from home|היברידי|מהבית|עבודה מרחוק", re.I)


@dataclass
class Facts:
    years: int | None      # minimum years of experience mentioned, None if not stated
    employment: str        # "student" | "part" | "full"
    hybrid: bool


def required_years(text: str) -> int | None:
    if _NO_EXPERIENCE.search(text):
        return 0
    found = []
    for m in _YEARS_EN.finditer(text):
        v = m.group(1).lower()
        found.append(int(v) if v.isdigit() else _NUM_WORDS[v])
    for m in _YEARS_HE.finditer(text):
        v = m.group(1)
        found.append(int(v) if v.isdigit() else _NUM_WORDS[v])
    if _TWO_YEARS_HE.search(text):
        found.append(2)
    if _ONE_YEAR_HE.search(text):
        found.append(1)
    found = [y for y in found if y <= 15]  # ignore things like "20 years of company history"
    return min(found) if found else None


def extract_facts(title: str, description: str, level: str) -> Facts:
    text = f"{title} \n {description}"
    if level == "student" or _STUDENT_JOB.search(title):
        employment = "student"
    elif _PART_TIME.search(text) and not _FULL_TIME.search(title):
        employment = "part"
    else:
        employment = "full"
    return Facts(years=required_years(text), employment=employment, hybrid=bool(_HYBRID.search(text)))


GENERAL_FIELDS = ("security", "lifeguard", "office", "government")
TIERS = (("hot", 6, "🔥"), ("good", 3, "👍"), ("long", -99, "🤔"))


def score(match: Match, facts: Facts, region: str) -> tuple[int, str, list[str]]:
    """Return (score, tier, reasons)."""
    s, reasons = 0, []
    s += {"student": 4, "junior": 2, "possible": 0}[match.level]
    reasons.append({"student": "משרת סטודנט", "junior": "ג'וניור", "possible": "בלי רמה מוגדרת"}[match.level])

    if facts.years == 0:
        s += 2; reasons.append("ללא ניסיון")
    elif facts.years == 1:
        s += 1; reasons.append("שנת ניסיון")
    elif facts.years is not None:
        s -= 3; reasons.append(f"דורש {facts.years}+ שנות ניסיון")

    if facts.employment in ("student", "part"):
        s += 1
        if facts.employment == "part":
            reasons.append("משרה חלקית")
    if facts.hybrid:
        s += 1; reasons.append("היברידי / מהבית")

    if region == "south":
        s += 2; reasons.append("בדרום")
    elif region == "north":
        s -= 2; reasons.append("בצפון")

    if match.track in ("qa", "support"):
        s += 1
    elif match.track in GENERAL_FIELDS:
        s += 2; reasons.append("תחום שבחרת")

    tier = next(name for name, minimum, _ in TIERS if s >= minimum)
    return s, tier, reasons


def tier_emoji(tier: str) -> str:
    return next(e for name, _, e in TIERS if name == tier)


def facts_to_dict(f: Facts) -> dict:
    return asdict(f)


def facts_from_dict(d: dict) -> Facts:
    return Facts(years=d.get("years"), employment=d.get("employment", "full"), hybrid=bool(d.get("hybrid")))
