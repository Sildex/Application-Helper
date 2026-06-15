"""Himalayas Remote Jobs API — https://himalayas.app/api — no auth required"""
import hashlib
import html
import re
from datetime import datetime
from typing import Optional

import httpx

SEARCH_URL = "https://himalayas.app/jobs/api/search"
BROWSE_URL = "https://himalayas.app/jobs/api"

_RE_BLOCK = re.compile(r'<(br|p|li|h[1-6]|div|tr|ul|ol|section|article)(\s[^>]*)?>',
                       re.IGNORECASE)
_RE_TAGS  = re.compile(r'<[^>]+>')
_RE_WS    = re.compile(r'[ \t]{2,}')
_RE_NL    = re.compile(r'\n{3,}')

# Only these seniority levels are relevant
_OK_SENIORITY = {"Entry-level", "Mid-level", ""}
_OK_LOCATIONS = {"germany", "austria", "switzerland", "europe", "worldwide", "dach", ""}



def _make_external_id(guid: str) -> str:
    return hashlib.md5(f"himalayas:{guid}".encode()).hexdigest()


def _clean_html(text: str) -> str:
    text = html.unescape(text or "")
    text = _RE_BLOCK.sub("\n", text)
    text = _RE_TAGS.sub("", text)
    text = _RE_WS.sub(" ", text)
    text = _RE_NL.sub("\n\n", text)
    return text.strip()


def _parse_job(raw: dict) -> Optional[dict]:
    url = raw.get("applicationLink") or raw.get("guid", "")
    if not url:
        return None
    seniority = (raw.get("seniority") or [])
    if seniority and not any(s in _OK_SENIORITY for s in seniority):
        return None  # skip Senior / Director
    location_list = raw.get("locationRestrictions") or []
    if location_list and not any(loc.lower() in _OK_LOCATIONS for loc in location_list):
        return None  # skip non-EU / non-worldwide jobs
    title = (raw.get("title") or "").strip()
    company = raw.get("companyName") or ""
    location = ", ".join(location_list) if location_list else "Remote"
    description = _clean_html(raw.get("description") or raw.get("excerpt") or "")
    pub = raw.get("pubDate") or ""
    posted_at = None
    if pub:
        try:
            posted_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            pass
    return {
        "external_id": _make_external_id(raw.get("guid") or url),
        "source": "himalayas",
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
        "posted_at": posted_at,
        "extra_data": None,
    }


async def fetch_jobs(keywords: list[str], max_results: int = 300) -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    kw_lower = [k.lower() for k in keywords]

    async with httpx.AsyncClient(timeout=12) as client:
        # 1) Keyword search per term with DE filter
        for kw in keywords:
            if len(jobs) >= max_results:
                break
            resp = await client.get(SEARCH_URL, params={
                "q": kw, "countryCode": "DE", "limit": 20,
            })
            if resp.status_code != 200:
                continue
            for raw in (resp.json().get("jobs") or []):
                parsed = _parse_job(raw)
                if not parsed or parsed["external_id"] in seen:
                    continue
                seen.add(parsed["external_id"])
                jobs.append(parsed)

        # 2) Worldwide jobs — keyword search, client-side keyword filter
        for kw in keywords:
            if len(jobs) >= max_results:
                break
            resp = await client.get(SEARCH_URL, params={
                "q": kw, "worldwide": "true", "limit": 20,
            })
            if resp.status_code != 200:
                continue
            for raw in (resp.json().get("jobs") or []):
                parsed = _parse_job(raw)
                if not parsed or parsed["external_id"] in seen:
                    continue
                seen.add(parsed["external_id"])
                jobs.append(parsed)

    return jobs[:max_results]
