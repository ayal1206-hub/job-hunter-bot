"""Send alerts through the Telegram Bot API."""

import html
import time

import requests

from .filters import Match
from .models import Job

API = "https://api.telegram.org/bot{token}/sendMessage"


def format_job(job: Job, match: Match) -> str:
    level = "🎓 Student" if match.level == "student" else "🌱 Junior"
    return (
        f"<b>{html.escape(job.title)}</b>\n"
        f"🏢 {html.escape(job.company)}\n"
        f"📍 {html.escape(job.location or 'Not specified')}\n"
        f"{level} · {html.escape(match.track_label)}\n"
        f"📄 CV: Tech (English)\n"
        f'<a href="{html.escape(job.url, quote=True)}">View and apply</a>'
    )


class Telegram:
    def __init__(self, token: str | None, chat_id: str | None):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            print("--- (dry run, Telegram not configured) ---")
            print(text)
            return
        resp = requests.post(
            API.format(token=self.token),
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if resp.status_code == 429:
            retry = resp.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(retry)
            return self.send(text)
        resp.raise_for_status()
        time.sleep(1)  # stay well under Telegram's rate limits
