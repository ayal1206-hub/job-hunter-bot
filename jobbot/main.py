"""Entry point: python -m jobbot.main [--check]

Every run:
  1. fetch jobs from the company boards (Greenhouse, Lever, Comeet)
  2. read job-alert emails (AllJobs, Drushim...) from Gmail, if configured
  3. keep student / junior / possible-fit roles in Israel, read each
     description and score it (see scoring.py)
  4. write docs/jobs.json - the list the Telegram mini app shows
  5. send an immediate Telegram alert only for new 🔥 jobs
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from .email_alerts import fetch_alert_emails
from .pipeline import board_entries, email_entries, merge, state
from .scoring import tier_emoji
from .sources import FETCHERS, SourceError
from .telegram import Telegram, format_hot

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen.json"              # jobs already notified
JOBS_PATH = ROOT / "docs" / "jobs.json"     # what the mini app shows
FACTS_PATH = ROOT / "data" / "facts.json"   # cached description facts
REPORT_PATH = ROOT / "reports" / "check.txt"
SEEN_TTL_DAYS = 180


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")


def load_seen() -> dict[str, str]:
    return _load_json(SEEN_PATH, {})


def save_seen(seen: dict[str, str]) -> None:
    cutoff = (date.today() - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    _save_json(SEEN_PATH, dict(sorted((k, v) for k, v in seen.items() if v >= cutoff)))


def fetch_all(cfg: dict):
    jobs, failures = [], []
    for source, companies in (cfg.get("companies") or {}).items():
        fetch = FETCHERS[source]
        for company in companies or []:
            try:
                found = fetch(company)
                jobs.extend(found)
                print(f"[ok]   {source:<10} {company['name']:<20} {len(found)} jobs")
            except SourceError as exc:
                failures.append(f"{source}/{company['name']}: {exc}")
                print(f"[fail] {source:<10} {company['name']:<20} {exc}")
    return jobs, failures


def fetch_emails(cfg: dict):
    ecfg = cfg.get("email_alerts") or {}
    address, password = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not ecfg.get("enabled") or not (address and password):
        print("Email alerts: skipped (not configured)")
        return []
    try:
        alerts = fetch_alert_emails(address, password.replace(" ", ""), ecfg["senders"],
                                    ecfg.get("lookback_days", 3), ecfg.get("max_jobs_per_email", 10))
    except Exception as exc:  # IMAP problems must never break the run
        print(f"Email alerts: failed ({type(exc).__name__}: {exc})")
        return []
    print(f"Email alerts: {len(alerts)} emails, {sum(len(a.jobs) for a in alerts)} job links")
    return alerts


def build(cfg: dict, today: str) -> tuple[list[dict], list[str], int]:
    jobs, failures = fetch_all(cfg)
    facts_cache = _load_json(FACTS_PATH, {})
    fresh = board_entries(jobs, cfg, facts_cache, today) + email_entries(fetch_emails(cfg), cfg, today)
    live = {j.key for j in jobs}
    _save_json(FACTS_PATH, {k: v for k, v in facts_cache.items() if k in live})
    previous = _load_json(JOBS_PATH, {"jobs": []})["jobs"]
    return merge(previous, fresh, today), failures, len(jobs)


def run(cfg: dict) -> int:
    today = date.today().isoformat()
    entries, failures, scanned = build(cfg, today)
    _save_json(JOBS_PATH, state(entries, cfg))

    telegram = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
    seen = load_seen()
    hot = [e for e in entries if e["tier"] == "hot" and e["key"] not in seen]
    for e in hot:
        telegram.send(format_hot(e, cfg.get("app_url")))
        seen[e["key"]] = today
        save_seen(seen)  # save after each send so a crash never re-sends
    # Everything else is shown in the app; mark it so it never triggers an alert later.
    for e in entries:
        seen.setdefault(e["key"], today)
    save_seen(seen)

    tiers = {t: sum(1 for e in entries if e["tier"] == t) for t in ("hot", "good", "long")}
    print(f"\nScanned {scanned} jobs -> {len(entries)} in the app "
          f"({tiers['hot']} hot, {tiers['good']} good, {tiers['long']} long shot); alerted {len(hot)}.")
    if failures:
        print(f"{len(failures)} board(s) failed:\n  " + "\n  ".join(failures))
    total_boards = sum(len(v or []) for v in (cfg.get("companies") or {}).values())
    return 1 if total_boards and len(failures) == total_boards else 0


def run_check(cfg: dict) -> None:
    """Report boards, in-area verdicts and scores; saved to reports/check.txt."""
    from . import sources
    sources.DEBUG_DIR = REPORT_PATH.parent / "debug"
    today = date.today().isoformat()
    entries, failures, _ = build(cfg, today)
    jobs_by_company: dict[str, list] = {}
    for e in entries:
        jobs_by_company.setdefault(e["company"], []).append(e)

    lines = [f"Check run {today}", ""]
    if failures:
        lines += [f"{len(failures)} board(s) failed:"] + [f"  {f}" for f in failures] + [""]
    lines.append("Jobs in the app, by company (score, tier, reasons):")
    for company, items in sorted(jobs_by_company.items()):
        lines.append(f"\n## {company}")
        for e in items:
            lines.append(f"{tier_emoji(e['tier'])} {e['score']:>3}  {e['title']}  [{e['location'] or e['region']}]"
                         f"  {e['employment']}, years={e['years']}  -> {' · '.join(e['reasons'])}")
    report = "\n".join(lines) + "\n"
    print(report)
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Hunter Bot")
    parser.add_argument("--check", action="store_true", help="report boards and scores, no alerts")
    args = parser.parse_args()
    cfg = load_config()
    if args.check:
        run_check(cfg)
        return
    sys.exit(run(cfg))


if __name__ == "__main__":
    main()
