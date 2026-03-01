"""
Immobilien Scraper - Playwright-basiert
Scrapt ImmobilienScout24, Immowelt, Kleinanzeigen
Kein API-Key noetig - direkte Browser-Simulation
"""

import hashlib
import logging
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)


def _parse_price(text: str) -> Optional[float]:
      if not text:
                return None
            cleaned = re.sub(r'[^\d,.]', '', text.replace('.', '').replace(',', '.'))
    try:
              return float(cleaned)
except ValueError:
        return None


def _parse_rooms(text: str) -> Optional[float]:
      if not text:
                return None
            m = re.search(r'(\d+[,.]?\d*)', text.replace(',', '.'))
    if m:
              try:
                            return float(m.group(1))
except ValueError:
            return None
    return None


def _parse_sqm(text: str) -> Optional[float]:
      if not text:
                return None
            m = re.search(r'(\d+[,.]?\d*)\s*m', text.replace(',', '.'))
    if m:
              try:
                            return float(m.group(1))
except ValueError:
            return None
    return None


class ImmobilienScraper:
      def __init__(self, config: dict):
                self.config = config
                self.search_config = config.get('search', {})
                self.scraping_config = config.get('scraping', {})
                self.location = self.search_config.get('location', 'Freiburg im Breisgau')
                self.radius_km = self.search_config.get('radius_km', 30)
                self.rooms_min = self.search_config.get('rooms_min', 1)
                self.rooms_max = self.search_config.get('rooms_max', 4)
                self.price_max = self.search_config.get('price_max', 440000)
                self.headless = self.scraping_config.get('headless', True)
                self.timeout = self.scraping_config.get('timeout_seconds', 30) * 1000
                self.delay = self.scraping_config.get('delay_between_requests', 3)
                self.exclude_keywords = [kw.lower() for kw in self.search_config.get('exclude', [])]
                self.platforms = self.scraping_config.get('platforms', ['immoscout24'])

    def _make_id(self, platform: str, url: str) -> str:
              return hashlib.md5(f"{platform}:{url}".encode()).hexdigest()

    def _should_exclude(self, title: str, description: str = '') -> bool:
              text = (title + ' ' + description).lower()
              return any(kw in text for kw in self.exclude_keywords)

    def scrape_all(self, limit: Optional[int] = None) -> list:
              listings = []
              with sync_playwright() as p:
                            browser = p.chromium.launch(
                                              headless=self.headless,
                                              args=['--no-sandbox', '--disable-dev-shm-usage']
                            )
                            context = browser.new_context(
                                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                                           'Chrome/120.0.0.0 Safari/537.36',
                                viewport={'width': 1280, 'height': 900}
                            )

                  if 'immoscout24' in self.platforms:
                                    try:
                                                          results = self._scrape_immoscout(context, limit)
                                                          listings.extend(results)
                                                          logger.info(f"ImmobilienScout24: {len(results)} Listings")
except Exception as e:
                    logger.error(f"ImmobilienScout24 Fehler: {e}")
                time.sleep(self.delay)

            if 'immowelt' in self.platforms:
                              try:
                                                    results = self._scrape_immowelt(context, limit)
                                                    listings.extend(results)
                                                    logger.info(f"Immowelt: {len(results)} Listings")
except Exception as e:
                    logger.error(f"Immowelt Fehler: {e}")
                time.sleep(self.delay)

            if 'kleinanzeigen' in self.platforms:
                              try:
                                                    results = self._scrape_kleinanzeigen(context, limit)
                                                    listings.extend(results)
                                                    logger.info(f"Kleinanzeigen: {len(results)} Listings")
except Exception as e:
                    logger.error(f"Kleinanzeigen Fehler: {e}")

            browser.close()
        return listings

    def _scrape_immoscout(self, context, limit=None) -> list:
              """Scrapt ImmobilienScout24."""
              page = context.new_page()
              listings = []

        # URL fuer Freiburg + Umgebung: geocoordinates oder Ort
              # Freiburg GeoCode: 1276003002
        url = (
                      f"https://www.immobilienscout24.de/Suche/de/freiburg-im-breisgau/wohnung-kaufen"
                      f"?numberofrooms={self.rooms_min}.0-{self.rooms_max}.0"
                      f"&price=-{self.price_max}"
                      f"&radius={self.radius_km}"
                      f"&sorting=2"  # Neueste zuerst
        )

        try:
                      logger.info(f"IS24: Lade {url}")
                      page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
                      time.sleep(3)

            # Cookie-Banner wegklicken falls vorhanden
                      try:
                                        page.click('button[data-testid="uc-accept-all-button"]', timeout=5000)
                                        time.sleep(1)
        except PWTimeout:
                          pass
                      try:
                                        page.click('#usercentrics-root >> text=Alle akzeptieren', timeout=3000)
except PWTimeout:
                pass

            # Listings extrahieren
            page.wait_for_selector('[data-testid="result-list-entry"]', timeout=15000)
            items = page.query_selector_all('[data-testid="result-list-entry"]')
            logger.info(f"IS24: {len(items)} Eintraege gefunden")

            for item in items[:limit] if limit else items:
                              try:
                                                    listing = self._parse_immoscout_item(item, page)
                                                    if listing and not self._should_exclude(listing.get('title', '')):
                                                                              listings.append(listing)
                              except Exception as e:
                                                    logger.debug(f"IS24 Item Parse-Fehler: {e}")

except PWTimeout:
            logger.warning("IS24: Timeout beim Laden")
except Exception as e:
            logger.error(f"IS24: {e}")
finally:
            page.close()

        return listings

    def _parse_immoscout_item(self, item, page) -> Optional[dict]:
              try:
                            # Titel
                            title_el = item.query_selector('[data-testid="result-list-entry-title"]')
                            title = title_el.inner_text().strip() if title_el else ''

                  # URL
                            link_el = item.query_selector('a[href*="/expose/"]')
            url = ''
            if link_el:
                              href = link_el.get_attribute('href')
                              url = f"https://www.immobilienscout24.de{href}" if href and href.startswith('/') else href or ''

            if not url:
                              return None

            # Preis
            price_el = item.query_selector('[data-testid="result-list-entry-price"]')
            price_text = price_el.inner_text() if price_el else ''
            price = _parse_price(price_text)

            # Zimmer + QM
            rooms = None
            sqm = None
            criteria_els = item.query_selector_all('[data-testid="result-list-entry-criteria"] span')
            for el in criteria_els:
                              text = el.inner_text()
                              if 'Zi.' in text or 'Zimmer' in text:
                                                    rooms = _parse_rooms(text)
elif 'm²' in text or 'm2' in text:
                    sqm = _parse_sqm(text)

            # Adresse
            addr_el = item.query_selector('[data-testid="result-list-entry-address"]')
            address = addr_el.inner_text().strip() if addr_el else ''

            listing_id = self._make_id('immoscout24', url)

            return {
                              'id': listing_id,
                              'platform': 'ImmobilienScout24',
                              'title': title,
                              'price': price,
                              'rooms': rooms,
                              'sqm': sqm,
                              'address': address,
                              'url': url,
                              'description': ''
            }
except Exception as e:
            logger.debug(f"Parse IS24 item error: {e}")
            return None

    def _scrape_immowelt(self, context, limit=None) -> list:
              """Scrapt Immowelt."""
        page = context.new_page()
        listings = []

        url = (
                      f"https://www.immowelt.de/liste/freiburg-im-breisgau/wohnungen/kaufen"
                      f"?ami={self.rooms_min}&ama={self.rooms_max}"
                      f"&pma={self.price_max}"
                      f"&umk={self.radius_km}"
                      f"&sd=DESC&sf=RELEVANCE&sp=1"
        )

        try:
                      logger.info(f"Immowelt: Lade {url}")
                      page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
                      time.sleep(3)

            # Cookie-Banner
                      try:
                                        page.click('[data-testid="uc-accept-all-button"]', timeout=5000)
                                        time.sleep(1)
except PWTimeout:
                pass
            try:
                              page.click('button:has-text("Alle akzeptieren")', timeout=3000)
                              time.sleep(1)
except PWTimeout:
                pass

            # Listings
            page.wait_for_selector('[data-testid="estate-item"]', timeout=15000)
            items = page.query_selector_all('[data-testid="estate-item"]')
            logger.info(f"Immowelt: {len(items)} Eintraege gefunden")

            for item in items[:limit] if limit else items:
                              try:
                                                    listing = self._parse_immowelt_item(item)
                                                    if listing and not self._should_exclude(listing.get('title', '')):
                                                                              listings.append(listing)
                              except Exception as e:
                                                    logger.debug(f"Immowelt Item Parse-Fehler: {e}")

except PWTimeout:
            logger.warning("Immowelt: Timeout beim Laden")
except Exception as e:
            logger.error(f"Immowelt: {e}")
finally:
            page.close()

        return listings

    def _parse_immowelt_item(self, item) -> Optional[dict]:
              try:
                            # Titel/Beschreibung
                            title_el = item.query_selector('h2, [data-testid="estate-title"]')
                            title = title_el.inner_text().strip() if title_el else ''

            # URL
            link_el = item.query_selector('a[href*="/expose/"]')
            url = ''
            if link_el:
                              href = link_el.get_attribute('href')
                              url = f"https://www.immowelt.de{href}" if href and href.startswith('/') else href or ''

            if not url and not title:
                              return None

            # Preis
            price_el = item.query_selector('[data-testid="price"]')
            price_text = price_el.inner_text() if price_el else ''
            price = _parse_price(price_text)

            # Details
            rooms = None
            sqm = None
            detail_items = item.query_selector_all('[data-testid="estate-detail-item"]')
            for di in detail_items:
                              text = di.inner_text()
                              if 'Zimmer' in text or 'Zi.' in text:
                                                    rooms = _parse_rooms(text)
elif 'm²' in text:
                    sqm = _parse_sqm(text)

            # Adresse
            addr_el = item.query_selector('[data-testid="address"]')
            address = addr_el.inner_text().strip() if addr_el else ''

            if not url:
                              url = f"https://www.immowelt.de/suche/freiburg-im-breisgau/wohnungen/kaufen"

            listing_id = self._make_id('immowelt', url + title)

            return {
                              'id': listing_id,
                              'platform': 'Immowelt',
                              'title': title,
                              'price': price,
                              'rooms': rooms,
                              'sqm': sqm,
                              'address': address,
                              'url': url,
                              'description': ''
            }
except Exception as e:
            logger.debug(f"Parse Immowelt item error: {e}")
            return None

    def _scrape_kleinanzeigen(self, context, limit=None) -> list:
              """Scrapt Kleinanzeigen (ehem. eBay Kleinanzeigen)."""
        page = context.new_page()
        listings = []

        # Kleinanzeigen URL fuer Immobilien kaufen in Freiburg + Umgebung
        url = (
                      f"https://www.kleinanzeigen.de/s-wohnung-kaufen/freiburg-im-breisgau"
                      f"/anzeige:angebote/preis::{self.price_max}"
                      f"/c196l9366r{self.radius_km}"
        )

        try:
                      logger.info(f"Kleinanzeigen: Lade {url}")
                      page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
                      time.sleep(3)

            # Cookie-Banner
                      try:
                                        page.click('#gdpr-banner-accept', timeout=5000)
                                        time.sleep(1)
except PWTimeout:
                pass
            try:
                              page.click('button:has-text("Einverstanden")', timeout=3000)
                              time.sleep(1)
except PWTimeout:
                pass

            # Listings
            page.wait_for_selector('.aditem', timeout=15000)
            items = page.query_selector_all('.aditem')
            logger.info(f"Kleinanzeigen: {len(items)} Eintraege gefunden")

            for item in items[:limit] if limit else items:
                              try:
                                                    listing = self._parse_kleinanzeigen_item(item)
                                                    if listing and not self._should_exclude(listing.get('title', '')):
                                                                              listings.append(listing)
                              except Exception as e:
                                                    logger.debug(f"Kleinanzeigen Item Parse-Fehler: {e}")

except PWTimeout:
            logger.warning("Kleinanzeigen: Timeout beim Laden")
except Exception as e:
            logger.error(f"Kleinanzeigen: {e}")
finally:
            page.close()

        return listings

    def _parse_kleinanzeigen_item(self, item) -> Optional[dict]:
              try:
                            # Titel
                            title_el = item.query_selector('.ellipsis, h2 a, .aditem-main--top--left')
                            title = title_el.inner_text().strip() if title_el else ''

            # URL
            link_el = item.query_selector('a[href*="/s-anzeige/"]')
            url = ''
            if link_el:
                              href = link_el.get_attribute('href')
                              url = f"https://www.kleinanzeigen.de{href}" if href and href.startswith('/') else href or ''

            if not title:
                              return None

            # Preis
            price_el = item.query_selector('.aditem-main--middle--price-shipping--price')
            price_text = price_el.inner_text() if price_el else ''
            price = _parse_price(price_text)

            # Details aus Beschreibung parsen
            desc_el = item.query_selector('.aditem-main--middle--description')
            description = desc_el.inner_text() if desc_el else ''

            rooms = _parse_rooms(description)
            sqm = _parse_sqm(description)

            # Adresse
            addr_el = item.query_selector('.aditem-main--top--left')
            address = addr_el.inner_text().strip() if addr_el else 'Freiburg'

            if not url:
                              url = "https://www.kleinanzeigen.de/s-wohnung-kaufen/freiburg-im-breisgau/c196"

            listing_id = self._make_id('kleinanzeigen', url + title)

            return {
                              'id': listing_id,
                              'platform': 'Kleinanzeigen',
                              'title': title,
                              'price': price,
                              'rooms': rooms,
                              'sqm': sqm,
                              'address': address,
                              'url': url,
                              'description': description
            }
except Exception as e:
            logger.debug(f"Parse Kleinanzeigen item error: {e}")
            return None
