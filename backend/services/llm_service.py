"""
Lokales LLM via Ollama.
keep_alive="2m" → Modell entlädt sich 2 Min nach letzter Nutzung automatisch.
"""
import time
from datetime import datetime

import ollama

_llm_log: list[dict] = []

_PROFILE_CONTEXT = ""

_SYSTEM_PROMPT = "Du bist ein Bewerbungsassistent. Antworte immer auf Deutsch. Sei präzise und halte dich an das geforderte Format."


def get_log() -> list[dict]:
    return list(reversed(_llm_log))


def log_call(purpose: str, duration_s: float, model: str):
    _llm_log.append({
        "purpose": purpose,
        "duration_s": duration_s,
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
        "model": model,
    })
    if len(_llm_log) > 30:
        _llm_log.pop(0)


def _chat(messages: list[dict], model: str, purpose: str = "") -> str:
    start = time.time()
    response = ollama.chat(
        model=model,
        messages=[{"role": "system", "content": _SYSTEM_PROMPT}] + messages,
        options={"temperature": 0.3},
        keep_alive="2m",
    )
    duration = round(time.time() - start, 1)
    _llm_log.append({
        "purpose": purpose,
        "duration_s": duration,
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
        "model": model,
    })
    if len(_llm_log) > 30:
        _llm_log.pop(0)
    return response["message"]["content"].strip()


def generate_cover_letter(
    job_title: str,
    company: str,
    job_description: str,
    model: str = "qwen2.5:14b",
    extra_instructions: str = "",
    reference_letter: str = "",
) -> str:
    ref_block = ""
    if reference_letter.strip():
        ref_block = (
            f"\n\nReferenz-Anschreiben (orientiere dich an Stil und Aufbau, "
            f"aber schreibe es komplett neu und stellenspezifisch):\n"
            f"---\n{reference_letter[:1500]}\n---"
        )
    extra_block = f"\n\nZusätzliche Hinweise: {extra_instructions.strip()}" if extra_instructions.strip() else ""

    return _chat(
        [
            {
                "role": "user",
                "content": (
                    f"Schreibe ein professionelles Bewerbungsanschreiben.\n\n"
                    f"Unternehmen: {company}\n"
                    f"Position: {job_title}\n\n"
                    f"Stellenbeschreibung:\n{job_description[:2000]}\n\n"
                    f"Vorgaben:\n"
                    f"- Ton: professionell und direkt, keine Floskeln\n"
                    f"- Struktur: Einstieg (konkreter Bezug zur Stelle) → Stärken/Mehrwert → Abschluss\n"
                    f"- Konkreten Bezug zu den Anforderungen der Stelle herstellen (nicht generisch)\n"
                    f"- Kernbotschaft: Prozesse effizienter gestalten und digitalisieren\n"
                    f"- Genau 3 Absätze + kurze Schlussformel, ca. 200–250 Wörter\n"
                    f"- Kein Datum, keine Adresse, keine Betreffzeile\n"
                    f"- Sprache: Deutsch"
                    f"{ref_block}"
                    f"{extra_block}"
                ),
            }
        ],
        model=model,
        purpose=f"letter · {company[:40]}",
    )


def unload_model(model: str = "qwen2.5:14b") -> None:
    try:
        ollama.chat(
            model=model,
            messages=[{"role": "user", "content": ""}],
            keep_alive=0,
        )
    except Exception:
        pass
