# Use Cases
**Project:** AutoApply  
**Version:** 0.1  
**Date:** 2026-05-19

---

## Akteure

- **User (Bewerber):** Maik – möchte sich effizient bewerben
- **KI-System:** Claude API – generiert Anschreiben, bewertet Relevanz
- **Job-APIs:** Externe Dienste (LinkedIn, Indeed, etc.)

---

## Use Case Übersicht

```
[User]──►(UC-01: Profil & CV hinterlegen)
[User]──►(UC-02: Suchpräferenzen konfigurieren)
[User]──►(UC-03: Stellensuche starten)
          └──►(UC-04: Stellen abrufen) ◄──[Job-APIs]
          └──►(UC-05: Relevanz bewerten) ◄──[KI-System]
[User]──►(UC-06: Bewerbungen im Dashboard ansehen)
[User]──►(UC-07: Anschreiben ansehen & bearbeiten)
          └──►(UC-08: Anschreiben generieren) ◄──[KI-System]
[User]──►(UC-09: Bewerbung vorbereiten / Status setzen)
[User]──►(UC-10: Zur Stellenseite navigieren)
```

---

## UC-01: Profil & CV hinterlegen

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Vorbedingung** | App ist geöffnet, erster Start |
| **Auslöser** | User öffnet Einstellungen / Onboarding |
| **Hauptablauf** | 1. User gibt Name, Kontaktdaten ein / lädt CV hoch <br> 2. System extrahiert Schlüsselinfos aus CV (Erfahrung, Skills, Ausbildung) <br> 3. System speichert Profil lokal |
| **Nachbedingung** | Profil ist gespeichert, Stellensuche ist freigeschalten |
| **Ausnahmen** | CV-Format nicht lesbar → Fehlermeldung, manuell eingeben |

---

## UC-02: Suchpräferenzen konfigurieren

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Vorbedingung** | Profil vorhanden |
| **Auslöser** | User öffnet Sucheinstellungen |
| **Hauptablauf** | 1. User gibt Berufsfeld / Keywords ein <br> 2. User wählt Standort(e) <br> 3. User setzt Mindest-Relevanzscore <br> 4. Einstellungen werden gespeichert |
| **Nachbedingung** | Präferenzen gespeichert |

---

## UC-03: Stellensuche starten

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Vorbedingung** | Profil + Präferenzen vorhanden |
| **Auslöser** | User klickt "Suche starten" |
| **Hauptablauf** | 1. System ruft Job-APIs mit Suchparametern ab <br> 2. System dedupliziert Ergebnisse <br> 3. KI bewertet jede Stelle gegen User-Profil <br> 4. System filtert nach Mindestscore <br> 5. Ergebnisse erscheinen im Dashboard |
| **Nachbedingung** | Dashboard zeigt gefilterte, bewertete Stellen |
| **Ausnahmen** | API nicht erreichbar → Fehlermeldung, vorherige Ergebnisse bleiben |

---

## UC-04: Stellen abrufen (System)

| Feld | Inhalt |
|---|---|
| **Akteur** | System + Job-APIs |
| **Ablauf** | API-Call mit Keywords, Standort, Seitenanzahl → JSON-Response → Normalisierung in internes Format |
| **Output** | Liste: { title, company, location, url, description, source, date } |

---

## UC-05: Relevanz bewerten (KI)

| Feld | Inhalt |
|---|---|
| **Akteur** | KI-System |
| **Input** | Stellenbeschreibung + User-Profil (Skills, Erfahrung, Präferenzen) |
| **Ablauf** | Prompt an Claude API → Score 0–100 + 2-Satz-Begründung |
| **Output** | { score: int, reason: string } |

---

## UC-06: Bewerbungen im Dashboard ansehen

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Auslöser** | User öffnet Dashboard |
| **Hauptablauf** | 1. System zeigt alle Stellen nach Score sortiert <br> 2. Filter nach Status möglich (Neu / Vorbereitet / Versendet) <br> 3. User klickt Stelle → Detail-Ansicht |
| **Nachbedingung** | User sieht Detailinfos + vorbereitetes Anschreiben |

---

## UC-07: Anschreiben ansehen & bearbeiten

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Vorbedingung** | Anschreiben wurde generiert (UC-08) |
| **Hauptablauf** | 1. User sieht Anschreiben in Editor <br> 2. User kann Text direkt bearbeiten <br> 3. User speichert Änderungen |

---

## UC-08: Anschreiben generieren (KI)

| Feld | Inhalt |
|---|---|
| **Akteur** | KI-System, getriggert durch User oder automatisch |
| **Input** | CV-Zusammenfassung + Stellenbeschreibung + optionale Hinweise |
| **Ablauf** | Prompt an Claude API → strukturiertes Anschreiben |
| **Output** | Anschreiben-Text (Markdown oder Plain Text) |
| **Ausnahmen** | API-Fehler → Retry 1x, dann Fehlermeldung |

---

## UC-09: Bewerbung vorbereiten / Status setzen

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Hauptablauf** | 1. User markiert Stelle als "Werde ich bewerben" <br> 2. System setzt Status auf "Vorbereitet" <br> 3. User kann Notizen hinzufügen |

---

## UC-10: Zur Stellenseite navigieren

| Feld | Inhalt |
|---|---|
| **Akteur** | User |
| **Auslöser** | User klickt "Bewerben" Button |
| **Hauptablauf** | 1. System öffnet Original-URL im Standard-Browser <br> 2. Vorbereitetes Anschreiben wird in Zwischenablage kopiert |
| **Nachbedingung** | Status wird auf "Versendet" gesetzt (nach User-Bestätigung) |
