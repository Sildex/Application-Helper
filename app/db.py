"""Direct DB helpers – no FastAPI."""
import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from backend.database import engine
from backend.models import Application, ApplicationStatus, Config, CoverLetter, Job



def _get_config(session: Session) -> Config:
    cfg = session.get(Config, 1)
    if not cfg:
        cfg = Config(
            profile_json=json.dumps(_DEFAULT_PROFILE),
            preferences_json=json.dumps(_DEFAULT_PREFS),
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def get_settings() -> dict:
    with Session(engine) as session:
        cfg = _get_config(session)
        profile = {**_DEFAULT_PROFILE, **json.loads(cfg.profile_json)}
        prefs = {**_DEFAULT_PREFS, **json.loads(cfg.preferences_json)}
        return {"profile": profile, "prefs": prefs}


def save_settings(profile: dict, prefs: dict):
    with Session(engine) as session:
        cfg = _get_config(session)
        cfg.profile_json = json.dumps(profile)
        cfg.preferences_json = json.dumps(prefs)
        session.add(cfg)
        session.commit()


def get_pipeline_counts() -> dict:
    with Session(engine) as session:
        apps = session.exec(select(Application)).all()
        counts = {"new": 0, "applied": 0, "interview": 0, "offer": 0, "rejected": 0}
        for a in apps:
            if not a.dismissed:
                v = a.status.value if a.status else "new"
                counts[v] = counts.get(v, 0) + 1
        return counts


def get_jobs(
    min_score: int = 0,
    category: str | None = None,
    show_dismissed: bool = False,
    view: str = "all",   # "all" | "saved" | "applied"
    search_text: str = "",
    sort: str = "score",  # "score" | "date" | "company"
    ai_only: bool = False,
    new_only: bool = False,    # only jobs fetched since last search
    status_filter: str = "",   # "applied" | "interview" | "offer" | "rejected"
) -> list[dict]:
    with Session(engine) as session:
        jobs = session.exec(select(Job)).all()
        if not jobs:
            return []

        # cutoff: jobs fetched after this timestamp are "new"
        new_since_dt = None
        cfg = session.get(Config, 1)
        if cfg:
            ts = json.loads(cfg.preferences_json).get("new_since_ts", "")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    new_since_dt = datetime.strptime(ts, fmt); break
                except Exception:
                    pass

        app_map: dict[int, Application] = {
            a.job_id: a
            for a in session.exec(
                select(Application).where(Application.job_id.in_([j.id for j in jobs]))
            ).all()
        }

        result = []
        for job in jobs:
            app = app_map.get(job.id)
            if job.relevance_score is not None and job.relevance_score < min_score: continue
            if category and job.category.value != category: continue
            if not show_dismissed and app and app.dismissed: continue
            if view == "saved" and not (app and app.saved): continue
            if view == "applied" and not (app and app.status == ApplicationStatus.applied): continue
            extra = {}
            if job.extra_data:
                try:
                    extra = json.loads(job.extra_data)
                except Exception:
                    pass
            is_new = (
                job.fetched_at is not None
                and new_since_dt is not None
                and job.fetched_at > new_since_dt
            )
            result.append({
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": job.description,
                "url": job.url,
                "category": job.category.value if job.category else "unknown",
                "relevance_score": job.relevance_score,
                "relevance_reason": job.relevance_reason,
                "source": job.source.value if job.source else "",
                "posted_at": job.posted_at,
                "fetched_at": job.fetched_at,
                "status": app.status.value if app and app.status else "new",
                "saved": app.saved if app else False,
                "dismissed": app.dismissed if app else False,
                "viewed": app.viewed if app else False,
                "is_new": is_new,
                "notes": app.notes if app else "",
                "applied_at": app.applied_at if app else None,
                "extra": extra,
                "extra_data": job.extra_data,
            })
        if ai_only:
            result = [r for r in result if (r["relevance_reason"] or "").startswith("[AI]")]
        if new_only:
            result = [r for r in result if r.get("is_new")]
        if status_filter:
            result = [r for r in result if r["status"] == status_filter]
        if search_text:
            q = search_text.lower()
            result = [r for r in result
                      if q in (r["title"] or "").lower()
                      or q in (r["company"] or "").lower()
                      or q in (r.get("description") or "").lower()]
        if sort == "date":
            result.sort(key=lambda x: x["posted_at"] or datetime.min, reverse=True)
        elif sort == "company":
            result.sort(key=lambda x: (x["company"] or "").lower())
        else:
            result.sort(key=lambda x: x["relevance_score"] or 0, reverse=True)
        return result


def toggle_save(job_id: int) -> bool:
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app:
            app.saved = not app.saved
            session.add(app)
            session.commit()
            return app.saved
    return False


def force_dismiss(job_id: int):
    """Dismiss unconditionally (does not toggle)."""
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app and not app.dismissed:
            app.dismissed = True
            session.add(app)
            session.commit()


def toggle_dismiss(job_id: int) -> bool:
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app:
            app.dismissed = not app.dismissed
            session.add(app)
            session.commit()
            return app.dismissed
    return False


def mark_viewed(job_id: int):
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app and not app.viewed:
            app.viewed = True
            session.add(app)
            session.commit()


def undo_dismiss(job_id: int):
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app and app.dismissed:
            app.dismissed = False
            session.add(app)
            session.commit()


def get_stats() -> dict:
    with Session(engine) as session:
        jobs = session.exec(select(Job)).all()
        apps = {a.job_id: a for a in session.exec(select(Application)).all()}
        scores = [j.relevance_score for j in jobs if j.relevance_score is not None]
        bands = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
        for s in scores:
            if s < 25:   bands["0-25"]   += 1
            elif s < 50: bands["25-50"]  += 1
            elif s < 75: bands["50-75"]  += 1
            else:        bands["75-100"] += 1
        cats = {"it": 0, "wirtschaft": 0, "unknown": 0}
        for j in jobs:
            cats[j.category.value if j.category else "unknown"] = cats.get(
                j.category.value if j.category else "unknown", 0) + 1
        pipeline = {"new": 0, "applied": 0, "interview": 0, "offer": 0, "rejected": 0}
        viewed_count = 0
        ai_count = 0
        for j in jobs:
            a = apps.get(j.id)
            if a and not a.dismissed:
                st = a.status.value if a.status else "new"
                pipeline[st] = pipeline.get(st, 0) + 1
            if a and a.viewed:
                viewed_count += 1
            if (j.relevance_reason or "").startswith("[AI]"):
                ai_count += 1
        return {
            "total": len(jobs),
            "score_bands": bands,
            "categories": cats,
            "pipeline": pipeline,
            "viewed": viewed_count,
            "ai_scored": ai_count,
        }


def bulk_dismiss(job_ids: list[int]):
    with Session(engine) as session:
        for jid in job_ids:
            app = session.exec(select(Application).where(Application.job_id == jid)).first()
            if app and not app.dismissed:
                app.dismissed = True
                session.add(app)
        session.commit()


def auto_dismiss_old_jobs(days: int) -> int:
    if days <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=days)
    with Session(engine) as session:
        old_jobs = session.exec(select(Job).where(Job.fetched_at < cutoff)).all()
        count = 0
        for job in old_jobs:
            app = session.exec(select(Application).where(Application.job_id == job.id)).first()
            if app and not app.dismissed and (app.status == ApplicationStatus.new):
                app.dismissed = True
                session.add(app)
                count += 1
        session.commit()
    return count


def set_status(job_id: int, status: str) -> str:
    """Set application status. If already that status, revert to 'new'."""
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app:
            if app.status.value == status:
                app.status = ApplicationStatus.new
                app.applied_at = None
            else:
                app.status = ApplicationStatus(status)
                if status == "applied":
                    app.applied_at = datetime.utcnow()
            session.add(app)
            session.commit()
            return app.status.value
    return "new"


def get_notes(job_id: int) -> str:
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        return (app.notes or "") if app else ""


def save_notes(job_id: int, text: str):
    with Session(engine) as session:
        app = session.exec(select(Application).where(Application.job_id == job_id)).first()
        if app:
            app.notes = text
            session.add(app)
            session.commit()


def save_last_search(new_count: int):
    with Session(engine) as session:
        cfg = _get_config(session)
        prefs = {**_DEFAULT_PREFS, **json.loads(cfg.preferences_json)}
        prefs["new_since_ts"] = prefs.get("last_search_ts", "")  # previous search = new cutoff
        prefs["last_search_ts"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        prefs["last_search_new"] = new_count
        cfg.preferences_json = json.dumps(prefs)
        session.add(cfg)
        session.commit()


def dismiss_empty_description_jobs(min_chars: int = 80) -> int:
    """Dismiss new/unsaved jobs whose description is missing or too short."""
    with Session(engine) as session:
        jobs = session.exec(select(Job)).all()
        app_map = {
            a.job_id: a
            for a in session.exec(select(Application)).all()
        }
        count = 0
        for job in jobs:
            app = app_map.get(job.id)
            if not app or app.dismissed or app.saved:
                continue
            if app.status != ApplicationStatus.new:
                continue
            desc = (job.description or "").strip()
            if len(desc) < min_chars:
                app.dismissed = True
                session.add(app)
                count += 1
        session.commit()
    return count


def clear_all_jobs():
    """Delete all jobs, applications and cover letters from the database."""
    with Session(engine) as session:
        for model in (CoverLetter, Application, Job):
            for obj in session.exec(select(model)).all():
                session.delete(obj)
        session.commit()


def get_jobs_for_ai_scoring(min_score: int = 40) -> list[dict]:
    """Jobs with rule_score >= min_score that haven't been AI-scored yet."""
    with Session(engine) as session:
        jobs = session.exec(
            select(Job)
            .where(Job.relevance_score >= min_score)
            .order_by(Job.relevance_score.desc())
        ).all()
        return [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company or "",
                "description": j.description or "",
            }
            for j in jobs
            if not (j.relevance_reason or "").startswith("[AI]")
        ]


def update_job_ai_score(job_id: int, score: int, reason: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job:
            job.relevance_score = score
            job.relevance_reason = reason
            session.add(job)
            session.commit()


def update_job_description(job_id: int, description: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job:
            job.description = description
            session.add(job)
            session.commit()


def get_cover_letter(job_id: int) -> str | None:
    with Session(engine) as session:
        cl = session.exec(
            select(CoverLetter).where(CoverLetter.job_id == job_id)
        ).first()
        return cl.content if cl else None


def save_cover_letter(job_id: int, content: str):
    with Session(engine) as session:
        cl = session.exec(
            select(CoverLetter).where(CoverLetter.job_id == job_id)
        ).first()
        if cl:
            cl.content = content
            cl.is_edited = True
            cl.edited_at = datetime.utcnow()
        else:
            cl = CoverLetter(job_id=job_id, content=content)
            session.add(cl)
        session.commit()
