"""Jobicy Remote Jobs API — https://jobicy.com/api — no auth required"""
import hashlib
from typing import Optional
from datetime import datetime

import httpx

SEARCH_URL = "https://jobicy.com/api/v2/remote-jobs"


def _make_external_id(url: str) -> str:
    return hashlib.md5(f"jobicy:{url}".encode()).hexdigest()


def _parse_job(raw: dict) -> Optional[dict]:
    url = raw.get("url", "")
    if not url:
        return None
    title = raw.get("jobTitle", "").strip()
    company = raw.get("companyName", "")
    location = raw.get("jobGeo", "") or "Remote"
    description = raw.get("jobDescription", "")
    pub_date = raw.get("pubDate", "")
    posted_at = None
    if pub_date:
        try:
            posted_at = datetime.fromisoformat(pub_date)
        except Exception:
            pass
    return {
        "external_id": _make_external_id(url),
        "source": "jobicy",
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
        "posted_at": posted_at,
        "extra_data": None,
    }


async def fetch_jobs(keywords: list[str], max_results: int = 100) -> list[dict]:
    """Fetch remote jobs — no auth needed. Filters by keywords client-side."""
    jobs: list[dict] = []
    kw_lower = [k.lower() for k in keywords]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(SEARCH_URL, params={"count": 50})
        if resp.status_code == 200:
            for raw in (resp.json().get("jobs") or []):
                parsed = _parse_job(raw)
                if not parsed:
                    continue
                text = (parsed["title"] + " " + parsed["description"]).lower()
                if any(kw in text for kw in kw_lower):
                    jobs.append(parsed)
                    if len(jobs) >= max_results:
                        break

    return jobs
