"""Interamt – Stellenportal für den öffentlichen Dienst."""
import hashlib
import json
from datetime import datetime
from typing import Optional

import httpx

SEARCH_URL = "https://interamt.de/koop/app/trefferliste"
HEADERS    = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


def _make_id(job_id) -> str:
    return hashlib.md5(f"interamt:{job_id}".encode()).hexdigest()


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_job(raw: dict) -> Optional[dict]:
    job_id = raw.get("id") or raw.get("stelleId")
    if not job_id:
        return None
    title   = raw.get("bezeichnung") or raw.get("titel") or ""
    company = raw.get("behoerde") or raw.get("einrichtung") or ""
    ort     = (raw.get("einsatzort") or {}).get("ort", "") if isinstance(raw.get("einsatzort"), dict) else raw.get("dienstort", "")
    extra: dict = {}
    if raw.get("berufsfeld"):
        extra["field"] = raw["berufsfeld"]
    if raw.get("besoldung") or raw.get("entgeltgruppe"):
        extra["pay"] = raw.get("besoldung") or raw.get("entgeltgruppe", "")
    return {
        "external_id": _make_id(job_id),
        "source":      "interamt",
        "title":       title,
        "company":     company,
        "location":    ort,
        "description": raw.get("beschreibung") or raw.get("aufgaben") or title,
        "url":         f"https://interamt.de/koop/app/stelle?id={job_id}",
        "posted_at":   _parse_date(raw.get("veroeffentlichungsdatum") or raw.get("einstellungsdatum")),
        "extra_data":  json.dumps(extra, ensure_ascii=False) if extra else None,
    }


async def search_jobs(keyword: str, max_results: int = 50) -> list[dict]:
    jobs: list[dict] = []
    page = 0
    async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
        while len(jobs) < max_results:
            params = {
                "bezeichnung": keyword,
                "angebotsart": "Stellen",
                "page":        page,
                "size":        min(50, max_results - len(jobs)),
            }
            try:
                resp = await client.get(SEARCH_URL, params=params)
                if resp.status_code != 200:
                    break
                data = resp.json()
                items = data.get("content") or data.get("stellenangebote") or []
                if not items:
                    break
                for raw in items:
                    parsed = _parse_job(raw)
                    if parsed:
                        jobs.append(parsed)
                if len(items) < 50 or data.get("last", True):
                    break
                page += 1
            except Exception:
                break
    return jobs[:max_results]
