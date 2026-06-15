"""Adzuna Deutschland Job API — https://developer.adzuna.com/"""
import hashlib
import html
import re
from typing import Optional
from datetime import datetime

import httpx

_RE_CONTACT = re.compile(
    r'(Telefon|Tel\.|E-Mail|Fax|Stellennr\.?|Ansprechpartner|Inhaber)[:\s][^\n]{0,80}\n?',
    re.IGNORECASE,
)
_RE_WHITESPACE = re.compile(r'[ \t]{2,}')

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


def _make_external_id(url: str) -> str:
    return hashlib.md5(f"adzuna:{url}".encode()).hexdigest()


def _clean_description(text: str) -> str:
    if not text:
        return text
    text = _RE_CONTACT.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _RE_WHITESPACE.sub(" ", text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _parse_job(raw: dict) -> Optional[dict]:
    url = raw.get("redirect_url", "")
    if not url:
        return None
    title = html.unescape(raw.get("title", "")).strip()
    company = html.unescape((raw.get("company") or {}).get("display_name", ""))
    location = html.unescape((raw.get("location") or {}).get("display_name", ""))
    description = _clean_description(html.unescape(raw.get("description", "")))
    created = raw.get("created", "")
    posted_at = None
    if created:
        try:
            posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            pass
    return {
        "external_id": _make_external_id(url),
        "source": "adzuna",
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
        "posted_at": posted_at,
        "extra_data": None,
    }


async def search_jobs(keywords: str, app_id: str, app_key: str,
                      country: str = "de", max_results: int = 50) -> list[dict]:
    if not app_id or not app_key:
        return []
    jobs: list[dict] = []
    page = 1
    per_page = min(50, max_results)

    async with httpx.AsyncClient(timeout=10) as client:
        while len(jobs) < max_results:
            resp = await client.get(
                SEARCH_URL.format(country=country, page=page),
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": keywords,
                    "results_per_page": per_page,
                    "sort_by": "date",
                    "content-type": "application/json",
                },
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            raw_jobs = data.get("results") or []
            if not raw_jobs:
                break
            for raw in raw_jobs:
                parsed = _parse_job(raw)
                if parsed:
                    jobs.append(parsed)
            if len(raw_jobs) < per_page:
                break
            page += 1

    return jobs[:max_results]
