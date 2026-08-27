#!/usr/bin/env python3
# amazon_hybrid_scraper.py
"""
Hybrid Amazon Scraper: Combines the robustness of the generalized scraper
with the smart data parsing of the food-specific logic.
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
    # Remove invisible control characters
    text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text)
    # Normalize whitespace
    text = re.sub(r'[\s\xa0]+', ' ', text)
    return text.strip()

# --- Main Scraper Class ---

class AmazonScraper:
    def __init__(self, headers: Dict[str, str] = None, timeout: int = 15):
        self.headers = headers or DEFAULT_HEADERS
        self.timeout = timeout
        # All HTTP fetching is delegated to the shared, hardened fetcher.
        self.fetcher = get_fetcher()

    def extract_asin(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        if url:
            m = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{9,13})', url)
            if m: return m.group(1).strip()
        if soup:
            tag = soup.find('input', {'id': 'ASIN'})
            if tag and tag.get('value'): return tag['value'].strip()
        return None

    def _get_title(self, soup: BeautifulSoup) -> Optional[str]:
        t = soup.find('span', id='productTitle')
        return _clean_text(t.get_text()) if t else None

    def _get_price_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Detects currency symbol from the raw text *before* converting to float
        to avoid the 'USD' default error on international items.
        """
        price = None
        currency = "USD" # Default fallback
        
        symbol_map = {
            '₹': 'INR', 'Rs.': 'INR', 
            '£': 'GBP', '€': 'EUR', 
            '¥': 'JPY', '$': 'USD'
        }

        # Helper to extract float
        def get_float(txt):
            clean = re.sub(r'[^\d\.,]', '', txt).replace(',', '')
            try: return float(clean)
            except: return None

        # 1. Look for the main price block
        price_tags = soup.select('span.a-price')
        for tag in price_tags:
            # Check for offscreen text (usually contains symbol + amount)
            off = tag.find('span', class_='a-offscreen')
            if off:
                raw_txt = off.get_text(strip=True)
                # Detect symbol
                for sym, code in symbol_map.items():
                    if sym in raw_txt:
                        currency = code
                        break
                
                # Parse amount
                p = get_float(raw_txt)
                if p:
                    price = p
                    break # Found it
            
            # If offscreen missing, try parts
            if not price:
                whole = tag.find('span', class_='a-price-whole')
                frac = tag.find('span', class_='a-price-fraction')
                if whole:
                    w = whole.get_text().strip().replace(',', '').replace('.', '')
                    f = frac.get_text().strip() if frac else "00"
                    try: 
                        price = float(f"{w}.{f}")
                        # Look for symbol sibling
                        sym = tag.find('span', class_='a-price-symbol')
                        if sym:
                            s_txt = sym.get_text(strip=True)
                            currency = symbol_map.get(s_txt, currency)
                        break
                    except: pass

        return {"price": price, "currency": currency}

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
    
    def get_important_information(self,soup) -> Dict[str, str]:
        """Extract important information like ingredients, directions, etc."""
        info = {}
        try:
            important_info_div = soup.find('div', {'id': 'important-information'})
            print(important_info_div)
            if important_info_div:
                for div in important_info_div.find_all('div', class_='content'):
                    h4 = div.find('h4')
                    if h4:
                        key = h4.get_text().strip().rstrip(':')
                        h4.extract()
                        value = div.get_text().strip()
                        if value:
                            info[key] = value
        except Exception as e:
            print(f"Error extracting important information: {e}")

        return info

    def _get_description(self, soup: BeautifulSoup) -> Optional[str]:
        # 1. Standard Description
        desc_div = soup.find('div', id='productDescription')
        if desc_div: 
            return _clean_text(desc_div.get_text())
        
        # 2. Meta Description (Fallback)
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta:
            return _clean_text(meta.get('content'))
            
        return None

    def _get_feature_bullets(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        bullets = []
        # Broader selector to catch variations
        feature_div = soup.find('div', id='feature-bullets') or \
                      soup.find('div', id='featurebullets_feature_div')

        if feature_div:
            for li in feature_div.find_all('li'):
                # Exclude hidden items
                if 'aok-hidden' in li.get('class', []): continue
                
                text = _clean_text(li.get_text())
                if not text: continue
                
                # Smart Parse: Label vs Value
                if ':' in text:
                    parts = text.split(':', 1)
                    label = parts[0].strip()
                    value = parts[1].strip()
                    # Heuristic: Labels are usually short phrases
                    if len(label) < 60:
                        bullets.append({"label": label, "value": value})
                    else:
                        bullets.append({"value": text})
                else:
                    bullets.append({"value": text})
        return bullets

    def _get_specifications(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Handles BOTH technical tables and food-style specification tables.
        """
        specs = {}
        tables = soup.find_all('table')
        
        for table in tables:
            # Skip layout tables or image maps
            if 'aplus' in str(table.get('class', [])): continue

            for row in table.find_all('tr'):
                cells = row.find_all(['th', 'td'])
                
                # We strictly look for rows with exactly 2 meaningful cells
                if len(cells) == 2:
                    key = _clean_text(cells[0].get_text()).rstrip(':')
                    val = _clean_text(cells[1].get_text())
                    
                    if key and val:
                        specs[key] = val
        return specs
    
    def _clean_key(k: str) -> str:
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

    def _get_product_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        metadata = {}
        details_div = soup.find('div', id='detailBullets_feature_div') or \
                      soup.find('div', id='detailBulletsWrapper_feature_div')
        
        if details_div:
            for li in details_div.select('li'):
                key_span = li.find('span', class_='a-text-bold')
                if key_span:
                    raw_key = _clean_text(key_span.get_text()).rstrip(':')
                    
                    # Skip Reviews in metadata
                    if "Customer Reviews" in raw_key: continue

                    full_text = _clean_text(li.get_text())
                    val = full_text.replace(raw_key, '', 1).strip().lstrip(':').strip()
                    
                    # Clean Rank
                    if "Best Sellers Rank" in raw_key:
                        val = re.sub(r'\(.*?\)', '', val).strip() # remove (See Top 100...)
                        val = re.sub(r'\s+', ' ', val)

                    if raw_key and val:
                        metadata[raw_key] = val
        return metadata

    def _get_important_information(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Safe extraction of Ingredients/Directions. 
        Will return empty dict if section doesn't exist (graceful fail).
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
        
    # def _get_price_per_unit(self, soup):
    #     """
    #     Extracts price-per-unit like: (₹31.55 /100 g)
    #     Returns: {"value": float, "unit": "100 g", "currency": "INR"} or None
    #     """
    #     try:
    #         # Pattern examples: "₹31.55 /100 g", "₹210 /kg", "(₹55 / 50 ml)"
    #         pattern = re.compile(r'([₹$£€¥]\s*\d+[\.\d]*)\s*/\s*([\d]+\s*\w+)', re.I)

    #         # Search inside all spans
    #         spans = soup.find_all("span")
    #         for sp in spans:
    #             text = sp.get_text(" ", strip=True)
    #             m = pattern.search(text)
    #             if m:
    #                 price_text = m.group(1)
    #                 unit_text = m.group(2)

    #                 # Detect currency
    #                 symbol_map = {
    #                     '₹': 'INR', 'Rs.': 'INR',
    #                     '$': 'USD', '£': 'GBP',
    #                     '€': 'EUR', '¥': 'JPY'
    #                 }
    #                 currency = None
    #                 for sym, code in symbol_map.items():
    #                     if sym in price_text:
    #                         currency = code
    #                         break

    #                 # Clean price numeric
    #                 price_num = re.sub(r'[^\d\.]', '', price_text)
    #                 try:
    #                     price_value = float(price_num)
    #                     return {
    #                         "value": price_value,
    #                         "unit": unit_text.strip(),
    #                         "currency": currency or "UNKNOWN"
    #                     }
    #                 except:
    #                     pass

    #         return None

    #     except Exception as e:
    #         print("Error parsing price per unit:", e)
    #         return None
        
    def _get_use_by_date(self, soup):
            """
            Extracts 'Use by' date from product page.
            Returns: string date like "30 APR 2026" or None
            """
            try:
                # Strategy 1: Look in offersConsistencyEnabled for sibling spans
                offers_div = soup.find("div", class_="offersConsistencyEnabled")
                if offers_div:
                    spans = offers_div.find_all("span")
                    for i, span in enumerate(spans):
                        text = span.get_text(strip=True)
                        if text == "Use by:":
                            # The next sibling span should contain the date
                            if i + 1 < len(spans):
                                date_text = spans[i + 1].get_text(strip=True)
                                if date_text:
                                    return date_text
                
                # Strategy 2: Look for the ppd_newAccordionRow div
                accordion_divs = [
                    soup.find("div", id="ppd_newAccordionRow"),
                    soup.find("div", id="ppd_snsAccordionRowMiddle")
                ]
                
                for accordion_div in accordion_divs:
                    if accordion_div:
                        spans = accordion_div.find_all("span")
                        for i, span in enumerate(spans):
                            text = span.get_text(strip=True)
                            if text == "Use by:":
                                # The next sibling span should contain the date
                                if i + 1 < len(spans):
                                    date_text = spans[i + 1].get_text(strip=True)
                                    if date_text:
                                        return date_text
                
                # Strategy 3: Regex fallback for any container with "Use by:"
                all_divs = soup.find_all("div")
                for div in all_divs:
                    text = div.get_text(" ", strip=True)
                    if "Use by:" in text:
                        match = re.search(r'Use by:\s*([0-9]{1,2}\s+[A-Z]{3}\s+[0-9]{4})', text, re.I)
                        if match:
                            return match.group(1).strip()
                
                return None
                
            except Exception as e:
                print(f"Error extracting use by date: {e}")
                return None

    def _get_price_per_unit(self, soup):
        """
        Extracts price-per-unit like: (₹31.55 /100 g)
        Returns: {"value": float, "unit": "100 g", "currency": "INR"} or None
        """
        try:
            symbol_map = {
                '₹': 'INR', 'Rs.': 'INR',
                '$': 'USD', '£': 'GBP',
                '€': 'EUR', '¥': 'JPY'
            }

            # Strategy 1: Look for the specific structure with a-price inside a-size-mini span
            mini_spans = soup.find_all("span", class_="a-size-mini")
            for mini_span in mini_spans:
                text = mini_span.get_text(" ", strip=True)
                
                # Check if it contains price-per-unit pattern: (₹XX.XX /YYY unit)
                if '/' in text and any(sym in text for sym in symbol_map.keys()):
                    # Try to find a-price span inside
                    price_span = mini_span.find("span", class_="a-price")
                    if price_span:
                        # Get the offscreen price (clean version)
                        offscreen = price_span.find("span", class_="a-offscreen")
                        if offscreen:
                            price_text = offscreen.get_text(strip=True)
                            
                            # Detect currency from price text
                            currency = None
                            for sym, code in symbol_map.items():
                                if sym in price_text:
                                    currency = code
                                    break
                            
                            # Extract numeric value
                            price_num = re.sub(r'[^\d\.]', '', price_text)
                            try:
                                price_value = float(price_num)
                                
                                # Extract unit from the full text (after the /)
                                unit_match = re.search(r'/\s*([\d]+\s*[a-zA-Z]+)', text)
                                if unit_match:
                                    unit_text = unit_match.group(1).strip()
                                    return {
                                        "value": price_value,
                                        "unit": unit_text,
                                        "currency": currency or "UNKNOWN"
                                    }
                            except:
                                pass

            # Strategy 2: Fallback to regex pattern matching
            pattern = re.compile(r'([₹$£€¥]\s*\d+[\.\d]*)\s*/\s*([\d]+\s*\w+)', re.I)
            spans = soup.find_all("span")
            for sp in spans:
                text = sp.get_text(" ", strip=True)
                m = pattern.search(text)
                if m:
                    price_text = m.group(1)
                    unit_text = m.group(2)

                    # Detect currency
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

    def _get_price_per_unit(self, soup):
        """
        Extracts price-per-unit like: (₹31.55 /100 g)
        Returns: {"value": float, "unit": "100 g", "currency": "INR"} or None
        """
        try:
            symbol_map = {
                '₹': 'INR', 'Rs.': 'INR',
                '$': 'USD', '£': 'GBP',
                '€': 'EUR', '¥': 'JPY'
            }

            # Strategy 1: Look for the specific structure with a-price inside a-size-mini span
            mini_spans = soup.find_all("span", class_="a-size-mini")
            for mini_span in mini_spans:
                text = mini_span.get_text(" ", strip=True)
                
                # Check if it contains price-per-unit pattern: (₹XX.XX /YYY unit)
                if '/' in text and any(sym in text for sym in symbol_map.keys()):
                    # Try to find a-price span inside
                    price_span = mini_span.find("span", class_="a-price")
                    if price_span:
                        # Get the offscreen price (clean version)
                        offscreen = price_span.find("span", class_="a-offscreen")
                        if offscreen:
                            price_text = offscreen.get_text(strip=True)
                            
                            # Detect currency from price text
                            currency = None
                            for sym, code in symbol_map.items():
                                if sym in price_text:
                                    currency = code
                                    break
                            
                            # Extract numeric value
                            price_num = re.sub(r'[^\d\.]', '', price_text)
                            try:
                                price_value = float(price_num)
                                
                                # Extract unit from the full text (after the /)
                                unit_match = re.search(r'/\s*([\d]+\s*[a-zA-Z]+)', text)
                                if unit_match:
                                    unit_text = unit_match.group(1).strip()
                                    return {
                                        "value": price_value,
                                        "unit": unit_text,
                                        "currency": currency or "UNKNOWN"
                                    }
                            except:
                                pass

            # Strategy 2: Fallback to regex pattern matching
            pattern = re.compile(r'([₹$£€¥]\s*\d+[\.\d]*)\s*/\s*([\d]+\s*\w+)', re.I)
            spans = soup.find_all("span")
            for sp in spans:
                text = sp.get_text(" ", strip=True)
                m = pattern.search(text)
                if m:
                    price_text = m.group(1)
                    unit_text = m.group(2)

                    # Detect currency
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
        print(f"[INFO] Scraping: {url}")
        try:
            html = self.fetcher.fetch(url)
            if not html:
                print(f"[ERROR] Could not retrieve page (blocked or unreachable): {url}")
                return None
            soup = BeautifulSoup(html, 'html.parser')

            price_data = self._get_price_data(soup)

            product = {
                "url": url,
                "asin": self.extract_asin(url, soup),
                "title": self._get_title(soup),
                "price": price_data['price'],
                "currency": price_data['currency'],
                "description": self._get_description(soup),
                "feature_bullets": self._get_feature_bullets(soup),
                "specifications": self._get_specifications(soup),
                "product_metadata": self._get_product_metadata(soup),
                "important_information": self._get_important_information(soup),
                "images": self.get_product_images(soup),
                "important_info": self.get_important_information(soup),
                "additional_info_tables": self._get_additional_info_tables(soup),
                "price_per_unit": self._get_price_per_unit(soup),
                "use_by_date": self._get_use_by_date(soup)
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
            print(f"[ERROR] {e}")
            return None

    def save_to_json(self, data: Any, filename: str):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Saved to {filename}")

# --- Execution ---

if __name__ == "__main__":
    scraper = AmazonScraper()
    
    # Your URL from the prompt
    url = "https://www.amazon.in/Unibic-Cookies-Premium-Biscuits-Cranberries/dp/B0D3HXCP7X/ref=sr_1_2_sspa?s=grocery&sr=1-2-spons&aref=opMG6FlVbU&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY"
    
    data = scraper.scrape_product(url)
    
    if data:
        print("\n--- Scraped Data ---")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        scraper.save_to_json(data, "amazon_food_product.json")