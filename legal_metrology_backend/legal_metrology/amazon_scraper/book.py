#!/usr/bin/env python3
# generalized_amazon_scraper.py
"""
Generalized Amazon product scraper designed to work across various product page layouts.
It is robust against different HTML structures (e.g., books vs. electronics) 
by checking multiple possible locations for core data fields.
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

# --- Configuration ---

DEFAULT_HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

# --- Helper Functions ---

def _clean_key(k: str) -> str:
    """Normalize keys found in product details (strip weird whitespace/controls)."""
    if not k:
        return k
    # remove invisible separators and non-printable characters
    k = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', k)
    k = re.sub(r'\s+', ' ', k)  # normalize whitespace
    return k.strip().rstrip(':')

def _safe_get_text(node) -> str:
    """Safely get text from a BeautifulSoup node."""
    if not node:
        return ''
    return node.get_text(separator=' ', strip=True)

# --- Main Scraper Class ---

class AmazonScraper:
    def __init__(self, headers: Dict[str, str] = None, timeout: int = 15):
        self.headers = headers or DEFAULT_HEADERS
        self.timeout = timeout
        # All HTTP fetching is delegated to the shared, hardened fetcher.
        self.fetcher = get_fetcher()

    def extract_asin(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        """Extract ASIN/ISBN from URL, hidden fields, or detail bullets."""
        if url:
            # 1. From URL: /dp/ASIN or /product/ASIN
            m = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{9,13})', url)
            if m:
                return m.group(1).strip()

        if soup:
            # 2. From hidden input: input#ASIN
            tag = soup.find('input', {'id': 'ASIN'})
            if tag and tag.get('value'):
                return tag['value'].strip()
            
            # 3. From data-asin attribute
            alt = soup.find(attrs={'data-asin': True})
            if alt:
                val = alt.get('data-asin')
                if val:
                    return val.strip()
            
            # 4. From detail bullets (often for ISBNs)
            db = soup.find('div', id=re.compile(r'detailBullets.*feature_div', re.I))
            if db:
                text = db.get_text(separator=' | ', strip=True)
                # try ISBN-10/13
                m = re.search(r'ISBN-10[:\s]*([0-9Xx\-]+)', text)
                if m:
                    return m.group(1).replace('-', '').strip()
                m = re.search(r'ISBN-13[:\s]*([0-9\-]+)', text)
                if m:
                    return m.group(1).replace('-', '').strip()
            
            # 5. From ld+json schema markup
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, dict):
                        # Look for common fields like sku or productID
                        sku = data.get('sku') or data.get('productID')
                        if sku:
                            return str(sku).strip()
                except Exception:
                    continue
        return None

    def _get_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract product title from multiple locations."""
        t = soup.find('span', id='productTitle')
        if t:
            return t.get_text(strip=True)
        og = soup.find('meta', property='og:title')
        if og and og.get('content'):
            return og['content'].strip()
        if soup.title:
            # Last resort: Page title
            return soup.title.get_text(strip=True)
        return None

    def _parse_price_text(self, txt: str) -> Optional[float]:
        """Internal function to normalize price text into a float."""
        if not txt:
            return None
        # Remove common non-numeric chars but keep the decimal dot
        txt = re.sub(r'[^\d\.,]', '', txt).strip()
        
        # Simple regex to capture potential price numbers (handle comma thousands, dot decimal)
        m = re.search(r'[\d\.,]+', txt.replace('\xa0', ' '))
        if not m:
            return None
        num = m.group(0)
        
        # Heuristic: If there are two dots/commas, assume the last one is the decimal point. 
        # For simplicity and typical Amazon format (e.g., $1,234.56), we mostly assume 
        # dots are decimals and commas are thousands separator, but remove commas for float conversion.
        num_clean = num.replace(',', '')
        
        try:
            return float(num_clean)
        except ValueError:
            return None

    def _get_price(self, soup):
        """Ultra-robust Amazon price extractor."""

        def parse_float(num):
            if not num:
                return None
            try:
                return float(num.replace(",", "").strip())
            except:
                return None

        # ----------------------------------
        # 1️⃣ New Amazon Book Layout (MOST COMMON NOW)
        # ----------------------------------
        symbol = soup.find("span", class_="a-price-symbol")
        whole  = soup.find("span", class_="a-price-whole")
        frac   = soup.find("span", class_="a-price-fraction")

        if symbol and whole and frac:
            price_str = f"{whole.get_text().replace(',', '')}.{frac.get_text()}"
            return parse_float(price_str)

        # ----------------------------------
        # 2️⃣ Try ANY visible a-price block
        # ----------------------------------
        for price_tag in soup.find_all("span", class_="a-price"):
            off = price_tag.find("span", class_="a-offscreen")
            if off and off.get_text(strip=True):
                num = re.search(r"[\d,]+\.\d+", off.get_text())
                if num:
                    return parse_float(num.group(0))

        # ----------------------------------
        # 3️⃣ old priceblock IDs
        # ----------------------------------
        ids = ["priceblock_ourprice", "priceblock_dealprice", "priceblock_saleprice"]
        for pid in ids:
            el = soup.find("span", id=pid)
            if el:
                txt = el.get_text(strip=True)
                num = re.search(r"[\d,]+\.\d+", txt)
                if num:
                    return parse_float(num.group(0))

        # ----------------------------------
        # 4️⃣ LD+JSON offers section
        # ----------------------------------
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    offers = data.get("offers")
                    if isinstance(offers, dict):
                        price = offers.get("price")
                        if price:
                            return parse_float(str(price))
            except:
                pass

        # ----------------------------------
        # 5️⃣ Full text fallback regex
        # ----------------------------------
        text = soup.get_text(" ")
        m = re.search(r"([£€¥₹$]\s?[0-9][0-9,]*\.\d+)", text)
        if m:
            value = re.search(r"[\d,]+\.\d+", m.group(1))
            if value:
                return parse_float(value.group(0))

        return None
    
    def extract_price(self, soup):
        """
        Extracts Amazon price from all known modern layouts.
        """

        def clean_num(x):
            if not x:
                return None
            clean = x.replace(",", "").strip()
            clean = clean.replace("..", ".")      # remove double dots
            clean = re.sub(r"\.+", ".", clean)    # collapse any repeated dots
            return float(clean)



        # ---------------------------
        # 1️⃣ NEW BOOK LAYOUT (works for your example)
        # ---------------------------
        symbol = soup.find("span", class_="a-price-symbol")
        whole = soup.find("span", class_="a-price-whole")
        frac  = soup.find("span", class_="a-price-fraction")

        if whole and frac:
            price = f"{whole.get_text().replace(',', '')}.{frac.get_text()}"
            return clean_num(price)

        # ---------------------------
        # 2️⃣ ANY a-price block with offscreen value
        # ---------------------------
        for tag in soup.find_all("span", class_="a-price"):
            off = tag.find("span", class_="a-offscreen")
            if off:
                text = off.get_text(strip=True)
                m = re.search(r"([\d,]+\.\d+)", text)
                if m:
                    return clean_num(m.group(1))

        # ---------------------------
        # 3️⃣ OLD priceblock ID layout
        # ---------------------------
        for pid in ["priceblock_ourprice", "priceblock_dealprice", "priceblock_saleprice"]:
            el = soup.find(id=pid)
            if el:
                text = el.get_text(strip=True)
                m = re.search(r"([\d,]+\.\d+)", text)
                if m:
                    return clean_num(m.group(1))

        return None



    def _get_currency(self, soup):
        symbol_map = {
            "$": "USD", "£": "GBP", "€": "EUR",
            "¥": "JPY", "₹": "INR", "INR": "INR"
        }

        # 1️⃣ New book layout
        sym = soup.find("span", class_="a-price-symbol")
        if sym:
            s = sym.get_text(strip=True)
            return symbol_map.get(s, s)

        # 2️⃣ any offscreen price
        off = soup.find("span", class_="a-offscreen")
        if off:
            txt = off.get_text(strip=True)
            m = re.search(r"([£€¥₹$])", txt)
            if m:
                return symbol_map.get(m.group(1), m.group(1))

        # 3️⃣ priceblock IDs
        ids = ["priceblock_ourprice", "priceblock_dealprice", "priceblock_saleprice"]
        for pid in ids:
            el = soup.find("span", id=pid)
            if el:
                txt = el.get_text(strip=True)
                m = re.search(r"([£€¥₹$])", txt)
                if m:
                    return symbol_map.get(m.group(1), m.group(1))

        return None


    def _get_country_from_url(self, url: str) -> Optional[str]:
        """Infers Amazon domain's country code (e.g., .com -> US)."""
        if not url:
            return None
        try:
            hostname = urlparse(url).hostname or ''
            domain_map = {
                '.com': 'US', '.co.uk': 'UK', '.de': 'DE', '.fr': 'FR',
                '.co.jp': 'JP', '.jp': 'JP', '.in': 'IN', '.ca': 'CA',
                '.com.au': 'AU', '.com.mx': 'MX', '.it': 'IT', '.es': 'ES',
                '.com.br': 'BR', '.com.tr': 'TR'
            }
            for suffix, country in domain_map.items():
                if hostname.endswith(suffix):
                    return country
        except Exception:
            pass
        return None

    def _get_language(self, soup: BeautifulSoup) -> Optional[str]:
        """Extracts page language from HTML or meta tags."""
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
        """Extracts average star rating."""
        # 1. Standard text/icon
        rating_elem = soup.find('span', class_='a-icon-alt') or soup.find('i', class_='a-icon-star')
        if rating_elem and rating_elem.get_text():
            m = re.search(r'(\d+(\.\d+)?)', rating_elem.get_text())
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass
        # 2. ld+json
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
                continue
        return None

    def _get_reviews_count(self, soup: BeautifulSoup) -> Optional[int]:
        """Extracts total number of reviews/ratings."""
        # 1. Standard review count text
        rev = soup.find('span', id='acrCustomerReviewText')
        if rev and rev.get_text():
            txt = rev.get_text().strip()
            m = re.search(r'([\d,]+)', txt)
            if m:
                return int(m.group(1).replace(',', ''))
        
        # 2. Detail bullets variant (for books/less standard items)
        db = soup.find('div', id=re.compile(r'detailBullets.*feature_div', re.I))
        if db:
            m = re.search(r'(\d{1,3}(?:,\d{3})*)\s+ratings?', db.get_text(), re.I)
            if m:
                return int(m.group(1).replace(',', ''))
        
        # 3. ld+json
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
                continue
        return None

    def _get_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extracts main product description text."""
        # 1. Common productDescription ID
        desc = soup.find('div', id='productDescription')
        if desc:
            # Remove scripts and styles before extracting text
            for s in desc(['script', 'style']):
                s.extract()
            text = desc.get_text(separator=' ', strip=True)
            if text:
                return text

        # 2. Expanded description container (often used for short descriptions/books)
        exp = soup.find('div', attrs={'data-expanded': True})
        if exp:
            txt = exp.get_text(separator=' ', strip=True)
            if txt:
                return txt

        # 3. Feature bullets (if no long description exists)
        bullets = soup.find('div', id='feature-bullets')
        if bullets:
            items = [span.get_text(strip=True) for span in bullets.select('span.a-list-item') if span.get_text(strip=True)]
            if items:
                return ' '.join(items)

        # 4. ld+json
        for s in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(s.string or "{}")
                if isinstance(data, dict):
                    d = data.get('description')
                    if d:
                        return str(d).strip()
            except Exception:
                continue
        return None

    def _get_about_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Specifically targets 'About the Author' section, typically for books."""
        about = None
        # Look for typical headings near the section
        headings = soup.find_all(['h2','h3'])
        for h in headings:
            if 'about the author' in h.get_text().lower():
                parent = h.find_parent()
                about = parent.get_text(separator=' ', strip=True)
                break
        
        if about:
            # Strip the heading itself and return the content
            about = re.sub(r'(?i)about the author\s*', '', about).strip()
            return about
        return None

    def _get_product_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Combines extraction from detail bullets and product tables (non-technical specs)."""
        details: Dict[str, str] = {}

        # 1. detailBullets_feature_div pattern (usually books/small items)
        detail_div = soup.find('div', id=re.compile(r'detailBullets.*feature_div', re.I))
        if detail_div:
            list_nodes = detail_div.select('ul.detail-bullet-list li') or detail_div.select('ul.a-unordered-list li')
            for li in list_nodes:
                key_elem = li.find(['span', 'b', 'strong'], class_=re.compile(r'(a-text-bold)?', re.I))
                
                if key_elem and key_elem.get_text(strip=True):
                    # Robust way to split key and value for complex elements
                    key = _clean_key(key_elem.get_text())
                    full = li.get_text(separator=' ', strip=True)
                    # Try to strip the key text from the full text to get the value
                    val = full.replace(key_elem.get_text(strip=True), '').strip(': ').strip()
                    
                    if not val:
                        # Fallback for value in a separate span
                        spans = li.find_all('span')
                        if len(spans) >= 2:
                            val = spans[-1].get_text(strip=True)
                            
                    if key and val:
                        details[key] = val
                else:
                    # Simple text split on first colon
                    txt = li.get_text(separator=' ', strip=True)
                    if ':' in txt:
                        k, v = txt.split(':', 1)
                        k = _clean_key(k)
                        if k and v.strip():
                            details[k] = v.strip()
                            
        # 2. productDetails tables (older or alternative layouts)
        prod_table = soup.find('table', id=re.compile(r'productDetails_techSpec_section_1|productDetails_detailBullets_sections1', re.I))
        if prod_table:
            for row in prod_table.find_all('tr'):
                th = row.find('th') or row.find('td', class_='label')
                td = row.find('td', class_='value') or row.find('td')
                if th and td:
                    k = _clean_key(th.get_text(strip=True))
                    v = td.get_text(separator=' ', strip=True)
                    if k and v:
                        details[k] = v
                        
        # 3. Merge with technical details (to cover all bases)
        tech_details = self._get_technical_details(soup)
        details.update(tech_details)
        
        return details

    def _get_technical_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extracts technical specification details from tables."""
        tech = {}
        # Find tables with technical specs keys
        tech_tables = soup.find_all('table', class_='a-keyvalue prodDetTable') + \
                      soup.find_all('table', id=re.compile(r'productDetails_techSpec_section_', re.I))
                      
        for table in [t for t in tech_tables if t]:
            for row in table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if th and td:
                    # Clean the key from the header
                    k = _clean_key(th.get_text(strip=True))
                    # Get the value from the data cell
                    v = td.get_text(separator=' ', strip=True)
                    if k and v:
                        tech[k] = v
        return tech

    def _get_availability(self, soup: BeautifulSoup) -> Optional[str]:
        """Extracts availability status (In Stock, Out of Stock, etc.)."""
        avail = soup.find('div', id='availability') or soup.find('span', id='availability')
        if avail:
            return avail.get_text(separator=' ', strip=True)
        # Fallback to search for common availability phrases
        alt = soup.find(text=re.compile(r'(Currently unavailable|In Stock|Out of Stock|Temporarily unavailable|Only \d+ left in stock)', re.I))
        if alt:
            parent = alt.find_parent()
            if parent:
                return parent.get_text(separator=' ', strip=True)
            return alt.strip()
        return None

    def _get_shipping_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extracts shipping and delivery text."""
        shipping = {}
        # Find block containing delivery information
        shipping_block = soup.find('div', id='mir-layout-DELIVERY_BLOCK') or soup.find(text=re.compile(r'Delivery|shipping', re.I))
        if shipping_block:
            if hasattr(shipping_block, 'get_text'):
                # Traverse up to a containing element for full detail text
                container = shipping_block.find_parent('div', class_=re.compile(r'a-spacing-base|a-row')) or shipping_block
                shipping['raw'] = container.get_text(separator=' ', strip=True)
            else:
                # If it's a direct text node
                shipping['raw'] = str(shipping_block).strip()
        return shipping
    
    def _clean_key(self, k: str) -> str:
        """Normalize keys found in product details (strip weird whitespace/controls)."""
        if not k:
            return k
        # remove invisible separators and non-printable characters
        k = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', k)
        k = re.sub(r'\s+', ' ', k)  # normalize whitespace
        return k.strip().rstrip(':')
    
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
                    key = self._clean_key(cells[0].get_text(strip=True))
                    
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
        """Main method to fetch and parse the product page."""
        print(f"[INFO] Attempting to scrape: {url}")
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
                'price': self.extract_price(soup),
                'currency': self._get_currency(soup),
                'country': self._get_country_from_url(url),
                'language': self._get_language(soup),
                'images': self.get_product_images(soup),
                'rating': self._get_rating(soup),
                'reviews_count': self._get_reviews_count(soup),
                'description': self._get_description(soup),
                # Note: Keeping this separate for book/author info
                'about_author': self._get_about_author(soup), 
                # Scrape all details, including technical specs
                'product_details': self._get_product_details(soup), 
                # For redundancy, you can still call technical details separately 
                # if you prefer them in their own dict, but _get_product_details 
                # is set to merge them for completeness.
                'technical_details': self._get_technical_details(soup), 
                'availability': self._get_availability(soup),
                'shipping_details': self._get_shipping_details(soup),
                'additional_info_tables': self._get_additional_info_tables(soup),
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
            # print(f"[ERROR] Last URL: {url}")
            return None

    def save_to_json(self, data: Dict[str, Any], filename: str = 'product_data_book.json'):
        """Saves the scraped data to a JSON file."""
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
    # Example 1: Electronics/Gaming PC
    pc_url = "https://www.amazon.com/CyberPowerPC-i9-14900KF-GeForce-Windows-GXiVR8080A39/dp/B0DW48QHFY/"
    
    # Example 2: Book/Interactive Edition
    book_url = "https://www.amazon.in/Bell-Jar-Sylvia-Plath/dp/9357025995/ref=sr_1_1_sspa?sr=8-1-spons&aref=o9K5BWaeSc&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&psc=1"

    skincare_url = "https://www.amazon.com/Vitamin-Serum-Niacinamide-Super-Bright/dp/B0FBXB6JR6/ref=sr_1_4?sr=8-4"
    
    scraper = AmazonScraper()
    
    # # Scrape PC
    # pc_product = scraper.scrape_product(pc_url)
    # if pc_product:
    #     print("\n--- PC Scrape Result ---")
    #     print(json.dumps(pc_product, indent=2, ensure_ascii=False))
    #     scraper.save_to_json(pc_product, 'amazon_pc_product.json')
    
    # Scrape Book
    book_product = scraper.scrape_product(book_url)
    if book_product:
        print("\n--- Book Scrape Result ---")
        print(json.dumps(book_product, indent=2, ensure_ascii=False))
        scraper.save_to_json(book_product, 'amazon_book_product.json')

    # # Scrape skincare product
    # skincare_product = scraper.scrape_product(skincare_url)
    # if skincare_product:
    #     print("\n--- Book Scrape Result ---")
    #     print(json.dumps(skincare_product, indent=2, ensure_ascii=False))
    #     scraper.save_to_json(skincare_product, 'amazon_skincare_product.json')

if __name__ == "__main__":
    # Remove the `main()` call if you intend to use this code 
    # as a module (e.g., from another script by importing the class).
    # Since you asked for a complete script, the example `main` is included.
    main()