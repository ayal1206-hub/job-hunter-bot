"""One-off probe of a site's public structure, run from GitHub Actions (check mode).

Records robots.txt and the API endpoints referenced by the site's JavaScript,
so we can decide whether (and how) a source may be added. Read-only, a handful
of requests.
"""

import re
from pathlib import Path

import requests

from .sources import HEADERS, TIMEOUT

TARGETS = ["https://namerz.moin.gov.il/namer"]


def _get(url: str) -> tuple[int, str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        return r.status_code, r.text
    except requests.RequestException as exc:
        return 0, f"ERROR {exc}"


def probe(url: str) -> str:
    base = re.match(r"https?://[^/]+", url).group(0)
    out = [f"# {url}"]
    code, robots = _get(base + "/robots.txt")
    out += [f"robots.txt -> HTTP {code}", robots[:1500], ""]
    code, html = _get(url)
    out += [f"page -> HTTP {code}, {len(html)} bytes"]
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    out += ["scripts: " + ", ".join(scripts)]
    endpoints = set()
    for src in scripts[:8]:
        full = src if src.startswith("http") else base + "/" + src.lstrip("/")
        c, js = _get(full)
        out.append(f"  {full} -> HTTP {c}, {len(js)} bytes")
        for m in re.finditer(r'["\'`]((?:https?://[^"\'`\s]+)?/?[\w\-./]*(?:api|Api|API|odata|service|Service)[\w\-./?=&{}$]*)["\'`]', js):
            endpoints.add(m.group(1))
    out += ["endpoints found in JS:"] + [f"  {e}" for e in sorted(endpoints)[:200]]
    return "\n".join(out)


def run(report_dir: Path) -> None:
    text = "\n\n".join(probe(u) for u in TARGETS)
    report_dir.mkdir(exist_ok=True)
    (report_dir / "probe.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
