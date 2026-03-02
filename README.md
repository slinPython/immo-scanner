# Immo-Scanner Freiburg

Automatische Immobilien-Suche fuer Freiburg + 30km Umgebung mit Immocation Bierdeckelrechnung.

## Was es macht

- Scrapt taeglich ImmobilienScout24, Immowelt, Kleinanzeigen (kein API-Key noetig)
- Filtert nach Kriterien: 1-4 Zimmer, max 110k/Zimmer, kein Erbbaurecht/Neubau/Versteigerung
- Berechnet Bierdeckelrechnung nach Immocation-Methode
- Schreibt Ergebnisse ins Google Sheet (farbcodiert)
- PWA Dashboard mit Browser-Notifications bei neuen Objekten

## Architektur

```
GitHub Actions (taeglich 16:30 UTC)
  -> scraper.py (Playwright)
  -> evaluator.py (Bierdeckelrechnung)
  -> Google Sheets (via Apps Script)
  -> PWA liest Daten via doGet()
  -> Browser-Notification bei neuen Objekten
```

## Setup

### 1. Repository klonen

```bash
git clone https://github.com/slinpython/immo-scanner.git
cd immo-scanner
```

### 2. Lokal testen

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python main.py --dry-run
```

### 3. Google Sheet vorbereiten

1. Neues Google Sheet erstellen
2. Erweiterungen > Apps Script
3. Inhalt von `apps_script.js` einfuegen
4. Bereitstellen > Neue Bereitstellung > Web-App
5. Ausfuehren als: Ich, Zugriff: Jeder
6. URL kopieren

### 4. GitHub Secret setzen

`GOOGLE_SHEETS_WEBAPP_URL` = die Apps Script Web-App URL

### 5. GitHub Pages aktivieren

Settings > Pages > Source: GitHub Actions

### 6. PWA oeffnen

`https://slinpython.github.io/immo-scanner/`

Web-App URL eingeben und fertig!

## PWA Features

- Dark-Mode Dashboard mit KPI-Cards
- Karten- und Tabellenansicht
- Suche, Filter (Plattform), Sortierung
- Detail-Modal mit vollstaendiger Bierdeckelrechnung
- Browser-Notifications bei neuen Objekten
- Installierbar als App (Handy/Desktop)
- Offline-faehig via Service Worker

## Bierdeckelrechnung

| Parameter | Wert |
|-----------|------|
| Miete Normal/qm | 12 EUR |
| Min. Rendite Normal | 5% |
| Miete WG/Zimmer | 420 EUR |
| Min. Rendite WG | 6% |
| NK ohne Makler | 7% |
| NK mit Makler | 10.57% |

## Dateien

| Datei | Funktion |
|-------|----------|
| main.py | Hauptskript - Orchestrierung |
| scraper.py | Playwright Scraper (IS24, Immowelt, KA) |
| evaluator.py | Bierdeckelrechnung + Scoring |
| notifier.py | Log-basierte Benachrichtigungen |
| config.yaml | Konfiguration |
| apps_script.js | Google Apps Script Endpoint |
| web/index.html | PWA Dashboard |
| web/manifest.json | PWA Manifest |
| web/sw.js | Service Worker |
