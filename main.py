#!/usr/bin/env python3
"""
Immo-Scanner Freiburg - Hauptskript
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml
from twilio.rest import Client as TwilioClient

from scraper import ImmobilienScraper
from evaluator import BierdeckelEvaluator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DB_PATH = Path("immo_scanner.db")
CONFIG_PATH = Path("config.yaml")


def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            platform TEXT,
            title TEXT,
            price REAL,
            rooms REAL,
            sqm REAL,
            address TEXT,
            url TEXT,
            score_normal REAL,
            score_wg REAL,
            rendite_normal REAL,
            rendite_wg REAL,
            kaufpreis_faktor REAL,
            gesamtscore INTEGER,
            leerstand INTEGER DEFAULT 0,
            wg_geeignet INTEGER DEFAULT 0,
            found_date TEXT,
            raw_data TEXT
        )
    """)
    conn.commit()
    return conn


def is_new_listing(conn, listing_id):
    cur = conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,))
    return cur.fetchone() is None


def save_listing(conn, listing):
    conn.execute("""
        INSERT OR IGNORE INTO listings
        (id, platform, title, price, rooms, sqm, address, url,
         score_normal, score_wg, rendite_normal, rendite_wg,
         kaufpreis_faktor, gesamtscore, leerstand, wg_geeignet,
         found_date, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing['id'], listing['platform'], listing['title'],
        listing.get('price'), listing.get('rooms'), listing.get('sqm'),
        listing.get('address', ''), listing.get('url', ''),
        listing.get('score_normal', 0), listing.get('score_wg', 0),
        listing.get('rendite_normal', 0), listing.get('rendite_wg', 0),
        listing.get('kaufpreis_faktor', 0), listing.get('gesamtscore', 0),
        int(listing.get('leerstand', False)),
        int(listing.get('wg_geeignet', False)),
        datetime.now().isoformat(),
        json.dumps(listing, ensure_ascii=False)
    ))
    conn.commit()


def export_to_google_sheet(listings, webapp_url, dry_run=False):
    if dry_run:
        logger.info(f"[DRY-RUN] Wuerde {len(listings)} Eintraege ins Google Sheet schreiben")
        return True

    if not webapp_url:
        logger.warning("GOOGLE_SHEETS_WEBAPP_URL nicht gesetzt - Sheet-Export uebersprungen")
        return False

    data = []
    for l in listings:
        rendite_normal_str = f"{l.get('rendite_normal', 0):.1f}%"
        rendite_wg_str = f"{l.get('rendite_wg', 0):.1f}%"
        ok_normal = "OK" if l.get('rendite_normal', 0) >= 5.0 else "NEIN"
        ok_wg = "OK" if l.get('rendite_wg', 0) >= 6.0 else "NEIN"
        data.append({
            "datum": datetime.now().strftime("%Y-%m-%d"),
            "platform": l.get('platform', ''),
            "titel": l.get('title', ''),
            "preis": l.get('price', 0),
            "zimmer": l.get('rooms', 0),
            "qm": l.get('sqm', 0),
            "adresse": l.get('address', ''),
            "url": l.get('url', ''),
            "rendite_normal": rendite_normal_str,
            "ok_normal": ok_normal,
            "rendite_wg": rendite_wg_str,
            "ok_wg": ok_wg,
            "kauf_faktor": round(l.get('kaufpreis_faktor', 0), 1),
            "score": l.get('gesamtscore', 0),
            "leerstand": "Ja" if l.get('leerstand') else "Nein",
            "wg_geeignet": "Ja" if l.get('wg_geeignet') else "Nein"
        })

    try:
        response = requests.post(
            webapp_url,
            json={"listings": data},
            timeout=30
        )
        if response.status_code == 200:
            logger.info(f"Google Sheet: {len(listings)} Eintraege erfolgreich geschrieben")
            return True
        else:
            logger.error(f"Google Sheet Fehler: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Google Sheet Export fehlgeschlagen: {e}")
        return False


def send_sms(listings, config, dry_run=False):
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_number = os.environ.get('TWILIO_FROM_NUMBER')
    to_number = os.environ.get('TWILIO_TO_NUMBER')

    if dry_run:
        logger.info(f"[DRY-RUN] Wuerde SMS senden mit {len(listings)} Objekten")
        return True

    if not all([account_sid, auth_token, from_number, to_number]):
        logger.warning("Twilio-Credentials fehlen - SMS uebersprungen")
        return False

    if not listings:
        body = f"[Immo-Scanner Freiburg] {datetime.now().strftime('%d.%m.%Y')}: Keine neuen Objekte gefunden."
    else:
        top5 = sorted(listings, key=lambda x: x.get('gesamtscore', 0), reverse=True)[:5]
        lines = [f"Immo-Scanner {datetime.now().strftime('%d.%m.')}: {len(listings)} neue Objekte!"]
        for i, l in enumerate(top5, 1):
            preis_k = int(l.get('price', 0) / 1000)
            lines.append(
                f"{i}. {l.get('rooms','?')}Zi {preis_k}k | "
                f"N:{l.get('rendite_normal',0):.1f}% WG:{l.get('rendite_wg',0):.1f}% | "
                f"Score:{l.get('gesamtscore',0)}"
            )
        if len(listings) > 5:
            lines.append(f"+ {len(listings)-5} weitere >> Google Sheet")
        body = "\n".join(lines)

    try:
        client = TwilioClient(account_sid, auth_token)
        message = client.messages.create(body=body, from_=from_number, to=to_number)
        logger.info(f"SMS gesendet: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"SMS senden fehlgeschlagen: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Immo-Scanner Freiburg')
    parser.add_argument('--dry-run', action='store_true', help='Testlauf')
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Immo-Scanner Freiburg gestartet")
    logger.info(f"Dry-Run: {args.dry_run}")
    logger.info("=" * 60)

    config = load_config()
    conn = init_db()
    evaluator = BierdeckelEvaluator(config)
    scraper = ImmobilienScraper(config)

    webapp_url = os.environ.get('GOOGLE_SHEETS_WEBAPP_URL', '')

    try:
        raw_listings = scraper.scrape_all(limit=args.limit)
        logger.info(f"Gesamt gescrapt: {len(raw_listings)} Listings")
    except Exception as e:
        logger.error(f"Scraping fehlgeschlagen: {e}")
        raw_listings = []

    new_listings = []
    for listing in raw_listings:
        if is_new_listing(conn, listing['id']):
            evaluated = evaluator.evaluate(listing)
            save_listing(conn, evaluated)
            new_listings.append(evaluated)
            logger.info(
                f"NEU: [{evaluated['platform']}] {evaluated['title']} | "
                f"{evaluated.get('price', 0):,.0f}EUR | "
                f"Normal: {evaluated.get('rendite_normal', 0):.1f}% | "
                f"WG: {evaluated.get('rendite_wg', 0):.1f}% | "
                f"Score: {evaluated.get('gesamtscore', 0)}"
            )

    logger.info(f"Neue Listings: {len(new_listings)} von {len(raw_listings)}")

    interessante = [
        l for l in new_listings
        if l.get('gesamtscore', 0) >= 30
        or l.get('rendite_normal', 0) >= 5.0
        or l.get('rendite_wg', 0) >= 6.0
    ]
    interessante.sort(key=lambda x: x.get('gesamtscore', 0), reverse=True)

    logger.info(f"Interessante Listings: {len(interessante)}")

    if interessante:
        export_to_google_sheet(interessante, webapp_url, dry_run=args.dry_run)

    send_sms(interessante, config, dry_run=args.dry_run)

    conn.close()
    logger.info("Immo-Scanner abgeschlossen")


if __name__ == '__main__':
    main()
