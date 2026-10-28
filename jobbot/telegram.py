"""Send alerts through the Telegram Bot API."""

import html
import time

import requests

API = "https://api.telegram.org/bot{token}/sendMessage"
EMPLOYMENT = {"student": "משרת סטודנט", "part": "משרה חלקית", "full": "משרה מלאה"}


def format_hot(entry: dict, app_url: str | None = None) -> str:
    """Immediate alert for a 🔥 job."""
    where = entry["location"] or {"south": "דרום", "center": "מרכז", "north": "צפון"}.get(entry["region"], "")
    lines = [
        f"🔥 <b>{html.escape(entry['title'])}</b>",
        f"🏢 {html.escape(entry['company'])}" + (f"  ·  📍 {html.escape(where)}" if where else ""),
        "✅ " + html.escape(" · ".join(entry["reasons"])),
        "📄 CV: " + ("Tech (English)" if entry["cv"] == "tech" else "General (Hebrew)"),
        f'<a href="{html.escape(entry["url"], quote=True)}">View and apply</a>',
    ]
    if app_url:
        lines.append(f'<a href="{html.escape(app_url, quote=True)}">All jobs</a>')
    return "\n".join(lines)


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
