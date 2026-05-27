# Requirements Specification
**Project:** AutoApply – KI-gestützte Bewerbungsautomatisierung  
**Version:** 0.1 (Draft)  
**Date:** 2026-05-19  
**Status:** In Progress

---

## 1. Vision

Eine Desktop-/Web-Applikation, die mithilfe von KI passende Stellenanzeigen findet, automatisch Bewerbungsunterlagen vorbereitet und dem User per One-Click-Link das Absenden ermöglicht.

---

## 2. Stakeholder

| Stakeholder | Rolle | Ziel |
|---|---|---|
| Maik Bender | Primärnutzer (Bewerber) | Schnell & effizient bewerben |
| Potenzielle Arbeitgeber | Indirekt | Erhalten qualifizierte Bewerbungen |

---

## 3. Funktionale Anforderungen

### F-01 Stellensuche
- Das System durchsucht automatisch Jobportale nach Stellen
- Quellen: LinkedIn, Indeed, Google Jobs, Stepstone
- Filterkriterien: Berufsfeld, Standort, Senioritätslevel, Vollzeit/Teilzeit
- Ergebnis: Liste relevanter Stellen mit Titel, Firma, Ort, Link, Beschreibung

### F-02 Relevanz-Scoring
- KI bewertet jede Stelle gegen das User-Profil (CV, Präferenzen)
- Ausgabe: Score 0–100 + kurze Begründung
- User sieht nur Stellen ab konfigurierbarem Mindestscore

### F-03 Anschreiben-Generierung
- KI erstellt individuelles Anschreiben pro Stelle
- Input: CV des Users + Stellenbeschreibung + optionale Hinweise
- Output: Anschreiben im gewählten Stil (formal/modern)
- User kann das Anschreiben vor Verwendung bearbeiten

### F-04 Bewerbungs-Dashboard
- Übersicht aller gefundenen/vorbereiteten/versendeten Bewerbungen
- Status-Tracking: Gefunden → Vorbereitet → Versendet → Antwort erhalten
- Direktlink zur Original-Stellenanzeige pro Eintrag

### F-05 One-Click Apply
- Button öffnet direkt die Bewerbungsseite der Stelle im Browser
- Optional: vorbereitete Unterlagen werden in Zwischenablage kopiert

### F-06 User-Profil / CV-Management
- User hinterlegt CV (PDF oder strukturiert)
- Definiert Suchpräferenzen (Branche, Standort, Gehalt, etc.)

---

## 4. Nicht-funktionale Anforderungen

| ID | Anforderung | Priorität |
|---|---|---|
| NF-01 | Stellensuche läuft im Hintergrund (async) | Hoch |
| NF-02 | Anschreiben-Generierung < 30 Sek. | Hoch |
| NF-03 | Lokale Datenspeicherung (kein Cloud-Zwang) | Mittel |
| NF-04 | Keine Login-Pflicht für MVP | Mittel |
| NF-05 | Läuft auf Windows 11 | Hoch |

---

## 5. Abgrenzung (Out of Scope – MVP)

- Automatisches Ausfüllen von Bewerbungsformularen
- Email-Versand direkt aus der App
- Mobile App
- Multi-User / Team-Funktionen
- CV-Editor

---

## 6. Offene Fragen

- [ ] Welche Job-APIs sind kostenlos nutzbar? (→ Recherche Phase 2)
- [ ] CV-Format: PDF-Upload oder manuell strukturiert eingeben?
- [ ] Soll Bewerbungshistorie persistent gespeichert werden?
