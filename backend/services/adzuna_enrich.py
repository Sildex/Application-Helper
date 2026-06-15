"""Fetch full job descriptions from adzuna.de detail pages."""
import asyncio
import json
import re

import httpx

from app.log import _log_activity

_RE_AZ = re.compile(r'window\["az_details"\]\s*=\s*\{')

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _extract_description(html: str) -> str:
    m = _RE_AZ.search(html)
    if not m:
        return ""
    start = m.end() - 1
    depth = i = start
    while i < len(html):
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    try:
        data = json.loads(html[start:i + 1])
        return data.get("description", "")
    except Exception:
        return ""


async def _fetch_one(sem: asyncio.Semaphore, job_id: int, url: str) -> tuple[int, str]:
    async with sem:
        for ua in _USER_AGENTS:
            try:
                async with httpx.AsyncClient(
                    timeout=12,
                    follow_redirects=True,
                    headers={"User-Agent": ua},
                ) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        desc = _extract_description(r.text)
                        if desc:
                            return job_id, desc
                    elif r.status_code == 403:
                        continue  # try next UA
                    else:
                        break
            except Exception:
                break
        return job_id, ""


async def enrich_adzuna_jobs(jobs: list[dict], concurrency: int = 8) -> dict[int, str]:
    """Fetch full descriptions for Adzuna jobs. Returns {job_id: description}."""
    sem = asyncio.Semaphore(concurrency)
    tasks = [_fetch_one(sem, j["id"], j["url"]) for j in jobs]
    results = await asyncio.gather(*tasks)
    enriched = {job_id: desc for job_id, desc in results if desc}
    failed = len(jobs) - len(enriched)
    if failed:
        _log_activity(f"Adzuna enrich: {failed} jobs nicht abrufbar (403/Timeout)", "search")
    return enriched
