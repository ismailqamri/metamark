#!/usr/bin/env python3
"""
Ultimate Amazon Product Scraper
Combines the best extraction techniques from multiple specialized scrapers
to work across all product categories: books, electronics, food, skincare, etc.
"""

import os
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
import google.generativeai as genai

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

def _clean_text(text: str) -> str:
    """Aggressively cleans text of invisible chars and extra whitespace."""
    if not text:
        return ""
    # Remove invisible control characters (LTR/RTL marks, etc.)
    text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text)
    # Normalize whitespace (tabs, newlines, non-breaking spaces)
    text = re.sub(r'[\s\xa0]+', ' ', text)
    return text.strip()

def _clean_key(k: str) -> str:
    """Normalize keys found in product details."""
    if not k:
        return k
    k = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', k)
    k = re.sub(r'\s+', ' ', k)
    return k.strip().rstrip(':')

# --- Main Scraper Class ---

class AmazonScraper:
    def __init__(self, headers: Dict[str, str] = None, timeout: int = 15):
        self.headers = headers or DEFAULT_HEADERS
        self.timeout = timeout
        # All HTTP fetching is delegated to the shared, hardened fetcher.
        self.fetcher = get_fetcher()

    # ==================== ASIN EXTRACTION ====================
    
    def extract_asin(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        """Extract ASIN/ISBN from URL, hidden fields, or detail bullets."""
        if url:
            # From URL: /dp/ASIN or /gp/product/ASIN
            m = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{9,13})', url)
            if m:
                return m.group(1).strip()

        if soup:
            # From hidden input: input#ASIN
            tag = soup.find('input', {'id': 'ASIN'})
            if tag and tag.get('value'):
                return tag['value'].strip()
            
            # From data-asin attribute
            alt = soup.find(attrs={'data-asin': True})
            if alt and alt.get('data-asin'):
                return alt['data-asin'].strip()
            
            # From detail bullets (books: ISBN-10/13)
            db = soup.find('div', id=re.compile(r'detailBullets.*feature_div', re.I))
            if db:
                text = db.get_text(separator=' | ', strip=True)
                # Try ISBN-10/13
                for pattern in [r'ISBN-10[:\s]*([0-9Xx\-]+)', r'ISBN-13[:\s]*([0-9\-]+)']:
                    m = re.search(pattern, text)
                    if m:
                        return m.group(1).replace('-', '').strip()
            
            # From ld+json schema markup
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, dict):
                        sku = data.get('sku') or data.get('productID')
                        if sku:
                            return str(sku).strip()
                except Exception:
                    continue
        return None

    # ==================== TITLE EXTRACTION ====================
    
    def _get_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract product title from multiple locations."""
        # Standard productTitle span
        t = soup.find('span', id='productTitle')
        if t:
            return _clean_text(t.get_text())
        
        # Open Graph meta tag
        og = soup.find('meta', property='og:title')
        if og and og.get('content'):
            return _clean_text(og['content'])
        
        # Fallback: page title
        if soup.title:
            return _clean_text(soup.title.get_text())
        
        return None

    # ==================== PRICE & CURRENCY EXTRACTION ====================
    
    def _get_price_and_currency(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Ultra-robust price and currency extractor.
        Detects currency BEFORE converting to float to avoid defaults.
        """
        price = None
        currency = None
        
        # Currency symbol mapping
        symbol_map = {
            '$': 'USD', '£': 'GBP', '€': 'EUR',
            '¥': 'JPY', '₹': 'INR', 'Rs.': 'INR',
            'INR': 'INR'
        }
        
        def parse_float(txt: str) -> Optional[float]:
            """Extract float from price string."""
            if not txt:
                return None
            # Remove everything except digits, dots, commas
            clean = re.sub(r'[^\d\.,]', '', txt).strip()
            # Remove commas (thousand separators)
            clean = clean.replace(',', '')
            # Handle double dots
            clean = re.sub(r'\.{2,}', '.', clean)
            try:
                return float(clean)
            except:
                return None
        
        def detect_currency(txt: str) -> Optional[str]:
            """Detect currency symbol in text."""
            if not txt:
                return None
            for sym, code in symbol_map.items():
                if sym in txt:
                    return code
            return None
        
        # 1. NEW BOOK LAYOUT: symbol + whole + fraction
        symbol = soup.find("span", class_="a-price-symbol")
        whole = soup.find("span", class_="a-price-whole")
        frac = soup.find("span", class_="a-price-fraction")
        
        if whole and frac:
            try:
                w = whole.get_text().replace(',', '').replace('.', '').strip()
                f = frac.get_text().strip()
                price = float(f"{w}.{f}")
                if symbol:
                    currency = detect_currency(symbol.get_text())
            except:
                pass
        
        # 2. ANY a-price block with offscreen value (MOST RELIABLE)
        if price is None:
            for tag in soup.find_all("span", class_="a-price"):
                off = tag.find("span", class_="a-offscreen")
                if off:
                    raw_text = off.get_text(strip=True)
                    # Detect currency first
                    if currency is None:
                        currency = detect_currency(raw_text)
                    # Parse price
                    p = parse_float(raw_text)
                    if p is not None:
                        price = p
                        break
        
        # 3. OLD priceblock IDs
        if price is None:
            for pid in ["priceblock_ourprice", "priceblock_dealprice", "priceblock_saleprice"]:
                el = soup.find("span", id=pid)
                if el:
                    txt = el.get_text(strip=True)
                    if currency is None:
                        currency = detect_currency(txt)
                    p = parse_float(txt)
                    if p is not None:
                        price = p
                        break
        
        # 4. LD+JSON offers section
        if price is None:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, dict):
                        offers = data.get("offers")
                        if isinstance(offers, dict):
                            p = offers.get("price")
                            if p:
                                price = parse_float(str(p))
                            c = offers.get("priceCurrency")
                            if c:
                                currency = c.upper()
                            if price:
                                break
                except:
                    pass
        
        # 5. Full text fallback regex
        if price is None:
            text = soup.get_text(" ")
            m = re.search(r'([$£€¥₹]\s?[0-9][0-9,]*\.?\d*)', text)
            if m:
                raw = m.group(1)
                if currency is None:
                    currency = detect_currency(raw)
                price = parse_float(raw)
        
        # Default currency if not detected
        if currency is None and price is not None:
            currency = "USD"
        
        return {"price": price, "currency": currency}

    # ==================== COUNTRY & LANGUAGE ====================
    
    def _get_country_from_url(self, url: str) -> Optional[str]:
        """Infers Amazon domain's country code."""
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

    # ==================== IMAGE EXTRACTION ====================
    
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

    # ==================== RATING & REVIEWS ====================
    
    def _get_rating(self, soup: BeautifulSoup) -> Optional[float]:
        """Extracts average star rating."""
        # Standard icon text
        rating_elem = soup.find('span', class_='a-icon-alt') or \
                      soup.find('i', class_='a-icon-star')
        if rating_elem:
            m = re.search(r'(\d+(\.\d+)?)', rating_elem.get_text())
            if m:
                try:
                    return float(m.group(1))
                except:
                    pass
        
        # ld+json
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
                            except:
                                pass
            except:
                pass
        return None
    
    def _get_reviews_count(self, soup: BeautifulSoup) -> Optional[int]:
        """Extracts total number of reviews/ratings."""
        # Standard review count
        rev = soup.find('span', id='acrCustomerReviewText')
        if rev:
            m = re.search(r'([\d,]+)', rev.get_text())
            if m:
                return int(m.group(1).replace(',', ''))
        
        # Detail bullets variant
        db = soup.find('div', id=re.compile(r'detailBullets.*feature_div', re.I))
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
                            except:
                                pass
            except:
                pass
        return None

    # ==================== DESCRIPTION & FEATURES ====================
    
    def _get_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extracts main product description text."""
        # 1. Common productDescription ID
        desc = soup.find('div', id='productDescription')
        if desc:
            for s in desc(['script', 'style']):
                s.extract()
            text = _clean_text(desc.get_text(separator=' '))
            if text:
                return text
        
        # 2. Expanded description container (books)
        exp = soup.find('div', attrs={'data-expanded': True})
        if exp:
            txt = _clean_text(exp.get_text(separator=' '))
            if txt:
                return txt
        
        # 3. Meta description
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta and meta.get('content'):
            return _clean_text(meta['content'])
        
        # 4. Feature bullets as fallback
        bullets = soup.find('div', id='feature-bullets')
        if bullets:
            items = [_clean_text(span.get_text()) 
                    for span in bullets.select('span.a-list-item') 
                    if _clean_text(span.get_text())]
            if items:
                return ' '.join(items)
        
        # 5. ld+json
        for s in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(s.string or "{}")
                if isinstance(data, dict):
                    d = data.get('description')
                    if d:
                        return _clean_text(str(d))
            except:
                pass
        
        return None
    
    def _get_feature_bullets(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """
        Extracts 'About this item' bullets.
        Smart parsing: detects 'Label: Value' format.
        """
        bullets = []
        feature_div = soup.find('div', id='feature-bullets') or \
                      soup.find('div', id='featurebullets_feature_div')
        
        if feature_div:
            for li in feature_div.find_all('li'):
                # Skip hidden items
                if 'aok-hidden' in li.get('class', []):
                    continue
                
                text = _clean_text(li.get_text())
                if not text:
                    continue
                
                # Smart parse: Label vs Value
                if ':' in text:
                    parts = text.split(':', 1)
                    label = parts[0].strip()
                    value = parts[1].strip()
                    # Labels are usually short phrases (< 60 chars)
                    if len(label) < 60:
                        bullets.append({"label": label, "value": value})
                    else:
                        bullets.append({"value": text})
                else:
                    bullets.append({"value": text})
        
        return bullets
    
    def _get_about_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extracts 'About the Author' section (books)."""
        headings = soup.find_all(['h2', 'h3'])
        for h in headings:
            if 'about the author' in h.get_text().lower():
                parent = h.find_parent()
                about = _clean_text(parent.get_text(separator=' '))
                # Strip the heading itself
                about = re.sub(r'(?i)about the author\s*', '', about).strip()
                return about if about else None
        return None

    # ==================== PRODUCT DETAILS & SPECS ====================
    
    def _get_product_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Combines extraction from detail bullets and product tables.
        Works for books, electronics, food, skincare, etc.
        """
        details: Dict[str, str] = {}
        
        # 1. detailBullets_feature_div pattern (books/small items)
        detail_div = soup.find('div', id=re.compile(r'detailBullets.*feature_div', re.I))
        if detail_div:
            list_nodes = detail_div.select('ul.detail-bullet-list li') or \
                        detail_div.select('ul.a-unordered-list li')
            for li in list_nodes:
                key_elem = li.find(['span', 'b', 'strong'], 
                                  class_=re.compile(r'(a-text-bold)?', re.I))
                
                if key_elem:
                    key = _clean_key(key_elem.get_text())
                    full = _clean_text(li.get_text(separator=' '))
                    val = full.replace(key_elem.get_text(strip=True), '').strip(': ').strip()
                    
                    if not val:
                        spans = li.find_all('span')
                        if len(spans) >= 2:
                            val = _clean_text(spans[-1].get_text())
                    
                    # Skip Customer Reviews in metadata
                    if key and val and "Customer Reviews" not in key:
                        # Clean Best Sellers Rank
                        if "Best Sellers Rank" in key:
                            val = re.sub(r'\(.*?\)', '', val).strip()
                        details[key] = val
                else:
                    txt = _clean_text(li.get_text(separator=' '))
                    if ':' in txt:
                        k, v = txt.split(':', 1)
                        k = _clean_key(k)
                        if k and v.strip():
                            details[k] = v.strip()
        
        # 2. productDetails tables
        prod_table = soup.find('table', id=re.compile(
            r'productDetails_techSpec_section_1|productDetails_detailBullets_sections1', re.I))
        if prod_table:
            for row in prod_table.find_all('tr'):
                th = row.find('th') or row.find('td', class_='label')
                td = row.find('td', class_='value') or row.find('td')
                if th and td:
                    k = _clean_key(th.get_text())
                    v = _clean_text(td.get_text(separator=' '))
                    if k and v:
                        details[k] = v
        
        return details
    
    def _get_specifications(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Generalized table parser for technical specs.
        Works for electronics, skincare quality details, food nutrition, etc.
        """
        specs = {}
        
        # Find all tables
        tables = soup.find_all('table')
        
        for table in tables:
            # Skip A+ content tables (marketing images)
            if 'aplus' in str(table.get('class', [])):
                continue
            
            # Look for technical detail tables
            if table.get('id') and re.search(r'techSpec|prodDet', table.get('id', ''), re.I):
                is_spec_table = True
            elif 'prodDetTable' in str(table.get('class', [])):
                is_spec_table = True
            else:
                is_spec_table = False
            
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['th', 'td'])
                
                # 2-column layout = key-value pair
                if len(cells) == 2:
                    key = _clean_key(cells[0].get_text())
                    val = _clean_text(cells[1].get_text())
                    if key and val:
                        specs[key] = val
        
        return specs
    
    def _get_important_information(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extracts Ingredients/Directions (food products).
        Returns empty dict if section doesn't exist.
        """
        info = {}
        imp_div = soup.find('div', id='importantInformation')
        
        if imp_div:
            for heading in imp_div.find_all(['h4', 'h5']):
                key = _clean_text(heading.get_text()).rstrip(':')
                sibling = heading.find_next_sibling()
                if sibling:
                    val = _clean_text(sibling.get_text())
                    if key and val:
                        info[key] = val
        
        return info
    
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

    # ==================== AVAILABILITY & SHIPPING ====================
    
    def _get_availability(self, soup: BeautifulSoup) -> Optional[str]:
        """Extracts availability status."""
        avail = soup.find('div', id='availability') or \
                soup.find('span', id='availability')
        if avail:
            return _clean_text(avail.get_text(separator=' '))
        
        # Fallback: search for common phrases
        alt = soup.find(text=re.compile(
            r'(Currently unavailable|In Stock|Out of Stock|Temporarily unavailable|Only \d+ left in stock)', 
            re.I))
        if alt:
            parent = alt.find_parent()
            if parent:
                return _clean_text(parent.get_text(separator=' '))
            return alt.strip()
        
        return None
    
    def _get_shipping_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extracts shipping and delivery text."""
        shipping = {}
        shipping_block = soup.find('div', id='mir-layout-DELIVERY_BLOCK') or \
                        soup.find(text=re.compile(r'Delivery|shipping', re.I))
        
        if shipping_block:
            if hasattr(shipping_block, 'get_text'):
                container = shipping_block.find_parent('div', 
                    class_=re.compile(r'a-spacing-base|a-row')) or shipping_block
                shipping['raw'] = _clean_text(container.get_text(separator=' '))
            else:
                shipping['raw'] = str(shipping_block).strip()
        
        return shipping
    
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



    # ==================== MAIN SCRAPER METHOD ====================
    
    def scrape_product(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Main scraping method — keeps all original fields and appends:
          product['seller'] = {seller_name, seller_url} or None
          product['seller_analysis'] = dict from Gemini or None
        """
        print(f"[INFO] Scraping: {url}")
        try:
            html = self.fetcher.fetch(url)
            if not html:
                print(f"[ERROR] Could not retrieve page (blocked or unreachable): {url}")
                return None
            soup = BeautifulSoup(html, 'html.parser')

            # --- existing extraction (price_data, etc) ---
            price_data = self._get_price_and_currency(soup)  # original method exists in file
            product = {
                'url': url,
                'asin': self.extract_asin(url, soup),
                'title': self._get_title(soup),
                'price': price_data.get('price'),
                'currency': price_data.get('currency'),
                'country': self._get_country_from_url(url),
                'language': self._get_language(soup),
                'images': self.get_product_images(soup),
                'rating': self._get_rating(soup),
                'reviews_count': self._get_reviews_count(soup),
                'description': self._get_description(soup),
                'feature_bullets': self._get_feature_bullets(soup),
                'product_details': self._get_product_details(soup),
                'specifications': self._get_specifications(soup),
                'important_information': self._get_important_information(soup),
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
            print(f"[ERROR] Parsing error: {e}")
            return None
    
    def save_to_json(self, data: Dict[str, Any], filename: str = 'product_data.json'):
        """Saves scraped data to JSON file."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[INFO] Data saved to {filename}")
        except Exception as e:
            print(f"[ERROR] Could not save to JSON: {e}")


# ==================== EXAMPLE USAGE ====================

def main():
    scraper = AmazonScraper()
    
    # Test URLs from different categories
    test_urls = {
        'book': "https://www.amazon.com/Harry-Potter-Books-MinaLima-Editions/dp/1546130195/",
        'electronics': "https://www.amazon.com/CyberPowerPC-i9-14900KF-GeForce-Windows-GXiVR8080A39/dp/B0DW48QHFY/",
        'skincare': "https://www.amazon.com/Vitamin-Serum-Niacinamide-Super-Bright/dp/B0FBXB6JR6/",
        'food': "https://www.amazon.com/Pintola-Classic-Peanut-Butter-Creamy/dp/B07G5829G9/"
    }
    
    # Test with book
    product = scraper.scrape_product(test_urls['book'])
    
    if product:
        print("\n" + "="*60)
        print("SCRAPED PRODUCT DATA")
        print("="*60)

if __name__ == "__main__":
    # url = input("Enter Amazon product URL: ").strip()
    test_urls = {
        # 'book': "https://www.amazon.com/Harry-Potter-Books-MinaLima-Editions/dp/1546130195/",
        'amazon': "https://www.amazon.in/Leriya-Fashion-Men-Ord-Set/dp/B0F6K68VL4/ref=sr_1_6?sr=8-6&psc=1",
        # 'skincare': "https://www.amazon.com/Vitamin-Serum-Niacinamide-Super-Bright/dp/B0FBXB6JR6/",
        # 'food': "https://www.amazon.com/Pintola-Classic-Peanut-Butter-Creamy/dp/B07G5829G9/"
    }

    scraper = AmazonScraper()
    for category, url in test_urls.items():
        print(category, url)
        data = scraper.scrape_product(url)

        print("\n\n=== OUTPUT ===")
        print(json.dumps(data, indent=4, ensure_ascii=False))