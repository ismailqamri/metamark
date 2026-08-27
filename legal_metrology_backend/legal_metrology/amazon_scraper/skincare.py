#!/usr/bin/env python3
# generalized_amazon_scraper.py

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

def _clean_text(text: str) -> str:
    """
    Aggressively cleans text: removes invisible unicode chars, 
    non-breaking spaces, and excessive whitespace.
    """
    if not text:
        return ""
    # Remove invisible control characters (Left-to-Right marks, etc commonly found on Amazon)
    text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text)
    # Normalize whitespace (newlines, tabs, non-breaking spaces become single space)
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
        """Extracts ASIN from URL or Page."""
        # 1. URL Regex
        if url:
            m = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{9,13})', url)
            if m: return m.group(1).strip()

        if soup:
            # 2. Hidden Input
            tag = soup.find('input', {'id': 'ASIN'})
            if tag and tag.get('value'): return tag['value'].strip()
            # 3. Data Attribute
            alt = soup.find(attrs={'data-asin': True})
            if alt and alt.get('data-asin'): return alt['data-asin'].strip()
        return None

    def _get_title(self, soup: BeautifulSoup) -> Optional[str]:
        t = soup.find('span', id='productTitle')
        return _clean_text(t.get_text()) if t else None

    def _get_price_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extracts price and currency."""
        price = None
        currency = "USD" # Default assumption, updated if symbol found

        # Helper to parse "$12.34" -> 12.34 and "$" -> "USD"
        def parse_val(txt):
            clean = re.sub(r'[^\d\.,]', '', txt).strip()
            # Heuristic: remove commas, keep last dot
            clean = clean.replace(',', '')
            try: return float(clean)
            except: return None
        
        def detect_currency(txt):
            if '£' in txt: return 'GBP'
            if '€' in txt: return 'EUR'
            if '¥' in txt: return 'JPY'
            if '₹' in txt: return 'INR'
            return 'USD'

        # 1. Check a-offscreen (standard)
        off = soup.find('span', class_='a-offscreen')
        if off:
            txt = off.get_text()
            p = parse_val(txt)
            if p:
                price = p
                currency = detect_currency(txt)

        # 2. Fallback to generic search if #1 failed
        if not price:
            whole = soup.find('span', class_='a-price-whole')
            frac = soup.find('span', class_='a-price-fraction')
            if whole:
                w = whole.get_text().replace('.', '').replace(',', '').strip()
                f = frac.get_text().strip() if frac else "00"
                try: price = float(f"{w}.{f}")
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
        """Extracts the main paragraph description."""
        # Standard description div
        desc_div = soup.find('div', id='productDescription')
        if desc_div:
            return _clean_text(desc_div.get_text())
        
        # Meta description as fallback
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta:
            return _clean_text(meta.get('content'))
        return None

    def _get_feature_bullets(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """
        Extracts 'About this item' bullets. 
        Detects 'Label: Value' format automatically.
        """
        bullets = []
        feature_div = soup.find('div', id='feature-bullets')
        if feature_div:
            for li in feature_div.find_all('li'):
                text = _clean_text(li.get_text())
                if not text: continue
                
                # Check for "Label: Value" pattern
                # We assume a label is reasonably short (< 50 chars) to avoid splitting long sentences
                if ':' in text:
                    parts = text.split(':', 1)
                    label = parts[0].strip()
                    value = parts[1].strip()
                    if len(label) < 50:
                        bullets.append({"label": label, "value": value})
                    else:
                        bullets.append({"value": text})
                else:
                    bullets.append({"value": text})
        return bullets

    def _get_specifications(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Generalized Table Parser.
        Looks for 'Technical Details', 'Quality Details', or any key-value table.
        """
        specs = {}
        
        # 1. Scan all tables in the main content area
        # We look for generic classes (like in your skincare example) and specific tech spec classes
        tables = soup.find_all('table')
        
        for table in tables:
            # Optimization: Skip tables that are clearly not specs (like image grids)
            if 'aplus' in str(table.get('class', [])): continue

            rows = table.find_all('tr')
            for row in rows:
                # Look for typical Key -> Value cell structures
                cells = row.find_all(['th', 'td'])
                
                # Strict 2-column layout usually indicates a spec
                if len(cells) == 2:
                    key = _clean_text(cells[0].get_text()).rstrip(':')
                    val = _clean_text(cells[1].get_text())
                    if key and val:
                        specs[key] = val
                        
        return specs

    def _get_product_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extracts data from the 'Product Details' section (Dimensions, ASIN, Rank).
        """
        metadata = {}
        details_div = soup.find('div', id='detailBullets_feature_div') or \
                      soup.find('div', id='detailBulletsWrapper_feature_div')
        
        if details_div:
            for li in details_div.select('li'):
                # Amazon puts keys in bold spans usually
                key_span = li.find('span', class_='a-text-bold')
                if key_span:
                    raw_key = _clean_text(key_span.get_text()).rstrip(':')
                    # Remove invisible chars
                    key = raw_key.replace('\u200e', '').replace('\u200f', '')
                    
                    # Value is the full text minus the key
                    full_text = _clean_text(li.get_text())
                    # remove the key text from the full text
                    val = full_text.replace(raw_key, '').strip().lstrip(':').strip()
                    
                    if key and val:
                        metadata[key] = val
                        
        return metadata
    
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
        """Aggregates all data points into a clean JSON structure."""
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
                # Generalized Data Buckets
                "feature_bullets": self._get_feature_bullets(soup), # "About this item"
                "specifications": self._get_specifications(soup),   # Tables (Quality/Tech details)
                "product_metadata": self._get_product_metadata(soup), # "Product Details" list
                "images": self.get_product_images(soup),
                "important_info": self.get_important_information(soup),
                "additional_info_tables": self._get_additional_info_tables(soup),
                "price_per_unit": self._get_price_per_unit(soup)
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
    
    # Test 1: Skincare (Your requested URL)
    url_skincare = "https://www.amazon.com/Minimalist-Vitamin-Glowing-Highly-Effective/dp/B08MVBF4P8/ref=pd_rhf_dp_s_ci_mcx_mr_hp_d_d_sccl_2_2/142-5061352-6721358?psc=1"
    data = scraper.scrape_product(url_skincare)
    
    if data:
        print("\n--- Scraped Data (Chatbot Friendly) ---")
        print(json.dumps(data, indent=2))
        scraper.save_to_json(data, "amazon_product_skincare.json")