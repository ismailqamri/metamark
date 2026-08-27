#!/usr/bin/env python3
# amazon_book_friendly_scraper.py
"""
Generalized Amazon product scraper with extra support for Book layouts.

- Robust parsing for detailBullets (books), productDetails tables, technical specs.
- Safe handling for empty strings and absent nodes.
- Extracts: title, asin, price (float), currency (ISO when detectable), country, language,
  images, rating, reviews_count, description, about_author, product_details, technical_details,
  availability, shipping_details.
"""

from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
import google.generativeai as genai
import os

# Shared hardened page fetcher (UA rotation, cookie priming, retries,
# bot-wall detection, and an optional headless-browser fallback).
try:
    from amazon_scraper.fetcher import get_fetcher
except ImportError:  # allow running this file directly from amazon_scraper/
    from fetcher import get_fetcher

# === Gemini (google.generativeai) setup (OPTION A) ===
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or "AIzaSyCRdKzY4bBefy0w3n_WUPC4uset4hED6hk"

genai.configure(api_key=GOOGLE_API_KEY)
GEMINI_AVAILABLE = True

DEFAULT_HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

def _clean_key(k: str) -> str:
    """Normalize keys found in product details (strip weird whitespace/controls)."""
    if not k:
        return k
    # remove invisible separators and non-printable characters
    k = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', k)
    k = re.sub(r'\s+', ' ', k)  # normalize whitespace
    return k.strip().rstrip(':')

def _safe_get_text(node) -> str:
    if not node:
        return ''
    return node.get_text(separator=' ', strip=True)

class AmazonScraper:
    def __init__(self, headers: Dict[str, str] = None, timeout: int = 15):
        self.headers = headers or DEFAULT_HEADERS
        self.timeout = timeout
        # All HTTP fetching is delegated to the shared, hardened fetcher.
        self.fetcher = get_fetcher()

    def extract_asin(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        """Extract ASIN from common places."""
        if url:
            # /dp/ASIN or /product/ASIN
            m = re.search(r'/dp/([A-Z0-9]{9,13})', url)
            if m:
                return m.group(1)
            m = re.search(r'/gp/product/([A-Z0-9]{9,13})', url)
            if m:
                return m.group(1)

        if soup:
            # input#ASIN
            tag = soup.find('input', {'id': 'ASIN'})
            if tag and tag.get('value'):
                return tag['value'].strip()
            # any data-asin attribute
            alt = soup.find(attrs={'data-asin': True})
            if alt:
                val = alt.get('data-asin')
                if val:
                    return val.strip()
            # detail bullets: find ISBN or ASIN lines
            db = soup.find('div', id='detailBullets_feature_div') or soup.find('div', id='detailBulletsWrapper_feature_div')
            if db:
                text = db.get_text(separator=' | ', strip=True)
                # try ISBN-10/13
                m = re.search(r'ISBN-10[:\s]*([0-9Xx\-]+)', text)
                if m:
                    return m.group(1).replace('-', '').strip()
                m = re.search(r'ISBN-13[:\s]*([0-9\-]+)', text)
                if m:
                    return m.group(1).replace('-', '').strip()
            # ld+json sku
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, dict):
                        sku = data.get('sku') or data.get('productID')
                        if sku:
                            return str(sku).strip()
                except Exception:
                    pass
        return None

    # -------------------- NEW: seller extraction --------------------
    def _get_seller_info(self, soup):
        """
        Extract seller/store name + store URL from the top of an Amazon product page.
        Example HTML:
        <a id="bylineInfo" class="a-link-normal" href="/stores/ChampionSports/...">
            Visit the Champion Sports Store
        </a>
        """
        link = soup.find("a", id="bylineInfo")
        if not link:
            return None

        name = link.get_text(strip=True)
        href = link.get("href")

        # Normalize full URL
        store_url = None
        if href:
            if href.startswith("http"):
                store_url = href
            else:
                store_url = "https://www.amazon.in" + href

        return {
            "raw_name": name,
            "store_url": store_url
        }

    def _ai_enrich_seller(self, name, store_url):
        if not name:
            return None

        prompt = f"""
        You MUST respond with ONLY valid JSON. No markdown, no explanations.
        LOCATION MUST BE SPECIFIC (city, state, country).

        Provide 5 fields:
        "location": "...",
        "seller_type": "...",
        "description": "...",
        "reputation": "...",
        "other_notes": "..."

        Do NOT include any additional text.

        Seller Name: {name}
        Seller URL: {store_url}
        """

        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            resp = model.generate_content(prompt)

            text = resp.text.strip()

            # If model surrounds JSON in markdown ``` blocks → clean them
            if text.startswith("```"):
                text = text.strip("`")
                # Remove ```json or ``` if present
                text = text.replace("json", "", 1).strip()

            return json.loads(text)

        except Exception as e:
            return {"error": str(e)}
        
    def _get_price_per_unit(self, soup):
        """
        Extracts price-per-unit like: (₹31.55 /100 g)
        Returns: {"value": float, "unit": "100 g", "currency": "INR"} or None
        """
        try:
            # Pattern examples: "₹31.55 /100 g", "₹210 /kg", "(₹55 / 50 ml)"
            pattern = re.compile(r'([₹$£€¥]\s*\d+[\.\d]*)\s*/\s*([\d]+\s*\w+)', re.I)

            # Search inside all spans
            spans = soup.find_all("span")
            for sp in spans:
                text = sp.get_text(" ", strip=True)
                m = pattern.search(text)
                if m:
                    price_text = m.group(1)
                    unit_text = m.group(2)

                    # Detect currency
                    symbol_map = {
                        '₹': 'INR', 'Rs.': 'INR',
                        '$': 'USD', '£': 'GBP',
                        '€': 'EUR', '¥': 'JPY'
                    }
                    currency = None
                    for sym, code in symbol_map.items():
                        if sym in price_text:
                            currency = code
                            break

                    # Clean price numeric
                    price_num = re.sub(r'[^\d\.]', '', price_text)
                    try:
                        price_value = float(price_num)
                        return {
                            "value": price_value,
                            "unit": unit_text.strip(),
                            "currency": currency or "UNKNOWN"
                        }
                    except:
                        pass

            return None

        except Exception as e:
            print("Error parsing price per unit:", e)
            return None

    def scrape_product(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            html = self.fetcher.fetch(url)
            if not html:
                print(f"[ERROR] Could not retrieve page (blocked or unreachable): {url}")
                return None
            soup = BeautifulSoup(html, 'html.parser')

            product = {
                'url': url,
                'asin': self.extract_asin(url, soup),
                'title': self._get_title(soup),
                'price': self._get_price(soup),
                'currency': self._get_currency(soup),
                'country': self._get_country_from_url(url),
                'language': self._get_language(soup),
                'images': self.get_product_images(soup),
                'rating': self._get_rating(soup),
                'reviews_count': self._get_reviews_count(soup),
                'description': self._get_description(soup),
                'about_author': self._get_about_author(soup),
                'product_details': self._get_product_details(soup),
                'technical_details': self._get_technical_details(soup),
                'availability': self._get_availability(soup),
                'additional_info': self._get_additional_info_tables(soup),
                'shipping_details': self._get_shipping_details(soup),
                'price_per_unit': self._get_price_per_unit(soup)
            }

            # --- SELLER: extract link, visit store, analyze with Gemini ---
            # --- SELLER INFORMATION ---
            seller_raw = self._get_seller_info(soup)

            seller_info = None
            if seller_raw:
                seller_info = {
                    "name": seller_raw["raw_name"],
                    "store_url": seller_raw["store_url"],
                    "ai_insights": self._ai_enrich_seller(
                        seller_raw["raw_name"], seller_raw["store_url"]
                    )
                }

            product["seller"] = seller_info

            return product
        except Exception as e:
            print(f"[ERROR] Error parsing product: {e}")
            return None

    # --- Extractors ----

    def _get_title(self, soup: BeautifulSoup) -> Optional[str]:
        t = soup.find('span', id='productTitle')
        if t:
            return t.get_text(strip=True)
        og = soup.find('meta', property='og:title')
        if og and og.get('content'):
            return og['content'].strip()
        if soup.title:
            return soup.title.get_text(strip=True)
        return None

    def _get_price(self, soup: BeautifulSoup) -> Optional[float]:
        def parse_price_text(txt: str) -> Optional[float]:
            if not txt:
                return None
            txt = txt.strip()
            m = re.search(r'[\d\.,]+', txt.replace('\xa0', ' '))
            if not m:
                return None
            num = m.group(0)
            # remove commas (thousand separators) and parse dot decimal
            num_clean = num.replace(',', '')
            try:
                return float(num_clean)
            except Exception:
                return None

        # 1) a-offscreen most reliable
        off = soup.find('span', class_='a-offscreen')
        if off and off.get_text(strip=True):
            p = parse_price_text(off.get_text())
            if p is not None:
                return p

        # 2) priceblock_*
        for pid in ('priceblock_ourprice', 'priceblock_dealprice', 'priceblock_saleprice'):
            el = soup.find('span', id=pid)
            if el and el.get_text(strip=True):
                p = parse_price_text(el.get_text())
                if p is not None:
                    return p

        # 3) numeric from whole+fraction
        whole = soup.find('span', class_='a-price-whole')
        if whole:
            frac = soup.find('span', class_='a-price-fraction')
            try:
                whole_text = whole.get_text().replace(',', '').strip()
                frac_text = frac.get_text().strip() if frac else '00'
                frac_digits = re.sub('[^0-9]', '', frac_text)
                return float(f"{whole_text}.{frac_digits}")
            except Exception:
                pass

        # 4) ld+json offers.price
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    offers = data.get('offers')
                    if isinstance(offers, dict):
                        price = offers.get('price') or (offers.get('priceSpecification') or {}).get('price')
                        if price:
                            try:
                                return float(price)
                            except Exception:
                                pass
            except Exception:
                pass

        # 5) fallback: currency symbol + number anywhere in text (safe regex)
        text = soup.get_text(separator=' ')
        try:
            m = re.search(r'([$£€¥₹]\s?[0-9][0-9,]*\.?[0-9]*)', text)
            if m:
                maybe = m.group(0)
                return parse_price_text(maybe)
        except Exception:
            pass

        return None

    def _get_currency(self, soup: BeautifulSoup) -> Optional[str]:
        # safe check
        def map_symbol(s):
            mapping = {'$': 'USD', '£': 'GBP', '€': 'EUR', '¥': 'JPY', '₹': 'INR'}
            return mapping.get(s, s)

        off = soup.find('span', class_='a-offscreen')
        txt = (off.get_text() if off else '') or ''
        txt = txt.strip()
        if txt:
            # try first char, but only if non-empty
            if txt[0] in ('$','£','€','¥','₹'):
                return map_symbol(txt[0])
            m = re.search(r'([£€¥₹$])', txt)
            if m:
                return map_symbol(m.group(1))

        # other ids
        for pid in ('priceblock_ourprice', 'priceblock_dealprice', 'priceblock_saleprice'):
            el = soup.find('span', id=pid)
            if el:
                t = (el.get_text() or '').strip()
                m = re.search(r'([£€¥₹$])', t)
                if m:
                    return map_symbol(m.group(1))

        # ld+json
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    offers = data.get('offers')
                    if isinstance(offers, dict):
                        cur = offers.get('priceCurrency')
                        if cur:
                            return cur.upper()
            except Exception:
                pass

        return None

    def _get_country_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        try:
            hostname = urlparse(url).hostname or ''
            if hostname.endswith('.co.uk'):
                return 'UK'
            if hostname.endswith('.de'):
                return 'DE'
            if hostname.endswith('.fr'):
                return 'FR'
            if hostname.endswith('.co.jp') or hostname.endswith('.jp'):
                return 'JP'
            if hostname.endswith('.in'):
                return 'IN'
            if hostname.endswith('.ca'):
                return 'CA'
            if hostname.endswith('.com.au'):
                return 'AU'
            if hostname.endswith('.com.mx'):
                return 'MX'
            if hostname.endswith('.com'):
                return 'US'
            parts = hostname.split('.')
            if len(parts) >= 2:
                return parts[-1].upper()
        except Exception:
            pass
        return None

    def _get_language(self, soup: BeautifulSoup) -> Optional[str]:
        html = soup.find('html')
        if html and html.get('lang'):
            return html.get('lang')
        meta = soup.find('meta', attrs={'http-equiv': 'content-language'})
        if meta and meta.get('content'):
            return meta.get('content')
        return None

    def _clean_image_url(self, url: str) -> str:
            """
            Removes Amazon resizing parameters (e.g., ._AC_SL1500_) 
            to get the full-resolution image.
            """
            if not url:
                return ""
            # Regex explanation:
            # Find pattern starting with ._ 
            # followed by uppercase, digits, commas, dots, hyphens
            # ending just before the file extension (.jpg, .png)
            return re.sub(r'\._[A-Z0-9,_\-\.]+(\.[a-zA-Z0-9]+)$', r'\1', url)

    def _convert_thumbnail_to_fullsize(self, url: str) -> str:
        """
        Convert Amazon thumbnail URLs to full-size images.
        Removes size constraints like ._SX38_SY50_, ._AC_US40_, etc.
        """
        if not url or 'media-amazon.com' not in url:
            return ""
        
        # Remove all size specifications before the file extension
        clean_url = re.sub(r'\._[A-Z]{2}[0-9_,]+_', '.', url)
        
        # Request high-res size (1500px)
        clean_url = re.sub(r'\.([a-z]+)$', r'._SL1500_.\1', clean_url)
        
        return clean_url

    def _is_valid_image_url(self, url: str) -> bool:
        """Validate if a URL is a proper image URL"""
        if not url or 'media-amazon.com/images/I/' not in url:
            return False
        if not re.search(r'\.(jpg|jpeg|png)$', url, re.IGNORECASE):
            return False
        if "'" in url or '"' in url or '\n' in url:
            return False
        return True

    def get_product_images(self,soup: BeautifulSoup) -> List[str]:
        """
        Extract all product images from the static HTML.
        Returns a deduplicated list of high-resolution image URLs.
        """
        found_urls = set()

        try:
            # Strategy 1: Extract from image thumbnails container
            image_block = soup.find('div', {'id': 'altImages'})
            if image_block:
                thumb_items = image_block.find_all('li', class_='item')
                for item in thumb_items:
                    thumb_img = item.find('img')
                    if thumb_img and thumb_img.get('src'):
                        full_url = self._convert_thumbnail_to_fullsize(thumb_img.get('src'))
                        if full_url and self._is_valid_image_url(full_url):
                            found_urls.add(full_url)

            # Strategy 2: Extract from landing image with dynamic image data
            landing_img = soup.find('img', {'id': 'landingImage'})
            if landing_img:
                # Extract dynamic images JSON
                dynamic_images = landing_img.get('data-a-dynamic-image')
                if dynamic_images:
                    try:
                        image_dict = json.loads(dynamic_images)
                        for url in image_dict.keys():
                            full_url = self._convert_thumbnail_to_fullsize(url)
                            if full_url and self._is_valid_image_url(full_url):
                                found_urls.add(full_url)
                    except json.JSONDecodeError:
                        pass
                
                # Also get the immediate src
                if landing_img.get('src'):
                    full_url = self._convert_thumbnail_to_fullsize(landing_img.get('src'))
                    if full_url and self._is_valid_image_url(full_url):
                        found_urls.add(full_url)

            # Strategy 3: Check image block script data
            scripts = soup.find_all('script', type='text/javascript')
            for script in scripts:
                if script.string and 'ImageBlockATF' in script.string:
                    urls = re.findall(r'https://m\.media-amazon\.com/images/I/[A-Za-z0-9+\-_.]+\.(?:jpg|jpeg|png)', script.string)
                    for url in urls:
                        full_url = self._convert_thumbnail_to_fullsize(url)
                        if full_url and self._is_valid_image_url(full_url):
                            found_urls.add(full_url)

        except Exception as e:
            print(f"Error extracting images: {e}")
        
        return sorted(list(found_urls))

    def _get_rating(self, soup: BeautifulSoup) -> Optional[float]:
        rating_elem = soup.find('span', class_='a-icon-alt') or soup.find('i', class_='a-icon-star')
        if rating_elem and rating_elem.get_text():
            m = re.search(r'(\d+(\.\d+)?)', rating_elem.get_text())
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    agg = data.get('aggregateRating')
                    if isinstance(agg, dict):
                        val = agg.get('ratingValue') or agg.get('rating')
                        if val:
                            try:
                                return float(val)
                            except Exception:
                                pass
            except Exception:
                pass
        return None

    def _get_reviews_count(self, soup: BeautifulSoup) -> Optional[int]:
        rev = soup.find('span', id='acrCustomerReviewText')
        if rev and rev.get_text():
            txt = rev.get_text().strip()
            m = re.search(r'([\d,]+)', txt)
            if m:
                return int(m.group(1).replace(',', ''))
        # detail bullets variant
        db = soup.find('div', id='detailBullets_feature_div') or soup.find('div', id='detailBulletsWrapper_feature_div')
        if db:
            m = re.search(r'(\d{1,3}(?:,\d{3})*)\s+ratings?', db.get_text(), re.I)
            if m:
                return int(m.group(1).replace(',', ''))
        # ld+json
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    agg = data.get('aggregateRating')
                    if isinstance(agg, dict):
                        rc = agg.get('reviewCount') or agg.get('ratingCount')
                        if rc:
                            try:
                                return int(rc)
                            except Exception:
                                pass
            except Exception:
                pass
        return None

    def _get_description(self, soup: BeautifulSoup) -> Optional[str]:
        # common productDescription
        desc = soup.find('div', id='productDescription')
        if desc:
            for s in desc(['script', 'style']):
                s.extract()
            text = desc.get_text(separator=' ', strip=True)
            if text:
                return text

        # Books example: expanded description container (from your snippet)
        exp = soup.find('div', attrs={'data-expanded': True})
        if exp:
            txt = exp.get_text(separator=' ', strip=True)
            if txt:
                return txt

        # feature bullets
        bullets = soup.find('div', id='feature-bullets')
        if bullets:
            items = [span.get_text(strip=True) for span in bullets.select('span.a-list-item') if span.get_text(strip=True)]
            if items:
                return ' '.join(items)

        # ld+json
        for s in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(s.string or "{}")
                if isinstance(data, dict):
                    d = data.get('description')
                    if d:
                        return str(d).strip()
            except Exception:
                pass

        return None

    def _get_about_author(self, soup: BeautifulSoup) -> Optional[str]:
        # find the about the author section (common in books)
        about = None
        # look for typical headings
        headings = soup.find_all(['h2','h3'])
        for h in headings:
            if 'about the author' in h.get_text().lower():
                parent = h.find_parent()
                about = parent.get_text(separator=' ', strip=True)
                break
        # fallback: find a section that contains 'About the Author' text
        if not about:
            candidate = soup.find(text=re.compile(r'About the Author', re.I))
            if candidate:
                parent = candidate.find_parent()
                if parent:
                    about = parent.get_text(separator=' ', strip=True)
        if about:
            # strip the heading itself
            about = re.sub(r'(?i)about the author\s*', '', about).strip()
            return about
        return None

    def _get_product_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        details: Dict[str, str] = {}

        # 1) detailBullets_feature_div pattern (books)
        detail_div = soup.find('div', id='detailBullets_feature_div') or soup.find('div', id='detailBulletsWrapper_feature_div')
        if detail_div:
            # list items under detail bullet list
            list_nodes = detail_div.select('ul.detail-bullet-list li') or detail_div.select('ul.a-unordered-list li')
            if list_nodes:
                for li in list_nodes:
                    # bold key may be in span.a-text-bold or similar
                    key_elem = li.find(['span', 'b', 'strong'], class_=re.compile(r'(a-text-bold)?', re.I))
                    # Some items are "Key: Value" in text only
                    if key_elem and key_elem.get_text(strip=True):
                        key = _clean_key(key_elem.get_text())
                        # remove the key text from li to get value
                        # get full li text then remove the key text occurrence
                        full = li.get_text(separator=' ', strip=True)
                        val = full.replace(key_elem.get_text(strip=True), '').strip(': ').strip()
                        if not val:
                            # sometimes the value is in next span
                            spans = li.find_all('span')
                            if len(spans) >= 2:
                                val = spans[-1].get_text(strip=True)
                        if key:
                            details[key] = val
                    else:
                        # try to split on first colon
                        txt = li.get_text(separator=' ', strip=True)
                        if ':' in txt:
                            k, v = txt.split(':', 1)
                            k = _clean_key(k)
                            details[k] = v.strip()
            # return early if found
            if details:
                return details

        # 2) productDetails_... tables (older layout)
        prod_table = soup.find('table', id='productDetails_techSpec_section_1') or soup.find('table', id='productDetails_detailBullets_sections1')
        if prod_table:
            for row in prod_table.find_all('tr'):
                th = row.find('th') or row.find('td', class_='label')
                td = row.find('td', class_='value') or row.find('td')
                if th and td:
                    k = _clean_key(th.get_text(strip=True))
                    v = td.get_text(separator=' ', strip=True)
                    if k:
                        details[k] = v
            if details:
                return details

        # 3) fallback: product details in <div id="prodDetails">
        prod_div = soup.find('div', id='prodDetails')
        if prod_div:
            for li in prod_div.find_all('li'):
                text = li.get_text(separator=' ', strip=True)
                if ':' in text:
                    k, v = text.split(':', 1)
                    details[_clean_key(k)] = v.strip()

        return details

    def _get_technical_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        tech = {}
        # same approach as before but focused on techSpec tables
        tech_tables = soup.find_all('table', class_='a-keyvalue prodDetTable') + \
                      [soup.find('table', id='productDetails_techSpec_section_1'),
                       soup.find('table', id='productDetails_techSpec_section_2')]
        for table in [t for t in tech_tables if t]:
            for row in table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if th and td:
                    tech[_clean_key(th.get_text(strip=True))] = td.get_text(separator=' ', strip=True)
        return tech

    def _get_availability(self, soup: BeautifulSoup) -> Optional[str]:
        avail = soup.find('div', id='availability') or soup.find('span', id='availability')
        if avail:
            return avail.get_text(separator=' ', strip=True)
        # sometimes availability shows in "out-of-stock" banners
        alt = soup.find(text=re.compile(r'(Currently unavailable|In Stock|Out of Stock|Temporarily unavailable)', re.I))
        if alt:
            parent = alt.find_parent()
            if parent:
                return parent.get_text(separator=' ', strip=True)
            return alt.strip()
        return None

    def _get_shipping_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        shipping = {}
        shipping_block = soup.find('div', id='mir-layout-DELIVERY_BLOCK') or soup.find(text=re.compile(r'Delivery', re.I))
        if shipping_block:
            if hasattr(shipping_block, 'get_text'):
                shipping['raw'] = shipping_block.get_text(separator=' ', strip=True)
            else:
                # if it's a text node
                shipping['raw'] = str(shipping_block).strip()
        return shipping
    
    def _get_additional_info_tables(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extract information from Amazon's a-bordered tables containing:
        - Accessibility features, Box contents, Generation, Privacy features
        - Language, Country of origin, Importer/Manufacturer details
        - MRP, Warranty, Physical specs (size, weight, audio, connectivity)
        """
        additional_info = {}
        
        # Find all tables with class 'a-bordered'
        tables = soup.find_all('table', class_='a-bordered')
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                
                if len(cells) >= 2:
                    # First cell is the key
                    key = _clean_key(cells[0].get_text(strip=True))
                    
                    # Second cell contains value and possibly links
                    value_cell = cells[1]
                    value_text = value_cell.get_text(separator=' ', strip=True)
                    
                    # Extract any links in the value cell
                    links = []
                    for link in value_cell.find_all('a', href=True):
                        href = link.get('href')
                        # Convert relative URLs to absolute
                        if href.startswith('http'):
                            full_url = href
                        else:
                            full_url = 'https://www.amazon.in' + href
                        
                        links.append({
                            'text': link.get_text(strip=True),
                            'url': full_url
                        })
                    
                    # Store the information
                    if key:
                        additional_info[key] = {
                            'text': value_text,
                            'links': links if links else None
                        }
        
        return additional_info


    def save_to_json(self, data: Dict[str, Any], filename: str = 'product_data_electric.json'):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[INFO] Data saved to {filename}")
        except Exception as e:
            print(f"[ERROR] Could not save to JSON: {e}")


# ---------------------
# Example usage
# ---------------------
def main():
    url = "https://www.amazon.in/All-new-Echo/dp/B085FY9NK8/ref=sr_1_2_sspa?nsdOptOutParam=true&sr=8-2-spons&aref=FMPhPN4sem&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY"
    scraper = AmazonScraper()
    product = scraper.scrape_product(url)
    if product:
        print("[OK] Scraped product:")
        print(json.dumps(product, indent=2, ensure_ascii=False))
        scraper.save_to_json(product, 'amazon_product.json')
    else:
        print("[FAIL] Failed to scrape product")

if __name__ == "__main__":
    main()
