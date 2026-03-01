import hashlib
import logging
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)


def _parse_price(text):
    if not text:
        return None
    text = str(text)
    cleaned = re.sub(r'[^\d]', '', text.replace('.', '').split(',')[0])
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _parse_rooms(text):
    if not text:
        return None
    m = re.search(r'(\d+[,.]?\d*)', str(text).replace(',', '.'))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _parse_sqm(text):
    if not text:
        return None
    m = re.search(r'(\d+[,.]?\d*)\s*m', str(text).replace(',', '.'))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


class ImmobilienScraper:
    def __init__(self, config):
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

    def _make_id(self, platform, url):
        return hashlib.md5(f"{platform}:{url}".encode()).hexdigest()

    def _should_exclude(self, title, description=''):
        text = (title + ' ' + description).lower()
        return any(kw in text for kw in self.exclude_keywords)

    def scrape_all(self, limit=None):
        listings = []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
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

    def _scrape_immoscout(self, context, limit=None):
        page = context.new_page()
        listings = []
        url = (
            f"https://www.immobilienscout24.de/Suche/de/freiburg-im-breisgau/wohnung-kaufen"
            f"?numberofrooms={self.rooms_min}.0-{self.rooms_max}.0"
            f"&price=-{self.price_max}&radius={self.radius_km}&sorting=2"
        )
        try:
            logger.info(f"IS24: Lade {url}")
            page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
            time.sleep(3)
            for selector in ['button[data-testid="uc-accept-all-button"]', 'button:text("Alle akzeptieren")']:
                try:
                    page.click(selector, timeout=3000)
                    time.sleep(1)
                    break
                except Exception:
                    pass
            page.wait_for_selector('[data-testid="result-list-entry"]', timeout=15000)
            items = page.query_selector_all('[data-testid="result-list-entry"]')
            logger.info(f"IS24: {len(items)} Eintraege gefunden")
            for item in (items[:limit] if limit else items):
                try:
                    listing = self._parse_is24_item(item)
                    if listing and not self._should_exclude(listing.get('title', '')):
                        listings.append(listing)
                except Exception as e:
                    logger.debug(f"IS24 parse error: {e}")
        except Exception as e:
            logger.error(f"IS24: {e}")
        finally:
            page.close()
        return listings

    def _parse_is24_item(self, item):
        try:
            title_el = item.query_selector('[data-testid="result-list-entry-title"]')
            title = title_el.inner_text().strip() if title_el else ''
            link_el = item.query_selector('a[href*="/expose/"]')
            url = ''
            if link_el:
                href = link_el.get_attribute('href') or ''
                url = f"https://www.immobilienscout24.de{href}" if href.startswith('/') else href
            if not url:
                return None
            price_el = item.query_selector('[data-testid="result-list-entry-price"]')
            price = _parse_price(price_el.inner_text() if price_el else '')
            rooms = None
            sqm = None
            for el in item.query_selector_all('[data-testid="result-list-entry-criteria"] span'):
                text = el.inner_text()
                if 'Zi.' in text or 'Zimmer' in text:
                    rooms = _parse_rooms(text)
                elif 'm' in text:
                    sqm = _parse_sqm(text)
            addr_el = item.query_selector('[data-testid="result-list-entry-address"]')
            address = addr_el.inner_text().strip() if addr_el else ''
            return {
                'id': self._make_id('immoscout24', url),
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
            logger.debug(f"IS24 item error: {e}")
            return None

    def _scrape_immowelt(self, context, limit=None):
        page = context.new_page()
        listings = []
        url = (
            f"https://www.immowelt.de/liste/freiburg-im-breisgau/wohnungen/kaufen"
            f"?ami={self.rooms_min}&ama={self.rooms_max}&pma={self.price_max}"
            f"&umk={self.radius_km}&sd=DESC&sf=RELEVANCE&sp=1"
        )
        try:
            logger.info(f"Immowelt: Lade {url}")
            page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
            time.sleep(3)
            for selector in ['[data-testid="uc-accept-all-button"]', 'button:text("Alle akzeptieren")']:
                try:
                    page.click(selector, timeout=3000)
                    time.sleep(1)
                    break
                except Exception:
                    pass
            page.wait_for_selector('[data-testid="estate-item"]', timeout=15000)
            items = page.query_selector_all('[data-testid="estate-item"]')
            logger.info(f"Immowelt: {len(items)} Eintraege")
            for item in (items[:limit] if limit else items):
                try:
                    listing = self._parse_immowelt_item(item)
                    if listing and not self._should_exclude(listing.get('title', '')):
                        listings.append(listing)
                except Exception as e:
                    logger.debug(f"Immowelt parse error: {e}")
        except Exception as e:
            logger.error(f"Immowelt: {e}")
        finally:
            page.close()
        return listings

    def _parse_immowelt_item(self, item):
        try:
            title_el = item.query_selector('h2, [data-testid="estate-title"]')
            title = title_el.inner_text().strip() if title_el else ''
            link_el = item.query_selector('a[href*="/expose/"]')
            url = ''
            if link_el:
                href = link_el.get_attribute('href') or ''
                url = f"https://www.immowelt.de{href}" if href.startswith('/') else href
            if not url and not title:
                return None
            price_el = item.query_selector('[data-testid="price"]')
            price = _parse_price(price_el.inner_text() if price_el else '')
            rooms = None
            sqm = None
            for di in item.query_selector_all('[data-testid="estate-detail-item"]'):
                text = di.inner_text()
                if 'Zimmer' in text or 'Zi.' in text:
                    rooms = _parse_rooms(text)
                elif 'm' in text:
                    sqm = _parse_sqm(text)
            addr_el = item.query_selector('[data-testid="address"]')
            address = addr_el.inner_text().strip() if addr_el else ''
            if not url:
                url = "https://www.immowelt.de/suche/freiburg-im-breisgau/wohnungen/kaufen"
            return {
                'id': self._make_id('immowelt', url + title),
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
            logger.debug(f"Immowelt item error: {e}")
            return None

    def _scrape_kleinanzeigen(self, context, limit=None):
        page = context.new_page()
        listings = []
        url = (
            f"https://www.kleinanzeigen.de/s-wohnung-kaufen/freiburg-im-breisgau"
            f"/anzeige:angebote/preis::{self.price_max}/c196l9366r{self.radius_km}"
        )
        try:
            logger.info(f"Kleinanzeigen: Lade {url}")
            page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
            time.sleep(3)
            for selector in ['#gdpr-banner-accept', 'button:text("Einverstanden")']:
                try:
                    page.click(selector, timeout=3000)
                    time.sleep(1)
                    break
                except Exception:
                    pass
            page.wait_for_selector('.aditem', timeout=15000)
            items = page.query_selector_all('.aditem')
            logger.info(f"Kleinanzeigen: {len(items)} Eintraege")
            for item in (items[:limit] if limit else items):
                try:
                    listing = self._parse_ka_item(item)
                    if listing and not self._should_exclude(listing.get('title', '')):
                        listings.append(listing)
                except Exception as e:
                    logger.debug(f"KA parse error: {e}")
        except Exception as e:
            logger.error(f"Kleinanzeigen: {e}")
        finally:
            page.close()
        return listings

    def _parse_ka_item(self, item):
        try:
            title_el = item.query_selector('h2 a, .ellipsis')
            title = title_el.inner_text().strip() if title_el else ''
            link_el = item.query_selector('a[href*="/s-anzeige/"]')
            url = ''
            if link_el:
                href = link_el.get_attribute('href') or ''
                url = f"https://www.kleinanzeigen.de{href}" if href.startswith('/') else href
            if not title:
                return None
            price_el = item.query_selector('.aditem-main--middle--price-shipping--price')
            price = _parse_price(price_el.inner_text() if price_el else '')
            desc_el = item.query_selector('.aditem-main--middle--description')
            description = desc_el.inner_text() if desc_el else ''
            rooms = _parse_rooms(description)
            sqm = _parse_sqm(description)
            addr_el = item.query_selector('.aditem-main--top--left')
            address = addr_el.inner_text().strip() if addr_el else 'Freiburg'
            if not url:
                url = "https://www.kleinanzeigen.de/s-wohnung-kaufen/freiburg-im-breisgau/c196"
            return {
                'id': self._make_id('kleinanzeigen', url + title),
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
            logger.debug(f"KA item error: {e}")
            return None
