# Job Hunter Bot

A small Python bot that scans the job boards of Israeli tech companies every few hours and sends me new student and junior openings on Telegram.

I built it to stop refreshing career pages by hand during my second year of a Computer Science degree. It runs for free on GitHub Actions and needs no server.

## How it works

```
GitHub Actions (every 4 hours)
        │
        ▼
 fetch jobs from Greenhouse, Lever and Comeet APIs
        │
        ▼
 filter: location, seniority, role track
        │
        ▼
 skip jobs already sent (seen.json)
        │
        ▼
 Telegram alert  ──►  I review and apply
```

- **Sources:** public JSON APIs of the three applicant-tracking systems most Israeli tech companies use. No scraping of sites that forbid it, so the bot doesn't get blocked.
- **Filtering:** a job matches when its location is in the search area, its title is student- or junior-level, and it belongs to a role track (QA, tech support, development). Senior roles are excluded. Keywords work in English and Hebrew, with whole-word matching so "sr" doesn't hit inside other words.
- **Memory:** sent jobs are stored in `seen.json`, which the workflow commits back to the repo. Entries expire after 180 days.
- **Robustness:** a board that fails (company switched ATS, wrong token) is skipped and reported in the log; the run fails only if every board fails.

Applications are always sent by me. The bot only finds and reports.

## Configuration

Everything lives in [`config.yaml`](config.yaml): locations, keywords per track, and the list of companies. Adding a company is one line.

To see which boards work and how many local jobs each has, run the workflow manually with **check** enabled, or:

```bash
python -m jobbot.main --check
```

## Running it yourself

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and get your chat id.
2. Add two repository secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Enable GitHub Actions. The bot runs every 4 hours, or on demand from the Actions tab.

Run locally (prints alerts instead of sending them when no token is set):

```bash
pip install -r requirements.txt
python -m jobbot.main
pytest
```

## Project structure

```
jobbot/
  sources.py    # Greenhouse, Lever, Comeet fetchers
  filters.py    # location + seniority + track rules
  telegram.py   # message formatting and sending
  main.py       # orchestration, dedupe, CLI
tests/          # unit tests for the filters and formatting
config.yaml     # what to search for
```

## Tech

Python 3.12 · requests · PyYAML · pytest · GitHub Actions · Telegram Bot API
