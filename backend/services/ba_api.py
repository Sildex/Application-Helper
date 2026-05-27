"""
Bundesagentur für Arbeit – Jobsuche REST API
Kein OAuth nötig – statischer X-API-Key Header reicht.
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

import httpx

SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
HEADERS = {"X-API-Key": "jobboerse-jobsuche"}


def _make_external_id(ref_nr: str) -> str:
    return hashlib.md5(f"ba:{ref_nr}".encode()).hexdigest()


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value[:10], fmt)
        except ValueError:
            continue
    return None


def _parse_job(raw: dict) -> Optional[dict]:
    ref_nr = raw.get("refnr")
    if not ref_nr:
        return None

    extra: dict = {}
    if raw.get("branchenbezeichnung"):
        extra["industry"] = raw["branchenbezeichnung"]
    elif isinstance(raw.get("branche"), dict):
        extra["industry"] = raw["branche"].get("bezeichnung", "")
    if raw.get("arbeitszeit"):
        extra["work_time"] = raw["arbeitszeit"]
    if raw.get("befristung"):
        extra["contract"] = raw["befristung"]
    region = raw.get("arbeitsort", {}).get("region", "")
    if region:
        extra["region"] = region
    land = raw.get("arbeitsort", {}).get("land", "")
    if land and land != "Deutschland":
        extra["country"] = land
    if raw.get("eintrittsdatum"):
        extra["start_date"] = raw["eintrittsdatum"]

    return {
        "external_id": _make_external_id(ref_nr),
        "source": "ba",
        "title": raw.get("titel") or raw.get("beruf", ""),
        "company": raw.get("arbeitgeber", ""),
        "location": raw.get("arbeitsort", {}).get("ort", ""),
        "description": raw.get("stellenbeschreibung") or raw.get("beruf", ""),
        "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref_nr}",
        "posted_at": _parse_date(raw.get("aktuelleVeroeffentlichungsdatum") or raw.get("eintrittsdatum")),
        "extra_data": json.dumps(extra, ensure_ascii=False) if extra else None,
    }


async def search_jobs(keywords: str, location: str, radius_km: int = 0, max_results: int = 25) -> list[dict]:
    jobs: list[dict] = []
    page = 1
    page_size = min(25, max_results)

    async with httpx.AsyncClient(timeout=3, headers=HEADERS) as client:
        while len(jobs) < max_results:
            params = {
                "was": keywords,
                "wo": location,
                "angebotsart": 1,
                "size": page_size,
                "page": page,
            }
            if radius_km > 0:
                params["umkreis"] = radius_km

            resp = await client.get(SEARCH_URL, params=params)
            if resp.status_code != 200:
                break

            raw_jobs = resp.json().get("stellenangebote") or []
            if not raw_jobs:
                break

            for raw in raw_jobs:
                parsed = _parse_job(raw)
                if parsed:
                    jobs.append(parsed)

            if len(raw_jobs) < page_size:
                break
            page += 1

    return jobs[:max_results]
