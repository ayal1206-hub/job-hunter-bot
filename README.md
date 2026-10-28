# Job Hunter Bot

A small Python bot that scans the job boards of Israeli tech companies every few hours and sends me new student and junior openings on Telegram.

I built it to stop refreshing career pages by hand during my second year of a Computer Science degree. It runs for free on GitHub Actions and needs no server.

## How it works

```
GitHub Actions (every 4 hours)
        │
        ▼
 fetch jobs: Greenhouse, Lever, Comeet APIs  +  job-alert emails (Gmail IMAP)
        │
        ▼
 keep student / junior / possible-fit roles in Israel
        │
        ▼
 read each description → required years, part-time, hybrid, region → score
        │
        ├──► docs/jobs.json  ──►  Telegram mini app (GitHub Pages): filter by type, region, field
        │
        └──► 🔥 new top matches only  ──►  instant Telegram alert
```

- **Sources:** public JSON APIs of the applicant-tracking systems most Israeli tech companies use, plus the official alert emails of job sites that forbid scraping (AllJobs, Drushim), read from Gmail in read-only mode. That's how security, lifeguard and other non-tech jobs arrive.
- **Filtering:** a job is kept when it's in Israel and its title is student-level, junior QA/support, or a QA/support role with no seniority stated. Senior/lead/expert titles are dropped. Keywords work in English and Hebrew, with whole-word matching.
- **Scoring:** `scoring.py` reads the description and adds or removes points for level, required years of experience (English and Hebrew phrasing), part-time, hybrid, region (south is closest to me) and role. Every score comes with its reasons, shown in the app. Tiers: 🔥 apply now, 👍 worth a look, 🤔 long shot.
- **App:** `docs/index.html` is a Telegram Mini App with no backend: it loads `jobs.json`, filters on the device, and remembers which jobs I applied to via Telegram CloudStorage.
- **State:** `seen.json` (alerted jobs), `docs/jobs.json` (current list, keeps first-seen dates) and `data/facts.json` (cached description facts, so each page is read once) are committed back by the workflow.
- **Robustness:** a board that fails is skipped and reported; email problems never break a run; the run fails only if every board fails.

Applications are always sent by me. The bot only finds, sorts and reports.

## Configuration

Everything lives in [`config.yaml`](config.yaml): locations, keywords per track, and the list of companies. Adding a company is one line.

To see which boards work and how many local jobs each has, run the workflow manually with **check** enabled, or:

```bash
python -m jobbot.main --check
```

## Running it yourself

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and get your chat id.
2. Add two repository secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   Optional, for the email relay: `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (a Google app password).
3. Enable GitHub Actions, and set **Settings → Pages → Source** to **GitHub Actions**.
4. In @BotFather: `/setmenubutton` → your bot → the Pages URL. The app opens from the bot's menu button.

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
  email_alerts.py  # Gmail IMAP reader for job-site alert emails
  details.py    # job page → plain text
  scoring.py    # description facts + relevance score
  pipeline.py   # builds the scored list for the app
  telegram.py   # message formatting and sending
  main.py       # orchestration, dedupe, CLI
tests/          # unit tests for the filters and formatting
docs/index.html # the Telegram mini app
config.yaml     # what to search for
```

## Tech

Python 3.12 · requests · PyYAML · pytest · GitHub Actions · GitHub Pages · Telegram Bot API · Telegram Mini Apps · vanilla JS
