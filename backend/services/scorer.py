"""
Rule-based job scoring — no LLM, instant.
Score 0-100 based on keyword matching, sector, and exclusion criteria.
"""
import re

from backend.models import JobCategory

# Hard-exclude jobs requiring 3+ years experience or thesis-only positions
_RE_EXPERIENCED = re.compile(
    r'\b([3-9]|\d{2,})\s*[\+\-]?\s*jahre?\s*(berufserfahrung|erfahrung|praxiserfahrung)|'
    r'mind(est)?\w*\s+([3-9]|\d{2,})\s*jahre?\s*(erfahrung|berufserfahrung)|'
    r'([3-9]|\d{2,})\s*years?\s*(of\s+)?experience|'
    r'mehrjährige\s+\w*\s*erfahrung|langjährige\s+\w*\s*erfahrung|'
    r'berufserfahrener?\b|'
    r'bachelorarbeit|masterarbeit|abschlussarbeit|bachelor.{0,5}thesis|master.{0,5}thesis|'
    r'nur\s+für\s+studierende|ausschließlich\s+für\s+studierende',
    re.IGNORECASE,
)

PREFERRED_SECTORS = [
    "öffentlich", "behörde", "verwaltung", "amt", "ministerium", "bundesamt",
    "landesamt", "kreis", "kommune", "stadtwerk", "stadtwerke", "bundeswehr",
    "bundesagentur", "jobcenter", "kammer", "universität", "hochschule",
]

KEYWORDS_IT = [
    "it-koordinat", "it-consultant", "it-betreuer", "requirements engineer",
    "it-anforderung", "industrie 4.0", "digitalisierungsbeauftragt",
    "applikationsbetreuer", "systemadministrat",
    "cloud architect", "netzwerkadministrat", "systemintegrator", "datenbankadministrat",
]

KEYWORDS_IT_SUPPORT = [
    "it-support", "helpdesk", "help desk", "1st level", "2nd level", "first level",
    "second level", "anwendersupport", "user support", "itsm",
]

KEYWORDS_KI = [
    "künstliche intelligenz", "machine learning", "deep learning", "neural network",
    "llm", "large language model", "nlp", "natural language", "computer vision",
    "ki-projekt", "ki-strategie", "ai-projekt", "ai-strategie", "generative ai",
    "prompt engineering", "data science", "data scientist", "data engineer",
    "data analyst", "datenanalyst", "datenauswertung", "datenanalyse",
    "bi developer", "business intelligence developer",
    "devops", "mlops", "etl", "data warehouse", "data pipeline",
]

KEYWORDS_DIGITALISIERUNG = [
    "digitalisierung", "automatisierung", "prozessautomatisierung",
    "rpa", "robotic process automation", "digital transformation",
    "verwaltungsdigitalisierung", "e-government", "industrie 4.0",
    "digitale transformation", "workflow-automatisierung",
]

KEYWORDS_WIRTSCHAFT = [
    "business analyst", "prozessmanagement", "prozessoptimierung", "wirtschaftsinformatik",
    "business intelligence", "organisationsentwicklung", "qualitätsmanagement",
    "prozessanalyst",
]

# Viel Kundenkontakt / Führungsverantwortung → Abzug
KEYWORDS_HIGH_CONTACT = [
    "kundenkontakt", "kundenbetreuung", "kundenberatung", "key account",
    "account management", "vertriebsinnendienst", "kundenpflege",
    "ansprechpartner für kunden", "disziplinarische führung",
    "führungsverantwortung", "personalverantwortung", "mitarbeiterführung",
]

# Management-heavy titles → small penalty (user prefers technical over managerial)
KEYWORDS_MANAGEMENT_TITLE = [
    "projektmanager", "project manager", "projektleiter", "koordinator",
    "it-koordinator", "it-projektmanagement",
]

# Interne / ruhige Rollen → Bonus
KEYWORDS_SECURITY = [
    "it-security", "it security", "cybersecurity", "cyber security",
    "information security", "it-sicherheit", "it sicherheit",
    "soc analyst", "security analyst", "it-sicherheitsanalyst",
    "it-sicherheitsbeauftragter", "penetration", "vulnerability",
    "siem", "endpoint security", "netzwerksicherheit",
]

KEYWORDS_LOW_CONTACT = [
    "backoffice", "back office", "inhouse", "ohne außendienst",
    "interne", "keine reisetätigkeit", "keine reisebereitschaft",
    "überwiegend intern", "sachbearbeitung", "datenanalyse", "datenauswertung",
]

KEYWORDS_SCHNITTSTELLE = [
    "technischer produktmanager", "digitalisierungsbeauftragt", "produktionsdigitalisierung",
    "wirtschaftsinformatik", "wirtschaftsinformatiker", "it-analyst", "systemanalyst",
    "applikationsmanager",
]

LOCATION_NORTH_DE = [
    "schleswig-holstein", "niedersachsen", "nordrhein-westfalen", "nrw",
    "hamburg", "bremen",
    "kiel", "flensburg", "lübeck", "schleswig", "neumünster", "rendsburg",
    "hannover", "braunschweig", "osnabrück", "oldenburg", "wolfsburg", "göttingen",
    "dortmund", "köln", "düsseldorf", "essen", "bochum", "münster",
    "bielefeld", "wuppertal", "aachen", "bonn",
]

# Switzerland, Austria, Luxembourg → small bonus (preferred regions after North DE)
LOCATION_DACH_LU = [
    # Switzerland
    "zürich", "zurich", "bern", "basel", "genf", "geneva", "lausanne",
    "zug", "winterthur", "st. gallen", "luzern", "lugano", "schweiz", "switzerland",
    # Austria
    "wien", "vienna", "graz", "linz", "salzburg", "innsbruck",
    "klagenfurt", "bregenz", "österreich", "austria",
    # Luxembourg
    "luxembourg", "luxemburg", "esch", "differdange",
]

ENTRY_LEVEL_SIGNALS = [
    "berufseinsteiger", "junior", "trainee", "absolvent", "hochschulabsolvent",
    "werkstudent", "duales studium", "einstiegsposition",
]

EXCLUDE_KEYWORDS = [
    # Pure developer roles
    "softwareentwickler", "software developer", "programmierer",
    "full stack", "frontend developer", "backend developer", "java developer",
    "python developer", ".net developer",
    # SAP-specific consulting roles (not plain "sap" — too broad)
    "sap-berater", "sap berater", "erp-berater", "erp spezialist",
    # Sales / field
    "vertrieb", "sales manager", "account manager", "call center", "kundenberater",
    "außendienst",
    # Seniority (leadership / overqualified)
    "lead developer", "team lead", "teamleiter", "abteilungsleiter", "bereichsleiter",
    # Unrelated professions
    "rechtsanwalt", "jurist", "wirtschaftsprüfer",
    "krankenpfleger", "erzieher", "sozialpädagog", "pädagog",
    "monteur", "elektriker", "schlosser", "lkw", "fahrer",
    "hausmeister",
]


def score_job(title: str, description: str, company: str = "", location: str = "") -> dict:
    text = (title + " " + description + " " + company).lower()
    title_lower = title.lower()
    loc = location.lower()

    # Hard-Ausschluss
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return {"score": 0, "reason": f"Excluded: contains '{kw}'"}

    # Jobs für Erfahrene → hard ausschließen (außer wenn nur "wünschenswert")
    desc = description or ""
    if _RE_EXPERIENCED.search(desc) and "wünschenswert" not in desc.lower():
        return {"score": 0, "reason": "Requires 3+ years experience"}

    score = 40  # Basiswert
    reasons: list[str] = []

    # Preferred sector (public) +20
    for sector in PREFERRED_SECTORS:
        if sector in text:
            score += 20
            reasons.append("Public sector")
            break

    # AI / ML keywords +15 per hit
    ki_hits = sum(1 for kw in KEYWORDS_KI if kw in text)
    ki_title_hits = sum(1 for kw in KEYWORDS_KI if kw in title_lower)
    score += ki_hits * 15 + ki_title_hits * 5
    if ki_hits:
        reasons.append(f"AI/ML keyword{'s' if ki_hits > 1 else ''}")

    # Digitalization / automation +15 per hit
    dig_hits = sum(1 for kw in KEYWORDS_DIGITALISIERUNG if kw in text)
    dig_title_hits = sum(1 for kw in KEYWORDS_DIGITALISIERUNG if kw in title_lower)
    score += dig_hits * 15 + dig_title_hits * 5
    if dig_hits:
        reasons.append("Digitalization/Automation")

    # IT keywords +5
    it_hits = sum(1 for kw in KEYWORDS_IT if kw in text)
    it_title_hits = sum(1 for kw in KEYWORDS_IT if kw in title_lower)
    score += it_hits * 5 + it_title_hits * 5
    if it_hits:
        reasons.append(f"{it_hits} IT keyword{'s' if it_hits > 1 else ''}")

    # IT security +10 per hit
    sec_hits = sum(1 for kw in KEYWORDS_SECURITY if kw in text)
    sec_title_hits = sum(1 for kw in KEYWORDS_SECURITY if kw in title_lower)
    score += sec_hits * 10 + sec_title_hits * 5
    if sec_hits:
        reasons.append(f"IT Security keyword{'s' if sec_hits > 1 else ''}")

    # IT support +2 (acceptable but not preferred)
    sup_hits = sum(1 for kw in KEYWORDS_IT_SUPPORT if kw in text)
    score += sup_hits * 2
    if sup_hits:
        reasons.append("IT Support")

    # Business keywords +4
    w_hits = sum(1 for kw in KEYWORDS_WIRTSCHAFT if kw in text)
    w_title_hits = sum(1 for kw in KEYWORDS_WIRTSCHAFT if kw in title_lower)
    score += w_hits * 4 + w_title_hits * 4
    if w_hits:
        reasons.append(f"{w_hits} business keyword{'s' if w_hits > 1 else ''}")

    # Interface/crossover keywords
    s_hits = sum(1 for kw in KEYWORDS_SCHNITTSTELLE if kw in text)
    score += s_hits * 6
    if s_hits:
        reasons.append("IT/Business interface")

    # Entry-level signals +8
    for sig in ENTRY_LEVEL_SIGNALS:
        if sig in text:
            score += 8
            reasons.append("Entry-level position")
            break

    # High customer contact / management → penalty (max -15)
    contact_hits = sum(1 for kw in KEYWORDS_HIGH_CONTACT if kw in text)
    if contact_hits:
        score -= min(15, contact_hits * 8)
        reasons.append(f"Customer contact/management (-{min(15, contact_hits * 8)})")

    # Management-heavy title → small penalty
    mgmt_hits = sum(1 for kw in KEYWORDS_MANAGEMENT_TITLE if kw in title_lower)
    if mgmt_hits:
        score -= 8
        reasons.append("Management title (-8)")

    # Internal / low-contact role → small bonus
    low_hits = sum(1 for kw in KEYWORDS_LOW_CONTACT if kw in text)
    if low_hits:
        score += min(10, low_hits * 5)
        reasons.append("Internal role")

    # Remote bonus
    if "remote" in loc or "remote" in title_lower or "homeoffice" in text or "home office" in text:
        score += 10
        reasons.append("Remote/Homeoffice")

    # Location bonuses (stackable: North DE job can also be DACH)
    if any(kw in loc for kw in LOCATION_NORTH_DE):
        score += 10
        reasons.append("North Germany")
    elif any(kw in loc for kw in LOCATION_DACH_LU):
        score += 5
        reasons.append("CH/AT/LU")

    reason = ", ".join(reasons) if reasons else "Base score"
    return {"score": min(100, score), "reason": reason}


def detect_category(title: str, description: str) -> JobCategory:
    text = (title + " " + description).lower()
    it_score = sum(1 for kw in KEYWORDS_IT + KEYWORDS_KI + KEYWORDS_DIGITALISIERUNG
                   + KEYWORDS_IT_SUPPORT + KEYWORDS_SCHNITTSTELLE if kw in text)
    w_score = sum(1 for kw in KEYWORDS_WIRTSCHAFT if kw in text)
    if it_score > w_score:
        return JobCategory.it
    if w_score > it_score:
        return JobCategory.wirtschaft
    return JobCategory.unknown
