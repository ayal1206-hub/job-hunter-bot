"""Fetchers for public job-board APIs.

Each fetcher returns a list of Job objects, or raises SourceError when the
board can't be read (wrong token, company moved to another ATS, network error).
"""

import json
import re

import requests

from .models import Job

TIMEOUT = 20
HEADERS = {"User-Agent": "job-hunter-bot (personal job alerts)"}


class SourceError(Exception):
    pass


def _get_json(url: str, params: dict | None = None):
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SourceError(f"network error: {exc}") from exc
    if resp.status_code != 200:
        raise SourceError(f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError("response was not JSON") from exc


def fetch_greenhouse(company: dict) -> list[Job]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{company['token']}/jobs",
                     params={"content": "true"})
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(Job(
            source="greenhouse",
            company=company["name"],
            job_id=str(item["id"]),
            title=item.get("title", "").strip(),
            location=(item.get("location") or {}).get("name", "").strip(),
            url=item.get("absolute_url", ""),
            description=item.get("content", ""),  # HTML-escaped HTML; cleaned by details.page_to_text
        ))
    return jobs


def fetch_lever(company: dict) -> list[Job]:
    data = _get_json(f"https://api.lever.co/v0/postings/{company['slug']}", params={"mode": "json"})
    if not isinstance(data, list):
        raise SourceError("unexpected response shape")
    jobs = []
    for item in data:
        categories = item.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location", "")]
        jobs.append(Job(
            source="lever",
            company=company["name"],
            job_id=str(item["id"]),
            title=item.get("text", "").strip(),
            location=" / ".join(loc for loc in locations if loc),
            url=item.get("hostedUrl", ""),
            description=item.get("descriptionPlain", "") + " " + " ".join(
                " ".join(li.get("content", "") for li in lst.get("content", []) if isinstance(li, dict))
                if isinstance(lst.get("content"), list) else str(lst.get("content", ""))
                for lst in item.get("lists", []) if isinstance(lst, dict)),
        ))
    return jobs


DEBUG_DIR = None  # set by check mode to save pages that couldn't be parsed


def _comeet_jobs(company: dict, items: list) -> list[Job]:
    jobs = []
    for item in items:
        if not isinstance(item, dict):
            continue
        loc = item.get("location") or {}
        if isinstance(loc, dict):
            location = loc.get("name") or ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
        else:
            location = str(loc)
        jobs.append(Job(
            source="comeet",
            company=company["name"],
            job_id=str(item.get("uid", "")),
            title=(item.get("name") or "").strip(),
            location=location or "",
            url=item.get("url_active_page") or item.get("url_comeet_hosted_page") or "",
            description=" ".join(
                str(d.get("value", "")) for d in (item.get("details") or []) if isinstance(d, dict)),
        ))
    return jobs


def _extract_json_array(text: str, start: int):
    """Parse the JSON array that begins at text[start] ('[')."""
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
        return value
    except ValueError:
        return None


def fetch_comeet(company: dict) -> list[Job]:
    """Comeet: use the API when a token is configured, otherwise read the
    public hosted careers page (comeet.com/jobs/<slug>/<uid>), which embeds
    the open positions as JSON."""
    if company.get("token"):
        url = f"https://www.comeet.co/careers-api/2.0/company/{company['uid']}/positions"
        data = _get_json(url, params={"token": company["token"], "details": "true"})
        if not isinstance(data, list):
            raise SourceError("unexpected response shape")
        return _comeet_jobs(company, data)

    page_url = f"https://www.comeet.com/jobs/{company['slug']}/{company['uid']}"
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SourceError(f"network error: {exc}") from exc
    if resp.status_code != 200:
        raise SourceError(f"HTTP {resp.status_code}")
    html = resp.text

    # 1) positions embedded in the page
    m = re.search(r"COMPANY_POSITIONS_DATA\s*=\s*\[", html)
    if m:
        data = _extract_json_array(html, m.end() - 1)
        if isinstance(data, list):
            return _comeet_jobs(company, data)

    # 2) an API token embedded in the page
    t = re.search(r'["\']?token["\']?\s*[:=]\s*["\']([A-Za-z0-9]{8,})["\']', html)
    if t:
        return fetch_comeet({**company, "token": t.group(1)})

    if DEBUG_DIR is not None:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{company['slug']}.html").write_text(html, encoding="utf-8")
    raise SourceError("no positions data found in page")


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "comeet": fetch_comeet,
}
