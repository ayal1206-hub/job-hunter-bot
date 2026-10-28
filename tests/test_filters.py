from pathlib import Path

import pytest
import yaml

from jobbot.filters import classify, location_ok, region_of
from jobbot.models import Job

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))


def job(title, location="Tel Aviv, Israel"):
    return Job("greenhouse", "Acme", "1", title, location, "https://example.com/job?a=1&b=2")


@pytest.mark.parametrize("location, region", [
    ("Tel Aviv, Israel", "center"), ("Tel-Aviv", "center"), ("Ramat Gan", "center"),
    ("Beer Sheva, Israel", "south"), ("Ashkelon", "south"), ("באר שבע", "south"),
    ("Haifa, Israel", "north"), ("Yokneam, Israel", "north"), ("Jerusalem, Israel", "center"),
    ("Israel", "any"), ("Remote, Israel", "any"), ("Hybrid - Israel", "any"),
    ("Tel Aviv / New York", "center"), ("Kiryat Gat", "south"),
])
def test_regions(location, region):
    assert region_of(location, CFG) == region


@pytest.mark.parametrize("location", ["New York, NY", "London", "Berlin, Germany", ""])
def test_locations_outside_israel(location):
    assert not location_ok(location, CFG)


@pytest.mark.parametrize("title, track, level", [
    ("QA Automation Student", "qa", "student"),
    ("Software Engineer - Student", "dev", "student"),
    ("Technical Support Intern", "support", "student"),
    ("Junior QA Engineer", "qa", "junior"),
    ("Junior IT Technician", "support", "junior"),
    ("סטודנט/ית לבדיקות תוכנה", "qa", "student"),
    ("Data Analyst Student", "dev", "student"),
    ("IT Support Specialist", "support", "possible"),
    ("QA Engineer", "qa", "possible"),
    ("Security Analyst (Student Position)", "tech", "student"),
    ("Cloud Monitoring Engineer (Student Position)", "tech", "student"),
    ("Service Desk Specialist", "support", "possible"),
    ("תומכ.ת טכני.ת", "support", "possible"),
])
def test_matches(title, track, level):
    m = classify(job(title), CFG)
    assert m is not None, title
    assert (m.track, m.level) == (track, level)


@pytest.mark.parametrize("title", [
    "Senior QA Engineer",          # senior
    "Sr. Software Engineer",       # sr abbreviation
    "QA Team Lead",                # lead
    "Junior Backend Developer",    # junior dev is not in junior_tracks
    "Data Engineer",               # dev with no level is not a possible fit
    "Network Automation Engineer", # 'automation' alone is not QA
    "Expert Backend Engineer",     # expert
    "Experienced Software Engineer",
    "Finance Student",             # student but no tech track
    "Marketing Intern",            # student but no tech track
    "FP&A Analyst - Student Position",  # analyst alone is not tech
    "Security Engineer",           # broad tech track is student-only
])
def test_rejects(title):
    assert classify(job(title), CFG) is None


def test_rejects_student_job_outside_israel():
    assert classify(job("QA Student", "London, UK"), CFG) is None


def test_whole_word_matching_avoids_false_hits():
    # "it" must not match inside "community" / "security"; "sr" must not match inside "israel".
    assert classify(job("Community Student"), CFG) is None
    assert classify(job("QA Student - Israel"), CFG).level == "student"
    assert classify(job("Security Officer"), CFG) is None


def test_hot_message_escapes_html():
    from jobbot.telegram import format_hot
    e = {"title": "QA <Student>", "company": "A&B <Co>", "location": "Tel Aviv", "region": "center",
         "reasons": ["משרת סטודנט"], "cv": "tech", "url": "https://x.com/?a=1&b=2"}
    text = format_hot(e, "https://app/")
    assert "A&amp;B &lt;Co&gt;" in text
    assert "QA &lt;Student&gt;" in text
    assert 'href="https://x.com/?a=1&amp;b=2"' in text
    assert "Tech (English)" in text and 'href="https://app/"' in text
