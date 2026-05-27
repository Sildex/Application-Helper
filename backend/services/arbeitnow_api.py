"""
Arbeitnow Job Board API – kostenlos, kein Key.
Die API unterstützt keinen Keyword-Filter – gibt immer dieselben paginierten Jobs.
Filterung erfolgt lokal nach Keywords.
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

import httpx

JOBS_URL = "https://www.arbeitnow.com/api/job-board-api"


def _make_external_id(slug: str) -> str:
    return hashlib.md5(f"arbeitnow:{slug}".encode()).hexdigest()


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value))
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(value)[:19])
        except ValueError:
            return None


def _parse_job(raw: dict) -> Optional[dict]:
    slug = raw.get("slug")
    if not slug:
        return None

    extra: dict = {}
    if raw.get("job_types"):
        extra["work_time"] = ", ".join(raw["job_types"])
    if raw.get("remote"):
        extra["remote"] = True
    if raw.get("tags"):
        extra["tags"] = raw["tags"][:8]
    if raw.get("language"):
        extra["language"] = raw["language"]

    return {
        "external_id": _make_external_id(slug),
        "source": "arbeitnow",
        "title": raw.get("title", ""),
        "company": raw.get("company_name", ""),
        "location": raw.get("location", ""),
        "description": raw.get("description", ""),
        "url": raw.get("url", f"https://www.arbeitnow.com/jobs/{slug}"),
        "posted_at": _parse_date(raw.get("created_at")),
        "extra_data": json.dumps(extra, ensure_ascii=False) if extra else None,
    }


async def fetch_jobs(keywords: list[str], max_results: int = 80, max_pages: int = 6) -> list[dict]:
    """Fetch pages from arbeitnow and filter locally by any of the given keywords."""
    kw_lower = [kw.lower() for kw in keywords]
    jobs: list[dict] = []
    seen_slugs: set[str] = set()
    page = 1

    async with httpx.AsyncClient(timeout=8) as client:
        while len(jobs) < max_results and page <= max_pages:
            try:
                resp = await client.get(JOBS_URL, params={"page": page})
                if resp.status_code != 200:
                    break
                data = resp.json()
                raw_jobs = data.get("data", [])
                if not raw_jobs:
                    break

                for raw in raw_jobs:
                    slug = raw.get("slug", "")
                    if slug in seen_slugs:
                        continue
                    title = (raw.get("title") or "").lower()
                    desc  = (raw.get("description") or "").lower()
                    if any(kw in title or kw in desc for kw in kw_lower):
                        parsed = _parse_job(raw)
                        if parsed:
                            seen_slugs.add(slug)
                            jobs.append(parsed)
                            if len(jobs) >= max_results:
                                break

                if not data.get("links", {}).get("next"):
                    break
            except Exception:
                break
            page += 1

    return jobs
