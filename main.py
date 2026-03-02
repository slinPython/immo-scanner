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

from scraper import ImmobilienScraper
from evaluator import BierdeckelEvaluator
from notifier import notify

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DB_PATH = Path("immo_scanner.db")
CONFIG_PATH = Path("config.yaml")

EXPECTED_COLUMNS = [
    'id', 'platform', 'title', 'price', 'rooms', 'sqm',
    'address', 'url', 'rendite_normal', 'rendite_wg',
    'kaufpreis_faktor', 'score', 'leerstand', 'wg_geeignet',
    'preis_pro_zimmer', 'empfehlung', 'found_date', 'raw_data'
]


def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("PRAGMA table_info(listings)")
        existing_cols = [row[1] for row in cur.fetchall()]
        if existing_cols and set(existing_cols) != set(EXPECTED_COLUMNS):
            logger.info("Schema geaendert - erstelle Tabelle neu")
            conn.execute("DROP TABLE IF EXISTS listings")
            conn.commit()
    except Exception:
        pass

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
            rendite_normal REAL,
            rendite_wg REAL,
            kaufpreis_faktor REAL,
            score INTEGER DEFAULT 0,
            leerstand INTEGER DEFAULT 0,
            wg_geeignet INTEGER DEFAULT 0,
            preis_pro_zimmer REAL,
            empfehlung TEXT,
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
         rendite_normal, rendite_wg, kaufpreis_faktor, score,
         leerstand, wg_geeignet, preis_pro_zimmer, empfehlung,
         found_date, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing['id'],
        listing['platform'],
        listing['title'],
        listing.get('price'),
        listing.get('rooms'),
        listing.get('sqm'),
        listing.get('address', ''),
        listing.get('url', ''),
        listing.get('rendite_normal'),
        listing.get('rendite_wg'),
        listing.get('kaufpreisfaktor'),
        listing.get('score'),
        int(listing.get('leerstand', False)),
        int(listing.get('wg_geeignet', False)),
        listing.get('preis_pro_zimmer'),
        listing.get('empfehlung', ''),
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
        rn = l.get('rendite_normal')
        sqm_val = l.get('sqm')
        preis = l.get('price')
        qm_preis = round(preis / sqm_val) if preis and sqm_val else 0

        kaufpreis_faktor = l.get('kaufpreisfaktor')
        jahreskaltmiete = round(preis / kaufpreis_faktor) if preis and kaufpreis_faktor else 0

        rendite_str = f"{rn:.1f}%"
        adresse = l.get('address', '')

        if ',' in adresse:
            parts = adresse.rsplit(',', 1)
            strasse = parts[0].strip()
            stadt = parts[1].strip()
        else:
            strasse = adresse
            stadt = ''

        data.append({
            "status": '',
            "url": l.get('url', ''),
            "expose": '',
            "stadt": stadt,
            "strasse": strasse,
            "preis": preis,
            "zimmer": l.get('rooms'),
            "makler": l.get('makler', ''),
            "notiz": '',
            "qm": sqm_val,
            "qm_preis": qm_preis,
            "jahreskaltmiete": jahreskaltmiete,
            "rendite": rendite_str,
            "baujahr": l.get('baujahr', ''),
            "notiz2": ''
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
    webapp_url = os.environ.get('GOOGLE_SHEETS_WEBAPP_URL')

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

            price_val = evaluated.get('price')
            rn_val = evaluated.get('rendite_normal')
            rw_val = evaluated.get('rendite_wg')
            sc_val = evaluated.get('score')
            logger.info(
                f"NEU: [{evaluated['platform']}] {evaluated['title']} | "
                f"{price_val:,.0f} EUR | "
                f"Normal: {rn_val:.1f}% | "
                f"WG: {rw_val:.1f}% | "
                f"Score: {sc_val}"
            )

    logger.info(f"Neue Listings: {len(new_listings)} von {len(raw_listings)}")

    interessante = [
        l for l in new_listings
        if (l.get('score', 0) > 0) and
           (l.get('rendite_normal', 0) >= 5.0 or
            l.get('rendite_wg', 0) >= 6.0)
    ]
    interessante.sort(key=lambda x: x.get('score', 0), reverse=True)
    logger.info(f"Interessante Listings: {len(interessante)}")

    if interessante:
        export_to_google_sheet(interessante, webapp_url, dry_run=args.dry_run)

    notify(interessante, config, dry_run=args.dry_run)

    conn.close()
    logger.info("Immo-Scanner abgeschlossen")


if __name__ == '__main__':
    main()
