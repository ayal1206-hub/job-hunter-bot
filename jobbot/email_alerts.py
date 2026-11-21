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
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.header import decode_header, make_header
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .filters import _any

IMAP_HOST = "imap.gmail.com"

# Link texts that are navigation, not jobs.
_SKIP_TEXT = (
    "unsubscribe", "הסר", "הסרה", "לביטול", "ביטול", "הגדרות", "settings", "privacy",
    "פרטיות", "לכל המשרות", "view all", "צפה בכל", "לצפייה בכל", "עדכון", "התחבר",
    "login", "app store", "google play", "facebook", "instagram", "linkedin",
)


# Account emails from the same senders (welcome, verification...) are not job alerts.
_NOT_ALERT_SUBJECT = (
    "ברוך הבא", "ברוכה הבאה", "ברוכים הבאים", "welcome", "קוד אימות", "אימות כתובת", "אימות המייל", "אימות חשבון", "אמת את", "verify", "confirm",
    "סיסמה", "password", "הרשמה", "נרשמת", "פרופיל", "profile", "קורות החיים שלך", "תודה",
)


def is_job_alert(subject: str) -> bool:
    s = subject.lower()
    return not any(word in s for word in _NOT_ALERT_SUBJECT)


@dataclass
class AlertEmail:
    message_id: str
    sender: str
    subject: str
    # (title, url, company, location[, details]); "" when the email doesn't say.
    jobs: list[tuple] = field(default_factory=list)
    uid: str = ""   # IMAP UID in All Mail, used to mark the email as read once handled


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


class _LinkedInCollector(HTMLParser):
    """LinkedIn job-alert digests: each job is a link to /jobs/view/<id>/ whose text is the
    title, followed by a <p> with "Company · Location"."""

    def __init__(self):
        super().__init__()
        self.jobs: dict[str, list[str]] = {}   # job id -> [title, company, location]
        self._in_title: str | None = None
        self._title_text: list[str] = []
        self._await_meta: str | None = None
        self._in_p = False
        self._p_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            m = re.search(r"/jobs/view/(\d+)", dict(attrs).get("href") or "")
            self._in_title = m.group(1) if m else None
            self._title_text = []
        elif tag == "p" and self._await_meta:
            self._in_p, self._p_text = True, []

    def handle_data(self, data):
        if self._in_title:
            self._title_text.append(data)
        if self._in_p:
            self._p_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title:
            title = " ".join(" ".join(self._title_text).split())
            if title and self._in_title not in self.jobs:   # the image link before it has no text
                self.jobs[self._in_title] = [title, "", ""]
                self._await_meta = self._in_title
            self._in_title = None
        elif tag == "p" and self._in_p:
            meta = " ".join(" ".join(self._p_text).split())
            company, _, location = meta.partition(" · ")
            self.jobs[self._await_meta][1:] = [company.strip(), location.strip()]
            self._in_p, self._await_meta = False, None


def extract_linkedin_jobs(html_body: str, limit: int) -> list[tuple[str, str, str, str]]:
    parser = _LinkedInCollector()
    parser.feed(html_body)
    return [(title, f"https://www.linkedin.com/jobs/view/{job_id}/", company, location)
            for job_id, (title, company, location) in list(parser.jobs.items())[:limit]]


def _plain(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


_AJ_TITLE = re.compile(r"<td[^>]*font-size:\s*13pt;\s*font-weight:\s*bold[^>]*>(.*?)</td>", re.S | re.I)


def extract_alljobs_jobs(html_body: str, limit: int) -> list[tuple[str, str, str, str, str]]:
    """AllJobs alert cards: title, company, workplace, job type, a short description and a
    personal redirect link. The link carries the user's id and key, so only the job id is
    kept and a public job URL is built from it."""
    jobs, seen = [], set()
    starts = list(_AJ_TITLE.finditer(html_body))
    for i, m in enumerate(starts):
        chunk = html_body[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(html_body)]
        title = _plain(m.group(1))
        job_id = re.search(r"JobIDs?=(\d+)", chunk)
        if not title or not job_id or job_id.group(1) in seen:
            continue
        seen.add(job_id.group(1))

        def field(label):
            f = re.search(label + r"\s*:?\s*</strong>\s*(?:</span>)?(.*?)</td>", chunk, re.S)
            return _plain(f.group(1)) if f else ""

        company = field("חברה")
        desc = re.search(r'class="LH"[^>]*>(.*?)</td>', chunk, re.S)
        details = " ".join(p for p in (field("סוג משרה"), _plain(desc.group(1)) if desc else "") if p)
        jobs.append((title, f"https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID={job_id.group(1)}",
                     "" if company == "אחר" else company, field("מקום העבודה"), details))
        if len(jobs) >= limit:
            break
    return jobs


_PERSONAL_PARAM = re.compile(r"(user|uid|key|token|email|mail|hash|sig|auth|session|utm_|ref|trk)", re.I)


def _public_url(url: str) -> str:
    """Drop query parameters that identify the recipient (the job list is public)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _PERSONAL_PARAM.search(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def extract_jobs(html_body: str, sender_domain: str, limit: int) -> list[tuple]:
    """(title, url, company, location[, details]) for each job in an alert email."""
    if "linkedin.com" in sender_domain:
        return extract_linkedin_jobs(html_body, limit)
    if "alljob" in sender_domain:
        cards = extract_alljobs_jobs(html_body, limit)
        if cards:
            return cards
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
        url = _public_url(url)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        jobs.append((text, url, "", ""))
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


def _all_mail(imap) -> str:
    """Gmail's "All Mail" folder (its name depends on the account language), so alerts are
    found even when they were read, archived or sorted into a tab. Falls back to INBOX."""
    try:
        status, folders = imap.list()
    except Exception:
        return "INBOX"
    if status != "OK":
        return "INBOX"
    for line in folders or []:
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        if "\\All" in text:
            name = text.rsplit(' "/" ', 1)[-1].strip()
            return name if name.startswith('"') else f'"{name}"'
    return "INBOX"


def fetch_alert_emails(address: str, app_password: str, senders: list[str],
                       lookback_days: int, max_jobs: int) -> list[AlertEmail]:
    since = (date.today() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    results = []
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(address, app_password)
        imap.select(_all_mail(imap), readonly=True)  # reading never changes the mailbox
        for domain in senders:
            status, data = imap.uid("search", None, "SINCE", since, "FROM", domain)
            if status != "OK":
                continue
            for num in data[0].split():
                status, msg_data = imap.uid("fetch", num, "(BODY.PEEK[])")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                if not is_job_alert(_decode(msg.get("Subject"))):
                    continue
                results.append(AlertEmail(
                    message_id=(msg.get("Message-ID") or f"{domain}-{num.decode()}").strip(),
                    sender=domain,
                    subject=_decode(msg.get("Subject")),
                    jobs=extract_jobs(_html_part(msg), domain, max_jobs),
                    uid=num.decode(),
                ))
    return results


def mark_as_read(address: str, app_password: str, alerts: list[AlertEmail]) -> int:
    """Mark the alert emails the bot handled as read, so the unread ones in Gmail are the ones
    it hasn't gone through (or couldn't read). Only emails with at least one job are marked:
    an email the bot found no jobs in stays unread for a human to open. Changes nothing else."""
    uids = sorted({a.uid for a in alerts if a.uid and a.jobs}, key=int)
    if not uids:
        return 0
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(address, app_password)
        imap.select(_all_mail(imap))   # read-write, only to set the \Seen flag
        status, _ = imap.uid("store", ",".join(uids), "+FLAGS", "(\\Seen)")
    return len(uids) if status == "OK" else 0


def is_tech(title: str, cfg: dict | None) -> bool:
    """True when the title matches any role track (QA, support, dev, tech)."""
    if not cfg:
        return False
    text = title.lower()
    return any(_any(text, t["keywords"]) for t in cfg.get("tracks", {}).values())


def format_alert(alert: AlertEmail, cfg: dict | None = None) -> str:
    lines = [f"📬 <b>{html.escape(alert.sender)}</b>: {html.escape(alert.subject)}"]
    tech_flags = []
    for title, url, *_ in alert.jobs:
        tech = is_tech(title, cfg)
        tech_flags.append(tech)
        icon = "💻" if tech else "•"
        lines.append(f'{icon} <a href="{html.escape(url, quote=True)}">{html.escape(title)}</a>')
    if not alert.jobs:
        lines.append("(no job links found - open the email)")

    if tech_flags and all(tech_flags):
        lines.append("📄 CV: Tech (English)")
    elif any(tech_flags):
        lines.append("📄 CV: 💻 = Tech (English), • = General (Hebrew)")
    else:
        lines.append("📄 CV: General (Hebrew)")
    return "\n".join(lines)
