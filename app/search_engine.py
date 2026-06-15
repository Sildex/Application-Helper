"""Job search – runs in a background thread via asyncio.run().
Rule-based scoring only (no LLM) → fast, instantly cancellable.
"""
import asyncio
import re
import threading

from sqlmodel import Session, select

from app.filters import RE_TITLE_EXCLUDE as _RE_TITLE_EXCLUDE
from app.log import _log_activity
from backend.database import engine
from backend.models import Application, Job, JobSource
from backend.services import arbeitnow_api, ba_api, adzuna_api, himalayas_api
from backend.services.scorer import detect_category, score_job as rule_score

MAX_BA_JOBS    = 5000
MAX_AW_JOBS    = 2000
MAX_ADZUNA     = 3000
MIN_RULE_SCORE = 58  # base=40 → requires solid keyword/sector match to pass

KEYWORD_GROUPS = {
    "data_science": [
        "Data Analyst", "Data Scientist", "Junior Data Scientist",
        "Data Engineer", "Datenanalyst", "Business Intelligence Analyst",
        "BI Developer", "BI Analyst", "Datenauswertung",
    ],
    "ai_automation": [
        "Machine Learning", "Künstliche Intelligenz", "KI-Entwickler",
        "Prozessautomatisierung", "RPA Developer", "Automatisierung",
        "AI Analyst", "MLOps", "Prompt Engineer",
    ],
    "digitalisierung": [
        "Digitalisierung", "Verwaltungsdigitalisierung", "E-Government",
        "Digitaler Zwilling", "Industrie 4.0", "Digitalisierungsbeauftragter",
        "Digital Transformation",
    ],
    "wirtschaftsinformatik": [
        "Wirtschaftsinformatik", "Wirtschaftsinformatiker", "Business Analyst",
        "IT-Analyst", "Systemanalyst", "Requirements Engineer",
        "Prozessoptimierung", "Applikationsmanager",
    ],
    "security": [
        "IT-Security", "IT-Sicherheit", "Cybersecurity", "Cyber Security",
        "Information Security", "IT-Sicherheitsanalyst", "SOC Analyst",
        "IT-Sicherheitsbeauftragter",
    ],
}

_RE_GENDER = re.compile(r'\s*[\(\[]?\s*[mwfdx]\s*/\s*[mwfdx](\s*/\s*[mwfdx])?\s*[\)\]]?', re.IGNORECASE)


def _norm_job(title: str, company: str) -> tuple[str, str]:
    t = _RE_GENDER.sub("", title).lower().strip()
    t = re.sub(r'\s+', ' ', t)
    c = (company or "").lower().strip()
    return t, c

current_workspace: str = "default"

search_status: dict = {
    "running": False, "fetched": 0, "filtered": 0, "saved": 0,
    "phase": "Ready", "done": True,
}

_cancel = threading.Event()
_thread: threading.Thread | None = None


def start_search(on_done=None):
    global _thread
    if search_status["running"]:
        return
    _cancel.clear()
    _thread = threading.Thread(target=_run, args=(on_done,), daemon=True)
    _thread.start()


def cancel_search():
    _cancel.set()
    search_status["phase"] = "Cancelling…"


def _run(on_done=None):
    global search_status
    search_status = {
        "running": True, "fetched": 0, "filtered": 0, "saved": 0,
        "phase": "Fetching jobs…", "done": False,
    }
    _log_activity("Search engine started", "search")
    try:
        asyncio.run(_do_search())
    except Exception as exc:
        search_status["phase"] = f"Error: {exc}"
        _log_activity(f"Search error: {exc}", "search")
    finally:
        search_status["running"] = False
        search_status["done"]    = True
        _log_activity(f"Search done · {search_status['saved']} new jobs saved", "search")
        try:
            from app.db import save_last_search
            save_last_search(search_status["saved"])
        except Exception:
            pass
    if on_done:
        on_done()


async def _fetch_ba(kw: str, sem: asyncio.Semaphore) -> list[dict]:
    async with sem:
        if _cancel.is_set():
            return []
        try:
            return await ba_api.search_jobs(kw, max_results=25)
        except Exception:
            return []


async def _do_search():
    # deduplicate keywords
    seen_kw: set[str] = set()
    all_keywords: list[str] = []
    for kw in (kw for grp in KEYWORD_GROUPS.values() for kw in grp):
        if kw.lower() not in seen_kw:
            seen_kw.add(kw.lower())
            all_keywords.append(kw)

    seen_ids: set[str] = set()
    all_jobs: list[dict] = []

    # ── BA API (parallel, semaphore 10) ──────────────────────────────────────
    sem = asyncio.Semaphore(10)
    ba_tasks = [
        asyncio.ensure_future(_fetch_ba(kw, sem))
        for kw in all_keywords
    ]
    total_ba, completed_ba = len(ba_tasks), 0
    pending = set(ba_tasks)
    while pending:
        if _cancel.is_set(): break
        done, pending = await asyncio.wait(pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
        if _cancel.is_set(): break
        for task in done:
            completed_ba += 1
            for j in (task.result() or []):
                if j["external_id"] not in seen_ids and len(all_jobs) < MAX_BA_JOBS:
                    seen_ids.add(j["external_id"])
                    all_jobs.append(j)
        search_status["fetched"] = len(all_jobs)
        search_status["phase"]   = f"BA API  {completed_ba}/{total_ba}  ·  {len(all_jobs)} found"
        if completed_ba % 20 == 0 and completed_ba > 0:
            _log_activity(f"BA API  {completed_ba}/{total_ba} done  ·  {len(all_jobs)} fetched", "search")

    # ── Arbeitnow (single fetch, own quota) ──────────────────────────────────
    if not _cancel.is_set():
        aw_before = len(all_jobs)
        search_status["phase"] = f"Arbeitnow  ·  {aw_before} so far…"
        try:
            aw_jobs = await arbeitnow_api.fetch_jobs(all_keywords, max_results=MAX_AW_JOBS, max_pages=20)
            for j in aw_jobs:
                if _cancel.is_set(): break
                if j["external_id"] not in seen_ids:
                    seen_ids.add(j["external_id"])
                    all_jobs.append(j)
            _log_activity(f"Arbeitnow  {len(all_jobs) - aw_before} new  ·  {len(all_jobs)} total", "search")
        except Exception as exc:
            _log_activity(f"Arbeitnow error: {exc}", "search")
        search_status["fetched"] = len(all_jobs)

    # ── Adzuna, Jooble, Jobicy ───────────────────────────────────────────────
    try:
        from app.db import get_settings as _get_settings
        _prefs = _get_settings()["prefs"]
    except Exception:
        _prefs = {}

    _az_id  = _prefs.get("adzuna_app_id", "")
    _az_key = _prefs.get("adzuna_app_key", "")
    if not _az_id or not _az_key:
        _log_activity("Adzuna skipped — no API key in settings", "search")
        search_status["phase"] = "Adzuna: no API key → skipped"
    for country, source_name in [("de", "Adzuna DE"), ("at", "Adzuna AT"), ("ch", "Adzuna CH"), ("lu", "Adzuna LU")]:
        if _cancel.is_set(): break
        if not _az_id or not _az_key: break
        before = len(all_jobs)
        search_status["phase"] = f"{source_name}  ·  {before} so far…"
        try:
            tasks = [
                adzuna_api.search_jobs(kw, app_id=_az_id, app_key=_az_key,
                                       country=country, max_results=50)
                for kw in all_keywords
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, list):
                    for j in res:
                        if j["external_id"] not in seen_ids:
                            seen_ids.add(j["external_id"])
                            all_jobs.append(j)
            added = len(all_jobs) - before
            if added:
                _log_activity(f"{source_name}  {added} new  ·  {len(all_jobs)} total", "search")
        except Exception as exc:
            _log_activity(f"{source_name} error: {exc}", "search")

    # ── Himalayas (Germany remote jobs) ─────────────────────────────────────
    if not _cancel.is_set():
        before = len(all_jobs)
        search_status["phase"] = f"Himalayas  ·  {before} so far…"
        try:
            for j in await himalayas_api.fetch_jobs(all_keywords, max_results=300):
                if _cancel.is_set(): break
                if j["external_id"] not in seen_ids:
                    seen_ids.add(j["external_id"])
                    all_jobs.append(j)
            added = len(all_jobs) - before
            if added:
                _log_activity(f"Himalayas  {added} new  ·  {len(all_jobs)} total", "search")
        except Exception as exc:
            _log_activity(f"Himalayas error: {exc}", "search")

    search_status["fetched"] = len(all_jobs)

    if _cancel.is_set():
        search_status["phase"] = "Cancelled"
        return

    # ── Rule filter ───────────────────────────────────────────────────────────
    search_status["phase"] = f"Filtering {len(all_jobs)} jobs…"
    with Session(engine) as check_sess:
        existing_jobs = check_sess.exec(select(Job)).all()
        known_ids  = {j.external_id for j in existing_jobs}
        known_norm = {_norm_job(j.title, j.company or "") for j in existing_jobs}

    candidates = []
    seen_norm: set[tuple[str, str]] = set()
    for job_data in all_jobs:
        if job_data["external_id"] in known_ids:
            continue
        if _RE_TITLE_EXCLUDE.search(job_data.get("title", "")):
            continue
        if len((job_data.get("description") or "").strip()) < 100:
            continue
        norm_key = _norm_job(job_data.get("title", ""), job_data.get("company", ""))
        if norm_key in known_norm or norm_key in seen_norm:
            continue
        pre = rule_score(job_data["title"], job_data["description"], job_data.get("company", ""), job_data.get("location", ""))
        if pre["score"] >= MIN_RULE_SCORE:
            job_data["_pre"] = pre
            candidates.append(job_data)
            seen_norm.add(norm_key)

    if _cancel.is_set():
        search_status["phase"] = "Cancelled"
        return

    # ── Save to DB ────────────────────────────────────────────────────────────
    search_status["filtered"] = len(candidates)
    search_status["phase"] = f"Saving {len(candidates)} jobs…"
    with Session(engine) as session:
        for job_data in candidates:
            if _cancel.is_set(): break
            pre = job_data.pop("_pre")
            job_data.pop("_refnr", None)
            job_data["category"]         = detect_category(job_data["title"], job_data["description"])
            job_data["relevance_score"]  = pre["score"]
            job_data["relevance_reason"] = pre["reason"]
            job_data["workspace"]        = current_workspace

            exists = session.exec(
                select(Job).where(Job.external_id == job_data["external_id"])
            ).first()
            if exists:
                continue

            job = Job(**job_data)
            session.add(job)
            session.commit()
            session.refresh(job)
            session.add(Application(job_id=job.id))
            session.commit()
            search_status["saved"] += 1
            _log_activity(
                f"Saved [{pre['score']:>3}]  {job_data.get('title','')[:45]}  ·  {job_data.get('company','')[:25]}",
                "db"
            )

    if _cancel.is_set():
        search_status["phase"] = "Cancelled"
        return

    # ── Adzuna enrich: fetch full descriptions ────────────────────────────────
    from backend.services.adzuna_enrich import enrich_adzuna_jobs
    from app.db import update_job_description
    with Session(engine) as esess:
        adzuna_jobs = [
            {"id": j.id, "url": j.url}
            for j in esess.exec(select(Job).where(Job.source == JobSource.adzuna)).all()
            if j.url and (not j.description or len(j.description) <= 500)
        ]
    if adzuna_jobs:
        search_status["phase"] = f"Enriching {len(adzuna_jobs)} Adzuna jobs…"
        _log_activity(f"Adzuna enrich: {len(adzuna_jobs)} jobs", "search")
        enriched = await enrich_adzuna_jobs(adzuna_jobs)
        for job_id, desc in enriched.items():
            if desc:
                update_job_description(job_id, desc)
        _log_activity(f"Adzuna enrich: {len(enriched)} descriptions updated", "search")

    search_status["phase"] = f"Done  ·  {search_status['saved']} new jobs saved"
