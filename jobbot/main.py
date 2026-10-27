"""Entry point: python -m jobbot.main [--check]

Scans every company in config.yaml, filters the openings, and sends new
matches to Telegram. Jobs already sent are remembered in seen.json.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from .filters import classify, location_ok
from .sources import FETCHERS, SourceError
from .telegram import Telegram, format_job

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen.json"
SEEN_TTL_DAYS = 180

TRACK_ORDER = {"qa": 0, "support": 1, "dev": 2}
LEVEL_ORDER = {"student": 0, "junior": 1}


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen() -> dict[str, str]:
    if not SEEN_PATH.exists():
        return {}
    with open(SEEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen: dict[str, str]) -> None:
    cutoff = (date.today() - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    kept = {k: v for k, v in seen.items() if v >= cutoff}
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(kept.items())), f, indent=1, ensure_ascii=False)
        f.write("\n")


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


def run_check(cfg: dict) -> None:
    """Report which boards work and how many of their jobs are in our area."""
    jobs, failures = fetch_all(cfg)
    by_company: dict[str, list] = {}
    for job in jobs:
        by_company.setdefault(job.company, []).append(job)
    print(f"\n{'company':<20} {'total':>5} {'in area':>8} {'matches':>8}")
    for company, items in sorted(by_company.items()):
        local = [j for j in items if location_ok(j.location, cfg)]
        matched = [j for j in local if classify(j, cfg)]
        print(f"{company:<20} {len(items):>5} {len(local):>8} {len(matched):>8}")
        for j in matched:
            print(f"    -> {j.title} ({j.location})")
    if failures:
        print(f"\n{len(failures)} board(s) failed - fix or remove them in config.yaml:")
        print("  " + "\n  ".join(failures))


def run(cfg: dict) -> int:
    telegram = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
    seen = load_seen()
    jobs, failures = fetch_all(cfg)

    new_matches = []
    for job in jobs:
        if job.key in seen:
            continue
        match = classify(job, cfg)
        if match:
            new_matches.append((job, match))

    new_matches.sort(key=lambda jm: (LEVEL_ORDER[jm[1].level], TRACK_ORDER.get(jm[1].track, 9), jm[0].company))
    limit = cfg.get("max_alerts_per_run", 15)
    to_send, deferred = new_matches[:limit], new_matches[limit:]

    today = date.today().isoformat()
    for job, match in to_send:
        telegram.send(format_job(job, match))
        seen[job.key] = today
        save_seen(seen)  # save after each send so a crash never re-sends

    if deferred:
        telegram.send(f"➕ {len(deferred)} more matching jobs - they'll arrive in the next run.")

    save_seen(seen)
    print(f"\nScanned {len(jobs)} jobs, {len(new_matches)} new matches, sent {len(to_send)}.")
    if failures:
        print(f"{len(failures)} board(s) failed:\n  " + "\n  ".join(failures))
    # Fail the run only if every single board failed - that means something is broken.
    total_boards = sum(len(v or []) for v in (cfg.get("companies") or {}).values())
    return 1 if total_boards and len(failures) == total_boards else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Hunter Bot")
    parser.add_argument("--check", action="store_true", help="only report which boards work")
    args = parser.parse_args()
    cfg = load_config()
    if args.check:
        run_check(cfg)
        return
    sys.exit(run(cfg))


if __name__ == "__main__":
    main()
