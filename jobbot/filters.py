"""Decide whether a job is worth an alert, and which track it belongs to."""

import re
from dataclasses import dataclass

from .models import Job

_COUNTRY_ONLY_WORDS = {"israel", "il", "remote", "hybrid", "ישראל"}


def _matches(text: str, keyword: str) -> bool:
    """Whole-word match for Latin keywords, substring match for Hebrew."""
    keyword = keyword.lower().strip()
    if not keyword:
        return False
    if re.search(r"[֐-׿]", keyword):
        return keyword in text
    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _any(text: str, keywords) -> bool:
    return any(_matches(text, k) for k in keywords)


def location_ok(location: str, cfg: dict) -> bool:
    loc = location.lower()
    if any(city.lower() in loc for city in cfg["locations"]):
        return True
    if cfg.get("accept_country_only") and ("israel" in loc or "ישראל" in loc):
        words = set(re.findall(r"[a-z֐-׿]+", loc))
        return bool(words) and words <= _COUNTRY_ONLY_WORDS
    return False


@dataclass(frozen=True)
class Match:
    track: str
    track_label: str
    level: str  # "student" | "junior"


def classify(job: Job, cfg: dict) -> Match | None:
    """Return a Match if the job should be sent, else None."""
    title = job.title.lower()

    if _any(title, cfg["exclude_keywords"]):
        return None
    if not location_ok(job.location, cfg):
        return None

    track = next(
        (name for name, t in cfg["tracks"].items() if _any(title, t["keywords"])),
        None,
    )

    if _any(title, cfg["student_keywords"]):
        level = "student"
    elif _any(title, cfg["junior_keywords"]):
        level = "junior"
    else:
        return None

    if track is None:
        # A student job outside our tracks (e.g. "Student - Finance") is not relevant.
        return None
    if level == "junior" and track not in cfg["junior_tracks"]:
        return None

    return Match(track=track, track_label=cfg["tracks"][track]["label"], level=level)
