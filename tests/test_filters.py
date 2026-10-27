from pathlib import Path

import pytest
import yaml

from jobbot.filters import classify, location_ok
from jobbot.models import Job
from jobbot.telegram import format_job

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))


def job(title, location="Tel Aviv, Israel"):
    return Job("greenhouse", "Acme", "1", title, location, "https://example.com/job?a=1&b=2")


@pytest.mark.parametrize("location", [
    "Tel Aviv, Israel", "Tel-Aviv", "Ramat Gan", "Beer Sheva, Israel", "Ashkelon",
    "Israel", "Remote, Israel", "Hybrid - Israel", "תל אביב", "באר שבע", "Tel Aviv / New York",
])
def test_locations_in_area(location):
    assert location_ok(location, CFG)


@pytest.mark.parametrize("location", [
    "Haifa, Israel", "Jerusalem, Israel", "New York, NY", "London", "Yokneam, Israel", "",
])
def test_locations_outside_area(location):
    assert not location_ok(location, CFG)


@pytest.mark.parametrize("title, track, level", [
    ("QA Automation Student", "qa", "student"),
    ("Software Engineer - Student", "dev", "student"),
    ("Technical Support Intern", "support", "student"),
    ("Junior QA Engineer", "qa", "junior"),
    ("Junior IT Technician", "support", "junior"),
    ("סטודנט/ית לבדיקות תוכנה", "qa", "student"),
    ("Data Analyst Student", "dev", "student"),
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
    "QA Engineer",                 # not student or junior
    "Finance Student",             # student but no tech track
    "Marketing Intern",            # student but no tech track
])
def test_rejects(title):
    assert classify(job(title), CFG) is None


def test_rejects_student_job_outside_area():
    assert classify(job("QA Student", "Haifa, Israel"), CFG) is None


def test_whole_word_matching_avoids_false_hits():
    # "sr" must not match inside "SRE"-like words or "israel"; "it" must not match inside "security".
    assert classify(job("Security Research Student"), CFG) is None  # no track keyword
    assert classify(job("Site Reliability Student, SRE"), CFG) is None


def test_message_escapes_html():
    j = Job("lever", "A&B <Co>", "9", "QA <Student>", "Tel Aviv", "https://x.com/?a=1&b=2")
    text = format_job(j, classify(j, CFG))
    assert "A&amp;B &lt;Co&gt;" in text
    assert "QA &lt;Student&gt;" in text
    assert 'href="https://x.com/?a=1&amp;b=2"' in text
