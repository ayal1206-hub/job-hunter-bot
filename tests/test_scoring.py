from pathlib import Path

import pytest
import yaml

from jobbot.email_alerts import AlertEmail
from jobbot.filters import Match
from jobbot.models import Job
from jobbot.pipeline import board_entries, email_entries, merge
from jobbot.scoring import Facts, extract_facts, required_years, score

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("text, years", [
    ("Requirements: 3+ years of experience in QA", 3),
    ("At least 2 years of hands-on experience with Linux", 2),
    ("1-2 years experience in support", 1),
    ("two years of professional experience", 2),
    ("Requirements: 3+ years of experience. Nice to have: 1 year experience with Jira", 1),
    ("לפחות 3 שנות ניסיון בבדיקות", 3),
    ("שנתיים ניסיון בתמיכה", 2),
    ("שנת ניסיון לפחות", 1),
    ("ללא ניסיון, הכשרה מלאה", 0),
    ("No prior experience required", 0),
    ("We are a fast growing company founded 20 years ago", None),
    ("Strong communication skills", None),
])
def test_required_years(text, years):
    assert required_years(text) == years


def test_employment_and_hybrid():
    assert extract_facts("QA Student", "", "student").employment == "student"
    assert extract_facts("Support Specialist", "This is a part-time role", "possible").employment == "part"
    assert extract_facts("Support Specialist", "Full time, hybrid model", "possible").employment == "full"
    assert extract_facts("Support Specialist", "Full time, hybrid model", "possible").hybrid is True
    assert extract_facts("מאבטח/ת - משרה חלקית", "", "possible").employment == "part"


def test_score_tiers():
    student_south = score(Match("support", "Support", "student"), Facts(0, "student", True), "south")
    assert student_south[1] == "hot" and "בדרום" in student_south[2]
    possible_needs_3 = score(Match("support", "Support", "possible"), Facts(3, "full", False), "center")
    assert possible_needs_3[1] == "long"
    possible_south = score(Match("support", "Support", "possible"), Facts(None, "full", False), "south")
    assert possible_south[1] == "good"


def test_board_entries_use_description_and_cache():
    jobs = [
        Job("comeet", "Acme", "1", "Technical Support - Student Position", "Tel Aviv", "https://a/1",
            description="&lt;p&gt;No prior experience required. Hybrid.&lt;/p&gt;"),
        Job("comeet", "Acme", "2", "IT Support Specialist", "Beer Sheva", "https://a/2"),
        Job("comeet", "Acme", "3", "Senior QA", "Tel Aviv", "https://a/3"),
    ]
    fetched = []
    def fake_fetch(url):
        fetched.append(url)
        return "Requirements: 2+ years of experience"
    cache = {}
    entries = board_entries(jobs, CFG, cache, "2026-10-28", fetch=fake_fetch)
    assert [e["title"] for e in entries] == ["Technical Support - Student Position", "IT Support Specialist"]
    student, specialist = entries
    assert student["years"] == 0 and student["hybrid"] and student["tier"] == "hot" and student["cv"] == "tech"
    assert specialist["years"] == 2 and specialist["region"] == "south"
    assert fetched == ["https://a/2"]  # only fetched when the source had no description
    board_entries(jobs, CFG, cache, "2026-10-28", fetch=fake_fetch)
    assert fetched == ["https://a/2"]  # cached the second time


def test_email_entries_fields_and_regions():
    alert = AlertEmail("<m>", "alljobs.co.il", "s", [
        ("מאבטח/ת לובי - באר שבע", "https://aj/1"),
        ("סטודנט/ית לתמיכה טכנית - אשקלון", "https://aj/2"),
        ("מציל/ה לבריכה", "https://aj/3"),
    ])
    e = {x["url"]: x for x in email_entries([alert], CFG, "2026-10-28")}
    assert e["https://aj/1"]["field"] == "security" and e["https://aj/1"]["region"] == "south"
    assert e["https://aj/1"]["cv"] == "general"
    assert e["https://aj/2"]["field"] == "support" and e["https://aj/2"]["level"] == "student"
    assert e["https://aj/2"]["cv"] == "tech"
    assert e["https://aj/3"]["field"] == "lifeguard" and e["https://aj/3"]["region"] == "any"


def test_merge_keeps_first_seen_and_expires_email_jobs():
    prev = [
        {"key": "board:1", "origin": "board", "first_seen": "2026-10-20", "score": 5},
        {"key": "board:closed", "origin": "board", "first_seen": "2026-10-20", "score": 5},
        {"key": "email:old", "origin": "email", "first_seen": "2026-10-01", "score": 1},
        {"key": "email:recent", "origin": "email", "first_seen": "2026-10-25", "score": 1},
    ]
    fresh = [{"key": "board:1", "origin": "board", "first_seen": "2026-10-28", "score": 5}]
    keys = {e["key"]: e for e in merge(prev, fresh, "2026-10-28")}
    assert set(keys) == {"board:1", "email:recent"}
    assert keys["board:1"]["first_seen"] == "2026-10-20"


def test_chosen_general_field_in_south_is_worth_a_look():
    s, tier, reasons = score(Match("lifeguard", "הצלה", "possible"), Facts(None, "full", False), "south")
    assert tier == "good" and "תחום שבחרת" in reasons


def test_government_jobs_from_emails_get_their_own_field():
    alert = AlertEmail("<g>", "drushim.co.il", "s", [("בודק/ת מכס - רשות המסים, אשדוד", "https://d/1")])
    e = email_entries([alert], CFG, "2026-10-28")[0]
    assert e["field"] == "government" and e["field_label"] == "שירות המדינה"
    assert e["region"] == "south" and e["tier"] == "good"
    dog = email_entries([AlertEmail("<k>", "drushim.co.il", "s", [("כלבן/ית - רשות המסים", "https://d/2")])], CFG, "2026-10-28")[0]
    assert dog["field"] == "government"


def test_state_lists_every_field_for_the_app():
    from jobbot.pipeline import state
    keys = [k for k, _ in state([], CFG)["fields"]]
    assert {"qa", "support", "dev", "security", "lifeguard", "government"} <= set(keys)
