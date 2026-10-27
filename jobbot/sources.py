"""Fetchers for public job-board APIs.

Each fetcher returns a list of Job objects, or raises SourceError when the
board can't be read (wrong token, company moved to another ATS, network error).
"""

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
    host = "boards-api.eu.greenhouse.io" if company.get("region") == "eu" else "boards-api.greenhouse.io"
    data = _get_json(f"https://{host}/v1/boards/{company['token']}/jobs")
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(Job(
            source="greenhouse",
            company=company["name"],
            job_id=str(item["id"]),
            title=item.get("title", "").strip(),
            location=(item.get("location") or {}).get("name", "").strip(),
            url=item.get("absolute_url", ""),
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
        ))
    return jobs


def fetch_comeet(company: dict) -> list[Job]:
    url = f"https://www.comeet.co/careers-api/2.0/company/{company['uid']}/positions"
    data = _get_json(url, params={"token": company["token"], "details": "false"})
    if not isinstance(data, list):
        raise SourceError("unexpected response shape")
    jobs = []
    for item in data:
        loc = item.get("location") or {}
        location = ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
        jobs.append(Job(
            source="comeet",
            company=company["name"],
            job_id=str(item.get("uid", "")),
            title=item.get("name", "").strip(),
            location=location,
            url=item.get("url_active_page") or item.get("url_comeet_hosted_page", ""),
        ))
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "comeet": fetch_comeet,
}
