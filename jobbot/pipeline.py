"""Turn raw jobs (boards + alert emails) into the scored list the app shows."""

import re
from datetime import date, datetime, timedelta, timezone

from .details import fetch_description, page_to_text
from .email_alerts import AlertEmail
from .filters import Match, _any, evaluate, region_of
from .models import Job
from .scoring import FACTS_VERSION, extract_facts, facts_from_dict, facts_to_dict, owner_block, score, years_until

EMAIL_JOB_TTL_DAYS = 14
SITE_NAMES = {"alljob": "AllJobs", "alljobs": "AllJobs", "drushim": "Drushim", "jobmaster": "JobMaster",
              "linkedin": "LinkedIn"}
FIELD_LABELS = {"qa": "QA", "support": "תמיכה / IT", "cyber": "סייבר", "data": "דאטה / BI",
                "devops": "DevOps / ענן", "dev": "פיתוח", "tech": "טכנולוגיה"}


def _field_of_title(title: str, cfg: dict) -> tuple[str, str]:
    """(field key, label) for a free-text title: tech tracks first, then general fields."""
    text = title.lower()
    tracks = cfg["tracks"]
    for name, t in tracks.items():
        if name != "tech" and _any(text, t["keywords"]):
            return name, FIELD_LABELS.get(name, t["label"])
    # General fields before the broad "tech" track: "back office for the engineering
    # department" is an office job, not a tech one.
    for name, f in cfg.get("general_fields", {}).items():
        if _any(text, f["keywords"]):
            return name, f["label"]
    if "tech" in tracks and _any(text, tracks["tech"]["keywords"]):
        return "tech", FIELD_LABELS["tech"]
    return "other", "אחר"


def _entry(key, source, company, title, location, region, url, field, field_label,
           match, facts, today, origin, studies_left=None) -> dict:
    s, tier, reasons = score(match, facts, region, studies_left)
    is_tech = field in FIELD_LABELS
    return {
        "key": key, "source": source, "origin": origin, "company": company,
        "title": title, "location": location, "region": region, "url": url,
        "field": field, "field_label": field_label, "level": match.level,
        "employment": facts.employment, "years": facts.years, "hybrid": facts.hybrid,
        "degree": facts.degree, "min_gpa": facts.min_gpa, "years_left": facts.years_left,
        # The owner can't apply: needs more years of studies than the owner has left.
        "final_year": facts.final_year, "min_study_year": facts.min_study_year,
        "remote": facts.remote or "remote" in (location or "").lower(), "relocation": facts.relocation,
        "owner_hide": bool(owner_block(facts, studies_left)),
        "score": s, "tier": tier, "reasons": reasons,
        "cv": "tech" if is_tech else "general", "first_seen": today,
        # Jobs from the owner's personal alert emails are shown only to the owner.
        "owner_only": origin == "email",
    }


def drop_reason(facts, cfg: dict) -> str | None:
    """Why a job that passed the title filter is still not for us, once its description is read."""
    rules = cfg.get("drop", {})
    if rules.get("other_fields") and facts.other_field:
        return "other discipline only"
    if rules.get("masters_only") and facts.degree == "msc":
        return "masters only"
    if rules.get("min_years") and facts.years is not None and facts.years >= rules["min_years"]:
        return f"{facts.years}+ years"
    return None


def board_entries(jobs: list[Job], cfg: dict, facts_cache: dict, today: str,
                  fetch=fetch_description) -> list[dict]:
    entries = []
    for job in jobs:
        match, _ = evaluate(job, cfg)
        if not match:
            continue
        if facts_cache.get(job.key, {}).get("v") == FACTS_VERSION:
            facts = facts_from_dict(facts_cache[job.key])
        else:
            text = page_to_text(job.description) if job.description.strip() else fetch(job.url)
            facts = extract_facts(job.title, text, match.level)
            facts_cache[job.key] = facts_to_dict(facts)
        if drop_reason(facts, cfg):
            continue
        region = region_of(job.location, cfg) or "any"
        entries.append(_entry(job.key, job.source, job.company, job.title, job.location, region,
                              job.url, match.track, FIELD_LABELS.get(match.track, match.track_label),
                              match, facts, today, "board",
                              years_until((cfg.get("owner") or {}).get("graduation"))))
    return entries


def email_entries(alerts: list[AlertEmail], cfg: dict, today: str) -> list[dict]:
    entries = []
    for alert in alerts:
        source = "linkedin" if "linkedin" in alert.sender else alert.sender.split(".")[0]
        site = SITE_NAMES.get(source, source)
        for job in alert.jobs:
            title, url, company, location, details = (*job, "", "", "")[:5]
            low = title.lower()
            if _any(low, cfg["exclude_keywords"]):
                continue   # senior / lead / manager roles from alert emails too
            field, label = _field_of_title(title, cfg)
            if field == "other" and not cfg.get("email_alerts", {}).get("keep_other_fields", False):
                continue   # sales, call centres... job sites send plenty of those
            text = f"{title} {details}".lower()
            level = ("student" if _any(text, cfg["student_keywords"]) or "מתאים גם לסטודנטים" in text
                     else "junior" if _any(low, cfg["junior_keywords"]) else "possible")
            facts = extract_facts(title, details, level)
            if drop_reason(facts, cfg):
                continue
            match = Match(track=field, track_label=label, level=level)
            region = region_of(location, cfg) or region_of(title, cfg) or "any"
            entries.append(_entry(f"email:{url}", source, company or site, title, location, region, url,
                                  field, label, match, facts, today, "email",
                                  years_until((cfg.get("owner") or {}).get("graduation"))))
    return entries


def signature(e: dict) -> str:
    """Same job, different link: agencies repost the same ad daily on AllJobs with a new id,
    and a few boards list one role twice. Same title + company + place = same job."""
    if not e.get("title"):
        return e["key"]
    norm = lambda s: re.sub(r"[\s/\\\-–|,.!?]+", " ", (s or "").lower()).strip()
    return f"{norm(e.get('title'))}|{norm(e.get('company'))}|{norm(e.get('location'))}"


def dedupe(entries: list[dict]) -> list[dict]:
    """Keep one entry per signature: the newest post (its link is the live one), with the date
    the job was first seen under any of its posts."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(signature(e), []).append(e)
    out = []
    for posts in groups.values():
        newest = max(posts, key=lambda e: (e["first_seen"], e["key"]))
        out.append({**newest, "first_seen": min(e["first_seen"] for e in posts)} if len(posts) > 1 else newest)
    return out


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
    return sorted(dedupe(list(by_key.values())), key=lambda e: (e["score"], e["first_seen"]), reverse=True)


def alert_reason(e: dict) -> str | None:
    """Telegram alerts go out only for the very best matches; everything else waits in the app.
    A job qualifies when it is a student position in a CS field that a second-year student can
    apply to, and it is reachable: in the south, from home, or in the center with housing or
    travel paid. Returns the reason shown in the alert, or None."""
    if e.get("field") not in FIELD_LABELS or e.get("level") != "student":
        return None
    if e.get("owner_hide") or e.get("min_gpa") or e.get("degree") in ("msc", "bsc_done") or (e.get("years") or 0) > 0:
        return None
    if e.get("region") == "south":
        return "בדרום"
    if e.get("remote"):
        return "מהבית"
    if e.get("region") == "center" and e.get("relocation"):
        return "במרכז, עם דירה / החזרי נסיעות"
    return None


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
