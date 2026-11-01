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


def test_email_jobs_are_owner_only_and_board_jobs_are_shared():
    alert = AlertEmail("<o>", "alljobs.co.il", "s", [("מאבטח/ת - אשקלון", "https://aj/9")])
    assert email_entries([alert], CFG, "2026-10-30")[0]["owner_only"] is True
    jobs = [Job("comeet", "Acme", "1", "QA Student", "Tel Aviv", "https://a/1", description="x")]
    assert board_entries(jobs, CFG, {}, "2026-10-30", fetch=lambda u: "")[0]["owner_only"] is False



def test_comeet_links_point_to_the_position_not_the_careers_page():
    from jobbot.sources import _comeet_url
    co = {"name": "Exodigo", "slug": "exodigo", "uid": "89.005"}
    generic = {"uid": "75.478", "url_active_page": "https://www.exodigo.com/careers",
               "url_comeet_hosted_page": "https://www.comeet.com/jobs/exodigo/89.005/student/75.478"}
    assert _comeet_url(co, generic) == "https://www.comeet.com/jobs/exodigo/89.005/student/75.478"
    specific = {"uid": "78.E65", "url_active_page": "https://www.upwind.io/careers/co/tel-aviv/78.E65/x/all",
                "url_comeet_hosted_page": "https://www.comeet.com/jobs/upwind/49.004/x/78.E65"}
    assert _comeet_url(co, specific) == specific["url_active_page"]
    deloitte = {"uid": "10.F6C", "url_active_page": "https://careers.deloitte.co.il/position/10-f6c-en/"}
    assert _comeet_url(co, deloitte) == deloitte["url_active_page"]
    assert _comeet_url(co, {"uid": "AB.1"}) == "https://www.comeet.com/jobs/exodigo/89.005/position/AB.1"


def test_comeet_location_uses_the_city_not_just_the_country():
    from jobbot.sources import _comeet_jobs
    from jobbot.filters import region_of
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    item = {"uid": "29.37D", "name": "Student Tier 1 Support Specialist", "workplace_type": "Hybrid",
            "location": {"name": "Israel", "city": "Tel Aviv", "country": "IL", "is_remote": True}}
    job = _comeet_jobs({"name": "Exodigo", "slug": "exodigo", "uid": "89.005"}, [item])[0]
    assert job.location == "Tel Aviv, Israel (Remote)"
    assert region_of(job.location, cfg) == "center"
    item["location"] = {"name": "Beer Sheva", "city": "Beer Sheva"}
    item["workplace_type"] = "On-site"
    assert _comeet_jobs({"name": "X"}, [item])[0].location == "Beer Sheva"


SAMSUNG_REQ = ("Requirements M.Sc. student in Electronic Engineering, Computer Engineering, Software Engineering, "
               "Computer Science or equivalent with at least 3 semesters until graduation GPA 85 and above "
               "Excellent coding skills in C/C++ and/or Python")


def test_masters_only_and_gpa_requirements_are_read():
    from jobbot.scoring import required_degree, required_gpa
    assert required_degree(SAMSUNG_REQ) == "msc"
    assert required_gpa(SAMSUNG_REQ) == 85
    assert required_degree("B.Sc. or M.Sc. student in Computer Science") is None
    assert required_degree("Second-year student in Computer Science") is None
    assert required_degree("סטודנט/ית לתואר שני במדעי המחשב") == "msc"
    assert required_gpa("ממוצע ציונים 80 ומעלה") == 80
    assert required_gpa("GPA of at least 90") == 90
    assert required_gpa("Excellent grades, 3 years of experience") is None


def test_masters_only_student_job_is_no_longer_hot():
    from jobbot.filters import Match
    from jobbot.scoring import extract_facts, score
    m = Match(track="dev", track_label="Development", level="student")
    f = extract_facts("Algorithm Student", SAMSUNG_REQ + " Workplace: On-site", "student")
    assert (f.degree, f.min_gpa, f.hybrid) == ("msc", 85, False)
    s, tier, reasons = score(m, f, "center")
    assert tier == "long" and "רק לסטודנטים לתואר שני" in reasons and "דורש ממוצע 85+" in reasons


def test_comeet_reads_description_from_custom_fields():
    from jobbot.sources import _comeet_jobs
    item = {"uid": "81.470", "name": "Algorithm Student", "workplace_type": "On-site",
            "custom_fields": {"details": [{"name": "Requirements", "value": SAMSUNG_REQ}, {"name": "x", "value": None}]}}
    job = _comeet_jobs({"name": "Samsung"}, [item])[0]
    assert "GPA 85" in job.description and "Workplace: On-site" in job.description


def test_stated_years_beat_experience_not_required():
    from jobbot.scoring import required_years
    assert required_years("4+ years of hands-on experience building ML systems. "
                          "Production experience is not required - a side project is enough") == 4
    assert required_years("No experience required") == 0


def test_jobs_nobody_can_apply_to_are_dropped_from_the_pool():
    import yaml
    from pathlib import Path
    from jobbot.models import Job
    from jobbot.pipeline import board_entries
    cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    mk = lambda t, d: Job("comeet", "Samsung", t, t, "Tel Aviv", "https://x/" + t, d)
    jobs = [mk("Algorithm Student", SAMSUNG_REQ),
            mk("QA Engineer", "3+ years of experience in testing"),
            mk("Algorithm's Infrastructure Student", "B.Sc. student in Computer Science with 2+ years left")]
    titles = [e["title"] for e in board_entries(jobs, cfg, {}, "2026-11-01", fetch=lambda u: "")]
    assert titles == ["Algorithm's Infrastructure Student"]


def test_degree_holders_only():
    from jobbot.scoring import required_degree
    assert required_degree("What are we looking for? M.Sc. / Ph.D. in Electrical Engineering, Computer Science") == "msc"
    assert required_degree("BSc in Electrical Engineering or Computer Engineering from leading university.") == "bsc_done"
    assert required_degree("B.Sc. student in Computer Science with 2+ years left") is None
    assert required_degree("B.Sc. in Computer Science. M.Sc. or Ph.D. in a relevant field - advantage") == "bsc_done"
    assert required_degree("תואר ראשון במדעי המחשב - חובה") == "bsc_done"
    assert required_degree("סטודנט/ית לתואר ראשון במדעי המחשב") is None
