"""Turn raw jobs (boards + alert emails) into the scored list the app shows."""

from datetime import date, datetime, timedelta, timezone

from .details import fetch_description, page_to_text
from .email_alerts import AlertEmail
from .filters import Match, _any, evaluate, region_of
from .models import Job
from .scoring import extract_facts, facts_from_dict, facts_to_dict, score

EMAIL_JOB_TTL_DAYS = 14
FIELD_LABELS = {"qa": "QA", "support": "תמיכה / IT", "dev": "פיתוח", "tech": "טכנולוגיה"}


def _field_of_title(title: str, cfg: dict) -> tuple[str, str]:
    """(field key, label) for a free-text title: tech tracks first, then general fields."""
    text = title.lower()
    for name, t in cfg["tracks"].items():
        if _any(text, t["keywords"]):
            return name, FIELD_LABELS.get(name, t["label"])
    for name, f in cfg.get("general_fields", {}).items():
        if _any(text, f["keywords"]):
            return name, f["label"]
    return "other", "אחר"


def _entry(key, source, company, title, location, region, url, field, field_label,
           match, facts, today, origin) -> dict:
    s, tier, reasons = score(match, facts, region)
    is_tech = field in ("qa", "support", "dev", "tech")
    return {
        "key": key, "source": source, "origin": origin, "company": company,
        "title": title, "location": location, "region": region, "url": url,
        "field": field, "field_label": field_label, "level": match.level,
        "employment": facts.employment, "years": facts.years, "hybrid": facts.hybrid,
        "score": s, "tier": tier, "reasons": reasons,
        "cv": "tech" if is_tech else "general", "first_seen": today,
    }


def board_entries(jobs: list[Job], cfg: dict, facts_cache: dict, today: str,
                  fetch=fetch_description) -> list[dict]:
    entries = []
    for job in jobs:
        match, _ = evaluate(job, cfg)
        if not match:
            continue
        if job.key in facts_cache:
            facts = facts_from_dict(facts_cache[job.key])
        else:
            text = page_to_text(job.description) if job.description.strip() else fetch(job.url)
            facts = extract_facts(job.title, text, match.level)
            facts_cache[job.key] = facts_to_dict(facts)
        region = region_of(job.location, cfg) or "any"
        entries.append(_entry(job.key, job.source, job.company, job.title, job.location, region,
                              job.url, match.track, FIELD_LABELS.get(match.track, match.track_label),
                              match, facts, today, "board"))
    return entries


def email_entries(alerts: list[AlertEmail], cfg: dict, today: str) -> list[dict]:
    entries = []
    for alert in alerts:
        for title, url in alert.jobs:
            field, label = _field_of_title(title, cfg)
            level = "student" if _any(title.lower(), cfg["student_keywords"]) else "possible"
            facts = extract_facts(title, "", level)
            match = Match(track=field, track_label=label, level=level)
            region = region_of(title, cfg) or "any"
            source = alert.sender.split(".")[0]
            entries.append(_entry(f"email:{url}", source, source, title, "", region, url,
                                  field, label, match, facts, today, "email"))
    return entries


def merge(previous: list[dict], fresh: list[dict], today: str) -> list[dict]:
    """Keep first_seen dates; drop board jobs that closed; keep email jobs for a while."""
    first_seen = {e["key"]: e["first_seen"] for e in previous}
    by_key = {}
    for e in fresh:
        e["first_seen"] = first_seen.get(e["key"], today)
        by_key[e["key"]] = e
    cutoff = (date.fromisoformat(today) - timedelta(days=EMAIL_JOB_TTL_DAYS)).isoformat()
    for e in previous:
        if e["origin"] == "email" and e["key"] not in by_key and e["first_seen"] >= cutoff:
            by_key[e["key"]] = e
    return sorted(by_key.values(), key=lambda e: (e["score"], e["first_seen"]), reverse=True)


def all_fields(cfg: dict) -> list[list[str]]:
    """Every field the app can filter by, in display order - shown even with 0 jobs."""
    fields = [[k, FIELD_LABELS.get(k, t["label"])] for k, t in cfg["tracks"].items()]
    fields += [[k, f["label"]] for k, f in cfg.get("general_fields", {}).items()]
    return fields + [["other", "אחר"]]


def state(jobs: list[dict], cfg: dict | None = None) -> dict:
    data = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": jobs}
    if cfg:
        data["fields"] = all_fields(cfg)
    return data
