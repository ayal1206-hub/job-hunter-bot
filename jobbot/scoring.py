"""Read a job description and score how well the job fits.

Everything here is plain rules on text, so each score comes with the
reasons that produced it (shown in the app), and is easy to tune.
"""

import re
from dataclasses import asdict, dataclass
from datetime import date

from .filters import Match

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "אחת": 1, "שנתיים": 2, "שתיים": 2, "שלוש": 3, "ארבע": 4, "חמש": 5}

_YEARS_EN = re.compile(
    r"(\d{1,2}|one|two|three|four|five|six)\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?"
    r"(?:\s+of)?(?:\s+[\w/&+-]+){0,4}?\s+experience",
    re.I,
)
# Any "N years" that reads as a requirement: "5+ years running...", "2-4 years in...", "at least 2 years"
_YEARS_ANY = re.compile(
    r"(at least|minimum(?: of)?|min\.?|over|more than)?\s*\b(\d{1,2}|one|two|three|four|five|six)\s*(\+|plus)?\s*"
    r"(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?\b"
    r"(?!\s+(?:old|ago|left|remaining|until|before|to graduat|of (?:growth|history|operation|studies|study)))"
    r"(.{0,60})", re.I)
_EXPERIENCE_WORDS = re.compile(r"experience|hands-on|working|building|running|developing|managing|\bas an?\b|\bin (?:a|an|the)?\s*\w+", re.I)
_ADVANTAGE = re.compile(r"advantage|preferred|nice to have|a plus|bonus|desirable|יתרון|רצוי", re.I)
# Sentence ends: a period after a real word (not "B.Sc."), bullets, line breaks.
_SENTENCE_SPLIT = re.compile(r"(?<=[a-z\u05d0-\u05ea)]{3}[.!?;])\s+|(?<=[•·])\s+|\n+|\s{2,}")


def _is_advantage(text: str, start: int, end: int) -> bool:
    """True when the phrase at text[start:end] is listed as an advantage: an advantage word
    right after it (before the next requirement starts) or a "Nice to have"/"Advantages"
    heading shortly before it."""
    after = re.split(r"(?<=[a-z\u05d0-\u05ea)]{3}[.!?;])\s|\n|•|·|\bmust\b|\bmandatory\b|\brequired\b|חובה", text[end:end + 90], 1, flags=re.I)[0]
    before = text[max(0, start - 40):start]
    return bool(_ADVANTAGE.search(after) or re.search(r"nice to have|advantages?\s*:?\s*$|יתרונות?\s*:?\s*$", before, re.I))


def required_text(text: str) -> str:
    """The description without sentences that only list advantages ("- advantage", "a plus")."""
    return " \n ".join(s for s in _SENTENCE_SPLIT.split(text) if s and not _ADVANTAGE.search(s))


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
# Fully from home (not hybrid): "Remote", "work from home", "עבודה מהבית"
_REMOTE = re.compile(r"\bremote\b|work(?:ing)? from home|\bwfh\b|מהבית|עבודה מרחוק", re.I)
# Housing or travel paid by the employer: makes a job in the center reachable from the south
_RELOCATION = re.compile(
    r"relocation|housing|accommodation|apartment|travel (?:expenses|reimbursement)|"
    r"commut\w* (?:reimburs\w*|allowance|covered)|transportation (?:provided|covered|reimburs\w*)|shuttle|"
    r"דירה|מגורים|לינה|החזר(?:י)?\s+(?:נסיעות|הוצאות נסיעה)|הסעות|הסעה", re.I)
_MASTERS = re.compile(
    r"\b(?:m\.?\s?sc|m\.?\s?s|m\.?\s?a|master'?s?|ph\.?\s?d)\.?\s+(?:degree\s+)?(?:student|candidate)|"
    r"(?<!under)graduate students? only|תואר שני|סטודנט(?:ית|ים)? ל?מאסטר", re.I)
# Holding a Master's/PhD (not only studying for one): "M.Sc. / Ph.D. in EE", "Master's degree in CS"
_MASTERS_DEGREE = re.compile(
    r"\b(?:m\.?\s?sc|ph\.?\s?d|master'?s?)\.?\s*(?:(?:/|or)\s*(?:m\.?\s?sc|ph\.?\s?d)\.?\s*)?(?:degree\s+)?in\b", re.I)
# A finished bachelor's degree: "BSc in Electrical Engineering", "תואר ראשון במדעי המחשב"
_BACHELOR_DONE = re.compile(
    r"\b(?:b\.?\s?sc|b\.?s|b\.?a|bachelor'?s?)\b\.?|\bdegree in\b|\bdegree or equivalent\b|"
    r"(?<!סטודנט ל)(?<!סטודנטית ל)תואר ראשון|בעל(?:/ת|ת)?\s+תואר", re.I)
_STUDYING = re.compile(r"student|studying|undergrad|final year|סטודנט|לומד|לומדת|במהלך התואר", re.I)
_BACHELORS = re.compile(r"\bb\.?\s?sc|\bb\.?\s?a\b|bachelor|undergraduate|תואר ראשון", re.I)
_GPA = re.compile(
    r"(?:gpa|grade point average|average grade|grades? average|ממוצע(?: ציונים)?)\s*(?:of\s*|:\s*)?"
    r"(?:above\s*|over\s*|at least\s*|of at least\s*|מעל\s*|לפחות\s*|של\s*)?(\d{2})|"
    r"(\d{2})\s*\+?\s*(?:gpa|average)", re.I)
_LEFT_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "שנה": 1, "שנתיים": 2, "שלוש": 3, "שלושה": 3, "ארבע": 4, "ארבעה": 4}
# "with 2+ years left", "at least 3 semesters until graduation", "שנתיים לפחות לסיום התואר"
_YEARS_LEFT_EN = re.compile(
    r"(\d|one|two|three|four|five|six)\s*\+?\s*(?:more\s+|full\s+|academic\s+)?(years?|semesters?)\s*"
    r"(?:of\s+(?:studies|study|your degree)\s+)?(?:left|remaining|until\s+graduation|until\s+(?:the\s+)?end|to\s+graduat|before\s+graduat)",
    re.I)
_YEARS_LEFT_HE = re.compile(
    r"(\d|שנה|שנתיים|שלוש|שלושה|ארבע|ארבעה)\s*(?:שנים|שנות לימוד|סמסטרים)?\s*(?:נוספות|נוספים|לפחות)?\s*"
    r"(?:לסיום|עד סיום|עד לסיום)\s*(?:ה)?(?:תואר|לימודים)")
# Jobs only for students of another discipline: "an internship for accounting students only"
_OTHER_FIELD_ONLY = re.compile(
    r"\b(?:accounting|accountancy|economics|law|finance|business(?:\s+administration)?|management|marketing|psychology|industrial engineering|architecture|design|communications?)\s+(?:and\s+(?:accounting|accountancy|economics|law|finance|business(?:\s+administration)?|management|marketing|psychology|industrial engineering|architecture|design|communications?)\s+)?students?\s+only\b|"
    r"\bonly\s+(?:for\s+|to\s+|open\s+to\s+)?(?:accounting|accountancy|economics|law|finance|business(?:\s+administration)?|management|marketing|psychology|industrial engineering|architecture|design|communications?)\s+students\b|"
    r"סטודנט(?:ים|ית|יות)?\s*(?:\S+\s+)?(?:ל|ב)(?:ראיית חשבון|חשבונאות|כלכלה|משפטים|מנהל עסקים|ניהול|שיווק|פסיכולוגיה|הנדסת תעשייה וניהול|אדריכלות|עיצוב|תקשורת)\s+בלבד", re.I)
# "students in their final year", "סטודנטים בשנה האחרונה ללימודים"
_FINAL_YEAR = re.compile(
    r"final[\s-]year|last year of (?:your |their |the )?(?:studies|degree)|graduating (?:students?|this year|in 20)|"
    r"(?:ב|ל)?שנה\s+(?:ה)?אחרונה(?:\s+(?:ל|ב|של\s+)?(?:ה)?(?:לימודים|תואר))?|שנת\s+(?:ה)?לימודים\s+(?:ה)?אחרונה|"
    r"לקראת\s+סיום\s+(?:ה)?(?:תואר|לימודים)", re.I)
# "Second- or third-year student", "סטודנט/ית שנה ג' ומעלה": the lowest study year that is accepted
_STUDY_YEAR_EN = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)(?:[\s-]+year|-(?=\s*or\b))", re.I)
_STUDY_YEAR_HE = re.compile(r"שנה\s+([אבגד])\s*['׳]")
_ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
        "א": 1, "ב": 2, "ג": 3, "ד": 4}
DEGREE_YEARS = 3
FACTS_VERSION = 10   # bump when extract_facts learns something new, so cached facts are re-read


@dataclass
class Facts:
    years: int | None      # minimum years of experience mentioned, None if not stated
    employment: str        # "student" | "part" | "full"
    hybrid: bool
    degree: str | None = None    # "msc" when the job is only for Master's/PhD students
    min_gpa: int | None = None   # minimum grade average the job asks for
    years_left: float | None = None  # studies the student must still have ahead ("2+ years left")
    other_field: bool = False        # only for students of another discipline (accounting, law...)
    remote: bool = False             # can be done from home
    relocation: bool = False         # housing / travel paid by the employer
    final_year: bool = False         # only for students in their final year
    min_study_year: int | None = None  # lowest year of studies accepted ("third-year students")


def required_years(text: str) -> int | None:
    """Years of experience the job requires: the highest stated requirement, ignoring
    sentences that are only advantages."""
    found = []
    for m in _YEARS_ANY.finditer(text):
        if _is_advantage(text, m.start(2), m.start(4)):   # group 4 is the text after "years"
            continue
        at_least, v, plus, rest = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        head = m.group(0)[:m.group(0).lower().rfind("year")]
        ranged = bool(re.search(r"\d\s*(?:-|–|to)\s*\d", head))
        if at_least or plus or ranged or _EXPERIENCE_WORDS.search(rest):
            found.append(int(v) if v.isdigit() else _NUM_WORDS[v])
    for m in _YEARS_HE.finditer(text):
        v = m.group(1)
        found.append(int(v) if v.isdigit() else _NUM_WORDS[v])
    if _TWO_YEARS_HE.search(text):
        found.append(2)
    if _ONE_YEAR_HE.search(text):
        found.append(1)
    found = [y for y in found if y <= 15]  # ignore things like "20 years of company history"
    if found:   # stated years win over "X experience is not required"
        return max(found)
    return 0 if _NO_EXPERIENCE.search(text) else None


def required_degree(text: str) -> str | None:
    """'msc': only for Master's/PhD students or holders. 'bsc_done': needs a finished
    bachelor's (fine for graduates, not for students). None: open to students."""
    if (_MASTERS.search(text) or _MASTERS_DEGREE.search(text)) and not _BACHELORS.search(text):
        return "msc"
    if not _STUDYING.search(text) and any(not _is_advantage(text, m.start(), m.end())
                                          for m in _BACHELOR_DONE.finditer(text)):
        return "bsc_done"
    return None


def required_years_left(text: str) -> float | None:
    found = []
    for m in _YEARS_LEFT_EN.finditer(text):
        v = m.group(1).lower()
        n = int(v) if v.isdigit() else _LEFT_NUM[v]
        found.append(n / 2 if m.group(2).lower().startswith("semester") else n)
    for m in _YEARS_LEFT_HE.finditer(text):
        v = m.group(1)
        n = int(v) if v.isdigit() else _LEFT_NUM[v]
        found.append(n / 2 if "סמסטר" in m.group(0) else n)
    found = [y for y in found if 0 < y <= 4]
    return max(found) if found else None


def years_until(graduation: str | None, today: date | None = None) -> float | None:
    """Years from today until graduation ("2028-07" or "2028")."""
    if not graduation:
        return None
    parts = str(graduation).split("-")
    year, month = int(parts[0]), int(parts[1]) if len(parts) > 1 else 7
    t = today or date.today()
    return round((year - t.year) + (month - t.month) / 12, 2)


def required_study_year(text: str) -> int | None:
    found = [_ORD[m.group(1).lower()] for m in _STUDY_YEAR_EN.finditer(text)]
    found += [_ORD[m.group(1)] for m in _STUDY_YEAR_HE.finditer(text)]
    return min(found) if found and min(found) > 1 else None


def study_year(studies_left: float | None) -> int | None:
    """The owner's current year of studies, from the time left until graduation."""
    if studies_left is None:
        return None
    return max(1, min(DEGREE_YEARS, DEGREE_YEARS - int(studies_left)))


def owner_block(facts: "Facts", studies_left: float | None) -> str | None:
    """Why a student with `studies_left` years to go can't apply, as a reason for the app."""
    if studies_left is None:
        return None
    if facts.years_left and studies_left < facts.years_left:
        return f"דורש עוד {facts.years_left:g}+ שנות לימוד"
    if facts.final_year and studies_left > 1:
        return "רק לסטודנטים בשנה האחרונה"
    year = study_year(studies_left)
    if facts.min_study_year and year < facts.min_study_year:
        return f"רק משנה {'אבגד'[facts.min_study_year - 1]}' ומעלה"
    return None


def required_gpa(text: str) -> int | None:
    found = [int(m.group(1) or m.group(2)) for m in _GPA.finditer(text)]
    found = [g for g in found if 60 <= g <= 100]
    return min(found) if found else None


def extract_facts(title: str, description: str, level: str) -> Facts:
    text = f"{title} \n {description}"
    if level == "student" or _STUDENT_JOB.search(title):
        employment = "student"
    elif _PART_TIME.search(text) and not _FULL_TIME.search(title):
        employment = "part"
    else:
        employment = "full"
    return Facts(years=required_years(text), employment=employment, hybrid=bool(_HYBRID.search(text)),
                 degree=required_degree(text), min_gpa=required_gpa(text),
                 years_left=required_years_left(text), other_field=bool(_OTHER_FIELD_ONLY.search(text)),
                 final_year=bool(_FINAL_YEAR.search(text)), min_study_year=required_study_year(text),
                 remote=bool(_REMOTE.search(text)), relocation=bool(_RELOCATION.search(text)))


GENERAL_FIELDS = ("security", "lifeguard", "office", "government")
TIERS = (("hot", 6, "🔥"), ("good", 3, "👍"), ("long", -99, "🤔"))


def score(match: Match, facts: Facts, region: str, studies_left: float | None = None) -> tuple[int, str, list[str]]:
    """Return (score, tier, reasons). studies_left: the owner's years until graduation."""
    s, reasons = 0, []
    s += {"student": 4, "junior": 2, "possible": 0}[match.level]
    reasons.append({"student": "משרת סטודנט", "junior": "ג'וניור", "possible": "בלי רמה מוגדרת"}[match.level])

    if facts.years == 0:
        s += 2; reasons.append("ללא ניסיון")
    elif facts.years == 1:
        s += 1; reasons.append("שנת ניסיון")
    elif facts.years is not None:
        s -= 3; reasons.append(f"דורש {facts.years}+ שנות ניסיון")

    if facts.degree == "msc":
        s -= 4; reasons.append("רק לסטודנטים לתואר שני")
    elif facts.degree == "bsc_done":
        s -= 3; reasons.append("דורש תואר גמור")
    block = owner_block(facts, studies_left)
    if block:
        s -= 4; reasons.append(block)
    if facts.min_gpa:
        s -= 2; reasons.append(f"דורש ממוצע {facts.min_gpa}+")

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
    return {**asdict(f), "v": FACTS_VERSION}


def facts_from_dict(d: dict) -> Facts:
    return Facts(years=d.get("years"), employment=d.get("employment", "full"), hybrid=bool(d.get("hybrid")),
                 degree=d.get("degree"), min_gpa=d.get("min_gpa"), years_left=d.get("years_left"),
                 other_field=bool(d.get("other_field")), final_year=bool(d.get("final_year")),
                 min_study_year=d.get("min_study_year"), remote=bool(d.get("remote")),
                 relocation=bool(d.get("relocation")))
