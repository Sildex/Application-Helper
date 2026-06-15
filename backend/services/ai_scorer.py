"""LLM-based job relevance scoring. Short prompt, structured output."""
import re
import time

import ollama

_SYSTEM_TEMPLATE = """\
Du bewertest Stellenangebote für folgenden Bewerber:
{profile}

{custom_prompt}

Antworte NUR in exakt diesem Format (keine anderen Zeichen):
SCORE: [0-100]
REASON: [max. 1 Satz auf Deutsch]

SCORE-Skala: 0-20 unpassend · 20-50 schwach · 50-75 geeignet · 75-100 sehr gut\
"""

_DEFAULT_CUSTOM = ""


def score_job_ai(
    title: str,
    company: str,
    description: str,
    profile: str,
    model: str = "qwen2.5:14b",
    custom_prompt: str = "",
    location: str = "",
) -> dict:
    system = _SYSTEM_TEMPLATE.format(
        profile=profile,
        custom_prompt=custom_prompt.strip() or _DEFAULT_CUSTOM,
    )
    desc_excerpt = (description or "")[:2000] or "—"
    user = f"STELLE: {title}\nFIRMA: {company or '—'}\nSTANDORT: {location or '—'}\nBESCHREIBUNG:\n{desc_excerpt}"

    t0 = time.time()
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            options={"temperature": 0.1, "num_predict": 100, "num_ctx": 4096},
        )
        text = resp["message"]["content"].strip()
        sm = re.search(r"SCORE:\s*(\d+)", text)
        rm = re.search(r"REASON:\s*(.+)", text, re.DOTALL)
        score  = min(100, max(0, int(sm.group(1)))) if sm else 25
        reason = rm.group(1).strip().split("\n")[0] if rm else "—"
        from backend.services.llm_service import log_call as _log_call
        _log_call(f"score · {title[:35]}", round(time.time() - t0, 1), model)
        return {"score": score, "reason": f"[AI] {reason}", "ok": True}
    except Exception as exc:
        return {"score": -1, "reason": f"[AI_ERR] {exc}", "ok": False}
