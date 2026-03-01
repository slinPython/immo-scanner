import hashlib
import logging
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


def _parse_price(text):
    if not text:
        return None
    text = str(text)
    cleaned = re.sub(r'[^\d.,]', '', text)
    cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _parse_rooms(text):
    if not text:
        return None
    m = re.search(r'(\d+[,.]?\d*)\s*Zi', str(text))
    if m:
        try:
            return float(m.group(1).replace(',', '.'))
        except ValueError:
            return None
    return None


def _parse_sqm(text):
    if not text:
        return None
    m = re.search(r'(\d+[,.]?\d*)\s*m', str(text))
    if m:
        try:
            return float(m.group(1).replace(',', '.'))
        except ValueError:
            return None
    return None


class ImmobilienScraper:
    def __init__(self, config):
        self.config = config
        self.search_config = config.get('search', {})
        self.platforms = config.get('platforms', {})
        self.locations = config.get('locations', [])

    def _make_id(self, platform, url_or_title, price=None):
        raw = f"{platform}_{url_or_title}_{price}"
        return hashlib.md5(raw.encode()).hexdigest()

    def scrape_all(self, limit=None):
        all_listings = []
        seen_ids = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='de-DE'
            )
            try:
                for loc in self.locations:
                    loc_name = loc.get('name', 'Unbekannt')
                    logger.info(f"=== Scrape Standort: {loc_name} ===")

                    if self.platforms.get('immoscout', {}).get('enabled', True):
                        try:
                            listings = self._scrape_is24(context, loc, limit)
                            for l in listings:
                                if l['id'] not in seen_ids:
                                    seen_ids.add(l['id'])
                                    all_listings.append(l)
                        except Exception as e:
                            logger.error(f"IS24 {loc_name} Fehler: {e}")

                    if self.platforms.get('kleinanzeigen', {}).get('enabled', True):
                        try:
                            listings = self._scrape_kleinanzeigen(context, loc, limit)
                            for l in listings:
                                if l['id'] not in seen_ids:
                                    seen_ids.add(l['id'])
                                    all_listings.append(l)
                        except Exception as e:
                            logger.error(f"Kleinanzeigen {loc_name} Fehler: {e}")

                    if self.platforms.get('immowelt', {}).get('enabled', True):
                        try:
                            listings = self._scrape_immowelt(context, loc, limit)
                            for l in listings:
                                if l['id'] not in seen_ids:
                                    seen_ids.add(l['id'])
                                    all_listings.append(l)
                        except Exception as e:
                            logger.error(f"Immowelt {loc_name} Fehler: {e}")

            finally:
                context.close()
                browser.close()

        logger.info(f"Gesamt gescrapt: {len(all_listings)} Listings (dedupliziert)")
        return all_listings

    def _scrape_is24(self, context, loc, limit=None):
        listings = []
        page = context.new_page()
        max_pages = self.platforms.get('immoscout', {}).get('max_pages', 3)
        slug = loc.get('slug_is24', '')
        loc_name = loc.get('name', '')

        rooms_min = self.search_config.get('rooms_min', 1)
        rooms_max = self.search_config.get('rooms_max', 4)
        price_max = self.search_config.get('price_max', 440000)

        try:
            for page_num in range(1, max_pages + 1):
                url = (
                    f"https://www.immobilienscout24.de/Suche/de/baden-wuerttemberg/{slug}/wohnung-kaufen"
                    f"?numberofrooms={rooms_min}.0-{rooms_max}.0"
                    f"&price=-{price_max}"
                    f"&sorting=2"
                )
                if page_num > 1:
                    url += f"&pagenumber={page_num}"

                logger.info(f"IS24 [{loc_name}]: Lade Seite {page_num}")
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)

                # Accept cookies
                try:
                    cookie_btn = page.query_selector('#usercentrics-root')
                    if cookie_btn:
                        shadow = cookie_btn.evaluate_handle('el => el.shadowRoot')
                        accept_btn = shadow.as_element().query_selector('button[data-testid="uc-accept-all-button"]')
                        if accept_btn:
                            accept_btn.click()
                            time.sleep(1)
                except Exception:
                    pass

                selectors = [
                    'article.result-list-entry',
                    '[data-testid="result-list-entry"]',
                    'li.result-list__listing',
                    'article[data-obid]',
                ]

                items = []
                for selector in selectors:
                    try:
                        page.wait_for_selector(selector, timeout=3000)
                        items = page.query_selector_all(selector)
                        if items:
                            break
                    except PlaywrightTimeout:
                        continue

                if not items:
                    # Fallback: expose links
                    all_links = page.query_selector_all('a[href*="/expose/"]')
                    if all_links:
                        seen_urls = set()
                        for link in all_links:
                            href = link.get_attribute('href') or ''
                            if '/expose/' in href and href not in seen_urls:
                                seen_urls.add(href)
                                full_url = href if href.startswith('http') else f"https://www.immobilienscout24.de{href}"
                                parent = link
                                for _ in range(5):
                                    p_el = parent.evaluate_handle('el => el.parentElement')
                                    if p_el:
                                        parent = p_el.as_element()
                                    else:
                                        break
                                text_content = parent.inner_text() if parent else ''
                                title_text = link.inner_text().strip()
                                price = _parse_price(text_content)
                                rooms = _parse_rooms(text_content)
                                sqm = _parse_sqm(text_content)
                                if title_text and price:
                                    listing = {
                                        'id': self._make_id('IS24', full_url, price),
                                        'platform': 'ImmobilienScout24',
                                        'title': title_text[:200],
                                        'price': price,
                                        'rooms': rooms,
                                        'sqm': sqm,
                                        'address': loc_name,
                                        'url': full_url,
                                        'description': text_content[:500],
                                    }
                                    listings.append(listing)
                    else:
                        break
                else:
                    for item in (items[:limit] if limit else items):
                        try:
                            listing = self._parse_is24_item(item, loc_name)
                            if listing and not self._is_excluded(listing):
                                listings.append(listing)
                        except Exception as e:
                            logger.debug(f"IS24 item error: {e}")

                if limit and len(listings) >= limit:
                    break

        except Exception as e:
            logger.error(f"IS24 [{loc_name}] error: {e}")
        finally:
            page.close()

        logger.info(f"IS24 [{loc_name}]: {len(listings)} Listings")
        return listings

    def _parse_is24_item(self, item, loc_name=''):
        try:
            title_el = item.query_selector('h2, .result-list-entry__brand-title')
            title = title_el.inner_text().strip() if title_el else ''
            link_el = item.query_selector('a[href*="/expose/"]')
            url = ''
            if link_el:
                href = link_el.get_attribute('href') or ''
                url = href if href.startswith('http') else f"https://www.immobilienscout24.de{href}"
            text = item.inner_text()
            price = None
            for line in text.split('\n'):
                if 'EUR' in line or '\u20ac' in line:
                    p = _parse_price(line)
                    if p and p > 10000:
                        price = p
                        break
            rooms = _parse_rooms(text)
            sqm = _parse_sqm(text)
            addr_el = item.query_selector('.result-list-entry__address')
            address = addr_el.inner_text().strip() if addr_el else loc_name
            if not title:
                return None
            return {
                'id': self._make_id('IS24', url or title, price),
                'platform': 'ImmobilienScout24',
                'title': title[:200],
                'price': price,
                'rooms': rooms,
                'sqm': sqm,
                'address': address,
                'url': url,
                'description': text[:500],
            }
        except Exception as e:
            logger.debug(f"IS24 parse error: {e}")
            return None

    def _scrape_kleinanzeigen(self, context, loc, limit=None):
        listings = []
        page = context.new_page()
        max_pages = self.platforms.get('kleinanzeigen', {}).get('max_pages', 3)
        slug = loc.get('slug_ka', '')
        ka_code = loc.get('ka_code', '')
        loc_name = loc.get('name', '')
        price_max = self.search_config.get('price_max', 440000)

        try:
            for page_num in range(1, max_pages + 1):
                if page_num == 1:
                    url = (
                        f"https://www.kleinanzeigen.de/s-wohnung-kaufen"
                        f"/{slug}/preis::{price_max}"
                        f"/c196{ka_code}"
                    )
                else:
                    url = (
                        f"https://www.kleinanzeigen.de/s-wohnung-kaufen"
                        f"/{slug}/seite:{page_num}"
                        f"/preis::{price_max}"
                        f"/c196{ka_code}"
                    )

                logger.info(f"Kleinanzeigen [{loc_name}]: Lade Seite {page_num}")
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(2)

                # Accept cookies
                try:
                    page.click('#gdpr-banner-accept', timeout=2000)
                    time.sleep(1)
                except Exception:
                    pass

                selectors = ['.aditem', 'article.aditem', '[data-adid]']
                items = []
                for selector in selectors:
                    try:
                        page.wait_for_selector(selector, timeout=5000)
                        items = page.query_selector_all(selector)
                        if items:
                            break
                    except PlaywrightTimeout:
                        continue

                if not items:
                    break

                logger.info(f"Kleinanzeigen [{loc_name}]: {len(items)} Eintraege auf Seite {page_num}")

                for item in (items[:limit] if limit else items):
                    try:
                        listing = self._parse_ka_item(item, loc_name)
                        if listing and not self._is_excluded(listing):
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"KA item error: {e}")

                if limit and len(listings) >= limit:
                    break

        except Exception as e:
            logger.error(f"Kleinanzeigen [{loc_name}] error: {e}")
        finally:
            page.close()

        logger.info(f"Kleinanzeigen [{loc_name}]: {len(listings)} Listings")
        return listings

    def _parse_ka_item(self, item, loc_name=''):
        try:
            title_el = item.query_selector('.aditem-main--middle--title, .text-module-begin, a.ellipsis')
            title = title_el.inner_text().strip() if title_el else ''

            link_el = item.query_selector('a[href*="/s-anzeige/"]')
            url = ''
            if link_el:
                href = link_el.get_attribute('href') or ''
                url = href if href.startswith('http') else f"https://www.kleinanzeigen.de{href}"

            text = item.inner_text()

            price = None
            for line in text.split('\n'):
                if 'EUR' in line or '\u20ac' in line or 'VB' in line:
                    p = _parse_price(line)
                    if p and p > 10000:
                        price = p
                        break

            rooms = _parse_rooms(text)
            sqm = _parse_sqm(text)

            addr_el = item.query_selector('.aditem-main--top--left, .aditem-main--top')
            address = addr_el.inner_text().strip() if addr_el else loc_name

            if not title:
                return None

            return {
                'id': self._make_id('Kleinanzeigen', url or title, price),
                'platform': 'Kleinanzeigen',
                'title': title[:200],
                'price': price,
                'rooms': rooms,
                'sqm': sqm,
                'address': address,
                'url': url,
                'description': text[:500],
            }
        except Exception as e:
            logger.debug(f"KA parse error: {e}")
            return None

    def _scrape_immowelt(self, context, loc, limit=None):
        listings = []
        page = context.new_page()
        max_pages = self.platforms.get('immowelt', {}).get('max_pages', 2)
        slug = loc.get('slug_immowelt', '')
        loc_name = loc.get('name', '')

        rooms_min = self.search_config.get('rooms_min', 1)
        rooms_max = self.search_config.get('rooms_max', 4)
        price_max = self.search_config.get('price_max', 440000)

        try:
            for page_num in range(1, max_pages + 1):
                url = (
                    f"https://www.immowelt.de/liste/{slug}/wohnungen/kaufen"
                    f"?rmi={rooms_min}&rma={rooms_max}"
                    f"&prima={price_max}&sort=relevanz"
                )
                if page_num > 1:
                    url += f"&page={page_num}"

                logger.info(f"Immowelt [{loc_name}]: Lade Seite {page_num}")
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)

                # Accept cookies
                try:
                    page.click('button[data-testid="uc-accept-all-button"]', timeout=2000)
                    time.sleep(1)
                except Exception:
                    pass

                selectors = [
                    '[data-testid="serp-core-classified-card-link"]',
                    'div[class*="EstateItem"]',
                    'a[href*="/expose/"]',
                ]

                items = []
                for selector in selectors:
                    try:
                        page.wait_for_selector(selector, timeout=3000)
                        items = page.query_selector_all(selector)
                        if items:
                            break
                    except PlaywrightTimeout:
                        continue

                if not items:
                    break

                logger.info(f"Immowelt [{loc_name}]: {len(items)} Eintraege auf Seite {page_num}")

                for item in (items[:limit] if limit else items):
                    try:
                        listing = self._parse_immowelt_item(item, loc_name)
                        if listing and not self._is_excluded(listing):
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"Immowelt item error: {e}")

                if limit and len(listings) >= limit:
                    break

        except Exception as e:
            logger.error(f"Immowelt [{loc_name}] error: {e}")
        finally:
            page.close()

        logger.info(f"Immowelt [{loc_name}]: {len(listings)} Listings")
        return listings

    def _parse_immowelt_item(self, item, loc_name=''):
        try:
            text = item.inner_text()
            tag_name = item.evaluate('el => el.tagName')

            if tag_name == 'A':
                href = item.get_attribute('href') or ''
                url = href if href.startswith('http') else f"https://www.immowelt.de{href}"
                title = text.split('\n')[0].strip() if text else ''
            else:
                link_el = item.query_selector('a[href*="/expose/"]')
                url = ''
                if link_el:
                    href = link_el.get_attribute('href') or ''
                    url = href if href.startswith('http') else f"https://www.immowelt.de{href}"
                title_el = item.query_selector('h2, [class*="Title"]')
                title = title_el.inner_text().strip() if title_el else text.split('\n')[0].strip()

            price = None
            rooms = None
            sqm = None
            for line in text.split('\n'):
                if not price and ('EUR' in line or '\u20ac' in line or re.search(r'\d{3}[.]\d{3}', line)):
                    price = _parse_price(line)
                if not rooms and 'Zi' in line:
                    rooms = _parse_rooms(line)
                if not sqm and ('m\u00b2' in line or 'qm' in line.lower()):
                    sqm = _parse_sqm(line)

            if not title:
                return None

            return {
                'id': self._make_id('Immowelt', url or title, price),
                'platform': 'Immowelt',
                'title': title[:200],
                'price': price,
                'rooms': rooms,
                'sqm': sqm,
                'address': loc_name,
                'url': url,
                'description': text[:500],
            }
        except Exception as e:
            logger.debug(f"Immowelt parse error: {e}")
            return None

    def _is_excluded(self, listing):
        exclude_terms = self.search_config.get('exclude', [])
        title = listing.get('title', '').lower()
        desc = listing.get('description', '').lower()
        for term in exclude_terms:
            term_lower = term.lower()
            if term_lower in title or term_lower in desc:
                logger.debug(f"Ausgeschlossen: '{listing.get('title', '')}' wegen '{term}'")
                return True
        return False
