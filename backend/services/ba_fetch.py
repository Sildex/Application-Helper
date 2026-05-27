"""Fetch full BA job description via Angular SSR ng-state embedded JSON."""
import json
import re

import httpx

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _md_to_text(text: str) -> str:
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^\s*[-*+]\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def fetch_description(refnr: str) -> str:
    """Extract full description from Angular SSR ng-state on BA job page."""
    url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
    try:
        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""

            # Force UTF-8 — httpx may detect wrong charset from headers
            html = resp.content.decode("utf-8", errors="replace")

            m = re.search(r'<script\s+id="ng-state"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                return ""

            state = json.loads(m.group(1))
            desc = (
                state.get("jobdetail", {}).get("stellenangebotsBeschreibung")
                or state.get("jobdetail", {}).get("stellenbeschreibung")
                or ""
            )
            if desc and len(desc.strip()) > 80:
                return _md_to_text(desc)
    except Exception:
        pass
    return ""
