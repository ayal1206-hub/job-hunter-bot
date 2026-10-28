"""Download a job's page and turn it into plain text for scoring.

Job pages are a mix of server-rendered HTML and JSON embedded in <script>
tags (Comeet), so script contents are kept and \\uXXXX escapes are decoded
to make Hebrew text searchable.
"""

import html as html_lib
import re

import requests

from .sources import HEADERS, TIMEOUT

_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"<style\b.*?</style>", re.S | re.I)
_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_SPACES = re.compile(r"\s+")


def page_to_text(page: str) -> str:
    text = _STYLE.sub(" ", page)
    text = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = text.replace("\\n", " ").replace("\\/", "/")
    text = _TAG.sub(" ", text)
    text = html_lib.unescape(text)
    # Embedded JSON may itself contain escaped HTML tags.
    text = _TAG.sub(" ", text)
    return _SPACES.sub(" ", text)


def fetch_description(url: str) -> str:
    """Plain text of the job page, or "" if it can't be fetched."""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return ""
    if resp.status_code != 200:
        return ""
    return page_to_text(resp.text)
