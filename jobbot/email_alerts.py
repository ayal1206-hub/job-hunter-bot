"""Relay job-alert emails (AllJobs, Drushim, ...) from Gmail to Telegram.

Job boards like AllJobs and Drushim don't allow scraping, but they do send
official "smart agent" alert emails. This module reads those emails over
IMAP (read-only), pulls out the job links, and forwards them to Telegram.

Needs two secrets: GMAIL_ADDRESS and GMAIL_APP_PASSWORD (a Google app
password, not the account password). Without them this step is skipped.
"""

import email
import email.message
import html
import imaplib
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.header import decode_header, make_header
from html.parser import HTMLParser

IMAP_HOST = "imap.gmail.com"

# Link texts that are navigation, not jobs.
_SKIP_TEXT = (
    "unsubscribe", "הסר", "הסרה", "לביטול", "ביטול", "הגדרות", "settings", "privacy",
    "פרטיות", "לכל המשרות", "view all", "צפה בכל", "לצפייה בכל", "עדכון", "התחבר",
    "login", "app store", "google play", "facebook", "instagram", "linkedin",
)


@dataclass
class AlertEmail:
    message_id: str
    sender: str
    subject: str
    jobs: list[tuple[str, str]] = field(default_factory=list)  # (title, url)


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            text = " ".join(" ".join(self._text).split())
            self.links.append((text, self._href))
            self._href = None


def extract_jobs(html_body: str, sender_domain: str, limit: int) -> list[tuple[str, str]]:
    """Return (title, url) for links that look like job postings."""
    parser = _LinkCollector()
    parser.feed(html_body)
    jobs, seen_urls = [], set()
    for text, url in parser.links:
        if not url.startswith("http") or len(text) < 4:
            continue
        if not any(domain in url for domain in (sender_domain, "click", "track", "link")):
            continue
        if any(skip in text.lower() for skip in _SKIP_TEXT):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        jobs.append((text, url))
        if len(jobs) >= limit:
            break
    return jobs


def _decode(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


def _html_part(msg: email.message.Message) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def fetch_alert_emails(address: str, app_password: str, senders: list[str],
                       lookback_days: int, max_jobs: int) -> list[AlertEmail]:
    since = (date.today() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    results = []
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(address, app_password)
        imap.select("INBOX", readonly=True)  # never changes the mailbox
        for domain in senders:
            status, data = imap.search(None, "SINCE", since, "FROM", domain)
            if status != "OK":
                continue
            for num in data[0].split():
                status, msg_data = imap.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                results.append(AlertEmail(
                    message_id=(msg.get("Message-ID") or f"{domain}-{num.decode()}").strip(),
                    sender=domain,
                    subject=_decode(msg.get("Subject")),
                    jobs=extract_jobs(_html_part(msg), domain, max_jobs),
                ))
    return results


def format_alert(alert: AlertEmail) -> str:
    lines = [f"📬 <b>{html.escape(alert.sender)}</b>: {html.escape(alert.subject)}"]
    for title, url in alert.jobs:
        lines.append(f'• <a href="{html.escape(url, quote=True)}">{html.escape(title)}</a>')
    if not alert.jobs:
        lines.append("(no job links found - open the email)")
    lines.append("📄 CV: General (Hebrew)")
    return "\n".join(lines)
