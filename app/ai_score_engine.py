"""Background AI scoring queue — processes jobs one-by-one, emits progress."""
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from app.db import update_job_ai_score
from app.log import _log_activity
from backend.services.ai_scorer import score_job_ai

_DECISIONS_FILE = (
    Path(os.environ.get("APPDATA", Path.home())) / "AutoApply" / "data" / "ai_decisions.json"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent / "data" / "ai_decisions.json"
)

ai_score_status: dict = {
    "running":  False,
    "total":    0,
    "done":     0,
    "current":  "",
    "eta_s":    0,
    "phase":    "idle",   # idle | scoring | done | cancelled | error
    "scored":   0,
    "avg_s":    15.0,
}

_decisions: deque = deque(maxlen=500)
_cancel = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _load_decisions():
    try:
        if _DECISIONS_FILE.exists():
            data = json.loads(_DECISIONS_FILE.read_text(encoding="utf-8"))
            for d in data[-500:]:
                _decisions.append(d)
    except Exception:
        pass


def _save_decisions():
    try:
        _DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            _DECISIONS_FILE.write_text(
                json.dumps(list(_decisions), ensure_ascii=False, indent=None),
                encoding="utf-8",
            )
    except Exception:
        pass


def get_decisions() -> list[dict]:
    return list(_decisions)


def start_scoring(
    jobs: list[dict],
    model: str,
    profile: str,
    custom_prompt: str = "",
    on_job_done=None,
    on_complete=None,
):
    global _thread, ai_score_status
    if ai_score_status["running"] or not jobs:
        return
    _cancel.clear()
    ai_score_status = {
        "running": True, "total": len(jobs), "done": 0,
        "current": "", "eta_s": int(len(jobs) * 15),
        "phase": "scoring", "scored": 0, "avg_s": 15.0,
    }
    _thread = threading.Thread(
        target=_run,
        args=(jobs, model, profile, custom_prompt, on_job_done, on_complete),
        daemon=True,
    )
    _thread.start()


def cancel_scoring():
    _cancel.set()
    ai_score_status["phase"] = "cancelling"


def _ensure_ollama() -> bool:
    """Returns True if ollama is reachable, starting it if necessary."""
    try:
        import httpx
    except ImportError:
        return False
    try:
        httpx.get("http://localhost:11434/", timeout=2)
        return True
    except Exception:
        pass
    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            time.sleep(1)
            try:
                httpx.get("http://localhost:11434/", timeout=1)
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _run(jobs, model, profile, custom_prompt, on_job_done, on_complete):
    ai_score_status["current"] = "checking ollama…"
    if not _ensure_ollama():
        _log_activity("Ollama unreachable — scoring aborted", "info")
        ai_score_status["running"] = False
        ai_score_status["phase"]   = "error"
        ai_score_status["current"] = ""
        if on_complete:
            on_complete()
        return
    _log_activity("Ollama ready", "info")

    times: list[float] = []
    for job in jobs:
        if _cancel.is_set():
            break
        title   = job.get("title", "")[:50]
        company = job.get("company", "")[:30]
        ai_score_status["current"] = title
        _log_activity(f"AI scoring: {title}", "info")

        t0 = time.time()
        result = score_job_ai(
            job.get("title", ""), job.get("company", ""),
            job.get("description", ""), profile, model, custom_prompt,
        )
        elapsed = time.time() - t0
        times.append(elapsed)
        ai_score_status["avg_s"] = sum(times) / len(times)
        ai_score_status["done"] += 1
        remaining = ai_score_status["total"] - ai_score_status["done"]
        ai_score_status["eta_s"] = int(remaining * ai_score_status["avg_s"])

        if result["ok"]:
            kept = result["score"] >= 25
            with _lock:
                _decisions.append({
                    "ts":      time.strftime("%H:%M:%S"),
                    "title":   title,
                    "company": company,
                    "score":   result["score"],
                    "reason":  result["reason"].removeprefix("[AI] "),
                    "kept":    kept,
                    "time_s":  round(elapsed, 1),
                    "error":   False,
                })
            update_job_ai_score(job["id"], result["score"], result["reason"])
            ai_score_status["scored"] += 1
            icon = "✦" if kept else "✕"
            _log_activity(
                f"AI {icon} [{result['score']:>3}]  {title}  — {result['reason'][:55]}",
                "info",
            )
            if on_job_done:
                on_job_done(job["id"], result["score"], result["reason"])
        else:
            err_msg = result["reason"].removeprefix("[AI_ERR] ")
            with _lock:
                _decisions.append({
                    "ts":      time.strftime("%H:%M:%S"),
                    "title":   title,
                    "company": company,
                    "score":   -1,
                    "reason":  err_msg,
                    "kept":    False,
                    "time_s":  round(elapsed, 1),
                    "error":   True,
                })
            _log_activity(f"AI ERR  {title}  — {err_msg[:70]}", "info")

    _save_decisions()
    ai_score_status["running"] = False
    ai_score_status["current"] = ""
    ai_score_status["phase"] = "done" if not _cancel.is_set() else "cancelled"
    ai_score_status["eta_s"] = 0
    if on_complete:
        on_complete()


# load persisted decisions on import
_load_decisions()
