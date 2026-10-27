from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import jobbot.email_alerts as ea

SAMPLE_HTML = """
<html><body dir="rtl">
<a href="https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=111">מאבטח/ת לובי - באר שבע</a>
<a href="https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=222"><b>מציל/ה לבריכה</b> - אשקלון</a>
<a href="https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=111">מאבטח/ת לובי - באר שבע</a>
<a href="https://www.alljobs.co.il/settings">הגדרות סוכן</a>
<a href="https://www.alljobs.co.il/unsub?u=1">להסרה מרשימת התפוצה</a>
<a href="https://www.facebook.com/alljobs">Facebook</a>
<a href="mailto:x@y.com">צור קשר</a>
</body></html>
"""


def test_extract_jobs_keeps_only_job_links():
    jobs = ea.extract_jobs(SAMPLE_HTML, "alljobs.co.il", limit=10)
    assert jobs == [
        ("מאבטח/ת לובי - באר שבע", "https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=111"),
        ("מציל/ה לבריכה - אשקלון", "https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=222"),
    ]


def test_extract_jobs_respects_limit():
    assert len(ea.extract_jobs(SAMPLE_HTML, "alljobs.co.il", limit=1)) == 1


def _raw_email():
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "=?utf-8?b?" + __import__("base64").b64encode("2 משרות חדשות עבורך".encode()).decode() + "?="
    msg["From"] = "agent@alljobs.co.il"
    msg["Message-ID"] = "<abc@alljobs>"
    msg.attach(MIMEText("plain version", "plain", "utf-8"))
    msg.attach(MIMEText(SAMPLE_HTML, "html", "utf-8"))
    return msg.as_bytes()


class FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL."""
    selected_readonly = None

    def __init__(self, host):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        assert pw == "apppassword"

    def select(self, box, readonly=False):
        FakeIMAP.selected_readonly = readonly
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        return "OK", [b"1" if "alljobs.co.il" in criteria else b""]

    def fetch(self, num, parts):
        assert "PEEK" in parts  # must not mark emails as read
        return "OK", [(b"1", _raw_email())]


def test_fetch_alert_emails_reads_mailbox_readonly():
    monkeypatch_target = ea.imaplib
    original = monkeypatch_target.IMAP4_SSL
    monkeypatch_target.IMAP4_SSL = FakeIMAP
    try:
        alerts = ea.fetch_alert_emails("me@gmail.com", "apppassword",
                                       ["alljobs.co.il", "drushim.co.il"], 3, 10)
    finally:
        monkeypatch_target.IMAP4_SSL = original
    assert FakeIMAP.selected_readonly is True
    assert len(alerts) == 1
    a = alerts[0]
    assert a.message_id == "<abc@alljobs>"
    assert a.subject == "2 משרות חדשות עבורך"
    assert len(a.jobs) == 2
    text = ea.format_alert(a)
    assert "📄 CV: General (Hebrew)" in text
    assert "JobID=222" in text


def test_cv_label_follows_job_type():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    mk = lambda titles: ea.AlertEmail("id", "alljobs.co.il", "s", [(t, "https://x/" + t) for t in titles])
    assert "CV: Tech (English)" in ea.format_alert(mk(["סטודנט/ית QA", "סטודנט לתמיכה טכנית"]), cfg)
    assert "CV: General (Hebrew)" in ea.format_alert(mk(["מאבטח/ת לובי", "מציל/ה לבריכה"]), cfg)
    mixed = ea.format_alert(mk(["סטודנט פיתוח תוכנה", "מאבטח/ת"]), cfg)
    assert "💻 = Tech (English)" in mixed and "💻 <a" in mixed and "• <a" in mixed
