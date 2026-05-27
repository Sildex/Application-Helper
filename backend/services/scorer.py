"""
Regelbasiertes Job-Scoring – kein LLM, sofort schnell.
Score 0-100 basierend auf Keyword-Matching, Branche und Ausschlusskriterien.
"""
from backend.models import JobCategory

PREFERRED_SECTORS = [
    "öffentlich", "behörde", "verwaltung", "amt", "ministerium", "bundesamt",
    "landesamt", "kreis", "kommune", "stadtwerk", "stadtwerke", "bundeswehr",
    "bundesagentur", "jobcenter", "kammer", "universität", "hochschule",
]

KEYWORDS_IT = [
    "it-projektmanagement", "it-koordinat", "it-consultant", "digitalisierung",
    "verwaltungsdigitalisierung", "e-government", "it-betreuer", "requirements engineer",
    "it-anforderung", "industrie 4.0", "technischer projektleiter", "it-projektleiter",
    "digitalisierungsbeauftragt", "applikationsbetreuer", "systemadministrat",
]

KEYWORDS_WIRTSCHAFT = [
    "business analyst", "prozessmanagement", "prozessoptimierung", "wirtschaftsinformatik",
    "projektkoordinator", "junior projektmanager", "business intelligence",
    "organisationsentwicklung", "qualitätsmanagement", "prozessanalyst",
    "projektmanagement", "organisationsberater",
]

KEYWORDS_SCHNITTSTELLE = [
    "technischer produktmanager", "digitalisierungsbeauftragt", "produktionsdigitalisierung",
    "mechatronik", "automotive", "maschinenbau", "kfz", "fahrzeug",
]

ENTRY_LEVEL_SIGNALS = [
    "berufseinsteiger", "junior", "trainee", "absolvent", "hochschulabsolvent",
    "werkstudent", "duales studium", "einstiegsposition",
]

EXCLUDE_KEYWORDS = [
    "softwareentwickler", "software developer", "software engineer", "programmierer",
    "full stack", "frontend developer", "backend developer", "java developer",
    "python developer", ".net developer",
    "sap", "erp-berater", "erp spezialist", "sap-berater",
    "vertrieb", "sales manager", "account manager", "call center", "kundenberater",
    "außendienst",
]


def score_job(title: str, description: str, company: str = "") -> dict:
    text = (title + " " + description + " " + company).lower()
    title_lower = title.lower()

    # Hard-Ausschluss
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return {"score": 0, "reason": f"Ausgeschlossen: enthält '{kw}'"}

    score = 40  # Basiswert
    reasons: list[str] = []

    # Bevorzugte Branche +20
    for sector in PREFERRED_SECTORS:
        if sector in text:
            score += 20
            reasons.append("öffentlicher Dienst / bevorzugte Branche")
            break

    # IT-Keywords (im Titel stärker gewichtet)
    it_hits = sum(1 for kw in KEYWORDS_IT if kw in text)
    it_title_hits = sum(1 for kw in KEYWORDS_IT if kw in title_lower)
    score += it_hits * 5 + it_title_hits * 5
    if it_hits:
        reasons.append(f"{it_hits} IT-Keyword{'s' if it_hits > 1 else ''}")

    # Wirtschafts-Keywords
    w_hits = sum(1 for kw in KEYWORDS_WIRTSCHAFT if kw in text)
    w_title_hits = sum(1 for kw in KEYWORDS_WIRTSCHAFT if kw in title_lower)
    score += w_hits * 4 + w_title_hits * 4
    if w_hits:
        reasons.append(f"{w_hits} Business-Keyword{'s' if w_hits > 1 else ''}")

    # Schnittstellen-Keywords
    s_hits = sum(1 for kw in KEYWORDS_SCHNITTSTELLE if kw in text)
    score += s_hits * 6
    if s_hits:
        reasons.append("Schnittstellen-Rolle")

    # Einstiegssignale +8
    for sig in ENTRY_LEVEL_SIGNALS:
        if sig in text:
            score += 8
            reasons.append("Einstiegsposition")
            break

    reason = ", ".join(reasons) if reasons else "Basisbewertung"
    return {"score": min(100, score), "reason": reason}


def detect_category(title: str, description: str) -> JobCategory:
    text = (title + " " + description).lower()
    it_score = sum(1 for kw in KEYWORDS_IT + KEYWORDS_SCHNITTSTELLE if kw in text)
    w_score = sum(1 for kw in KEYWORDS_WIRTSCHAFT if kw in text)
    if it_score > w_score:
        return JobCategory.it
    if w_score > it_score:
        return JobCategory.wirtschaft
    return JobCategory.unknown
