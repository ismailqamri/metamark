import re
import json
import time
import random
from urllib.parse import parse_qs, urlparse, unquote

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("BeautifulSoup4 not installed. Install it with: pip install beautifulsoup4")
    exit(1)

# Prefer the shared hardened fetcher (UA rotation, cookie priming, retries,
# bot-wall detection, headless-browser fallback). Falls back to the local
# helpers below if the module can't be imported (e.g. run in isolation).
try:
    from amazon_scraper.fetcher import fetch as _shared_fetch
except ImportError:
    try:
        from fetcher import fetch as _shared_fetch
    except ImportError:
        _shared_fetch = None

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

def extract_product_url(click_url, base_domain="amazon.in"):
    """Extract the actual Amazon product URL from the click tracking URL or direct link"""
    try:
        # If it's already a direct product link
        if '/dp/' in click_url and '/sspa/click' not in click_url:
            # Clean up the URL to get just the product path
            match = re.search(r'(/[^/]+/dp/[A-Z0-9]+)', click_url)
            if match:
                product_path = match.group(1)
                return f"https://www.{base_domain}{product_path}"
        
        # If it's a click tracking URL
        if '/sspa/click' in click_url:
            # Parse the URL parameters
            parsed = urlparse(click_url)
            params = parse_qs(parsed.query)
            
            # Get the 'url' parameter which contains the actual product URL
            if 'url' in params:
                product_path = unquote(params['url'][0])
                
                # Extract the product path (e.g., /Product-Name/dp/B01LY6B085/...)
                # Find the dp/ASIN pattern
                match = re.search(r'(/[^/]+/dp/[A-Z0-9]+)', product_path)
                if match:
                    product_path = match.group(1)
                    # Clean up the path to just get to the dp/ASIN
                    product_path = re.sub(r'/ref=.*$', '', product_path)
                    return f"https://www.{base_domain}{product_path}"
        
        return None
    except Exception as e:
        print(f"Error extracting URL: {e}")
        return None

def extract_links_with_bs4(html_content, base_domain="amazon.in"):
    """Extract product links using BeautifulSoup4"""
    soup = BeautifulSoup(html_content, 'html.parser')
    results = []
    seen_urls = set()
    
    # Find all product containers
    # Amazon uses various selectors, try multiple approaches
    
    # Method 1: Find all h2 tags with product titles
    product_headings = soup.find_all('h2', class_=lambda x: x and 'a-size-mini' in x or 'a-size-base-plus' in x)
    
    for heading in product_headings:
        # Find the anchor tag within or near the heading
        link = heading.find('a')
        if not link:
            # Check parent
            link = heading.find_parent('a')
        
        if link and link.get('href'):
            href = link.get('href')
            
            # Get title text
            title = heading.get_text(strip=True)
            if not title:
                # Try to get from aria-label
                title = heading.get('aria-label', '')
            
            # Extract product URL
            if title and href:
                product_url = extract_product_url(href, base_domain)
                
                if product_url and product_url not in seen_urls:
                    results.append({
                        'title': title,
                        'url': product_url
                    })
                    seen_urls.add(product_url)
    
    # Method 2: If above didn't work, try finding all links with /dp/ or /sspa/click
    if len(results) < 3:
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link.get('href', '')
            
            if '/dp/' in href or '/sspa/click' in href:
                # Try to find associated title
                title = ""
                
                # Check for h2 in the link
                h2 = link.find('h2')
                if h2:
                    title = h2.get_text(strip=True)
                    if not title:
                        title = h2.get('aria-label', '')
                
                # Check for span with product title
                if not title:
                    span = link.find('span', class_=lambda x: x and 'a-text-normal' in x)
                    if span:
                        title = span.get_text(strip=True)
                
                if title and href:
                    product_url = extract_product_url(href, base_domain)
                    
                    if product_url and product_url not in seen_urls:
                        results.append({
                            'title': title,
                            'url': product_url
                        })
                        seen_urls.add(product_url)
    
    return results

def fetch_with_selenium(url):
    """Fetch Amazon page using Selenium (more reliable but slower)"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        print("Using Selenium (this may take a moment)...")
        
        # Setup Chrome options
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Initialize driver
        driver = webdriver.Chrome(options=chrome_options)
        
        # Navigate to URL
        driver.get(url)
        
        # Wait for page to load
        time.sleep(random.uniform(2, 4))
        
        # Get page source
        html_content = driver.page_source
        
        # Close driver
        driver.quit()
        
        return html_content
        
    except ImportError:
        print("\nSelenium not installed. Install it with:")
        print("pip install selenium")
        print("\nYou'll also need Chrome/Chromium and ChromeDriver installed.")
        return None
    except Exception as e:
        print(f"Selenium error: {e}")
        return None

def fetch_with_requests(url):
    """Try to fetch with requests library (faster but may be blocked)"""
    try:
        import requests
        
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()
        return response.text
        
    except ImportError:
        print("Requests library not installed. Install it with: pip install requests")
        return None
    except Exception as e:
        print(f"Requests error: {e}")
        return None

def fetch_amazon_page(url, use_selenium=False):
    """Fetch Amazon search page HTML.

    By default this delegates to the shared hardened fetcher (rotating UA,
    cookie priming, retries with backoff, bot-wall detection and a headless
    browser fallback). Setting ``use_selenium=True`` forces the Selenium path
    directly. If the shared fetcher module is unavailable, we fall back to the
    legacy requests-then-Selenium behaviour.
    """
    if use_selenium:
        return fetch_with_selenium(url)

    # Preferred path: shared hardened fetcher.
    if _shared_fetch is not None:
        html = _shared_fetch(url)
        if html and len(html) > 1000:
            return html
        print("\nShared fetcher was blocked or returned too little; trying Selenium...")
        return fetch_with_selenium(url)

    # Legacy fallback if the shared fetcher couldn't be imported.
    print("Trying with requests library...")
    html = fetch_with_requests(url)
    if html and len(html) > 1000:  # Basic check that we got content
        return html
    print("\nRequests failed or was blocked. Trying Selenium...")
    return fetch_with_selenium(url)

def extract_top_links_from_url(search_url, num_links=3, use_selenium=False):
    """Extract top N product links from Amazon search URL"""
    # Fetch the page
    print(f"Fetching: {search_url}")
    html_content = fetch_amazon_page(search_url, use_selenium)
    
    if not html_content:
        return []
    
    # Determine the domain (amazon.com, amazon.in, etc.)
    parsed_url = urlparse(search_url)
    base_domain = parsed_url.netloc.replace('www.', '')
    
    # Parse with BeautifulSoup
    print("Parsing HTML with BeautifulSoup...")
    results = extract_links_with_bs4(html_content, base_domain)
    
    # Return only the requested number of links
    return results[:num_links]

def extract_from_file(filepath, num_links=3):
    """Extract links from a saved HTML file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        print(f"Reading from file: {filepath}")
        
        # Try to determine domain from the HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        base_domain = "amazon.in"  # default
        
        # Try to find domain from meta tags or links
        canonical = soup.find('link', {'rel': 'canonical'})
        if canonical and canonical.get('href'):
            parsed = urlparse(canonical.get('href'))
            base_domain = parsed.netloc.replace('www.', '')
        
        results = extract_links_with_bs4(html_content, base_domain)
        return results[:num_links]
        
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

# Main execution
if __name__ == "__main__":
    print("="*60)
    print("Amazon Product Link Extractor (using BeautifulSoup4)")
    print("="*60)
    
    # Ask for input method
    print("\nChoose input method:")
    print("1. URL (fetch from web)")
    print("2. HTML file (saved page)")
    choice = input("Enter choice (1/2): ").strip()
    
    results = []
    
    if choice == '2':
        filepath = input("\nEnter path to HTML file: ").strip()
        results = extract_from_file(filepath, num_links=3)
    else:
        # Get search URL
        search_url = input("\nEnter Amazon search URL: ").strip()
        
        if not search_url:
            print("Please provide a valid Amazon search URL")
            exit(1)
        
        # Ask if user wants to force Selenium
        use_sel = input("\nForce use Selenium? (y/n, default: n): ").strip().lower()
        use_selenium = use_sel == 'y'
        
        # Extract top 3 links
        results = extract_top_links_from_url(search_url, num_links=3, use_selenium=use_selenium)
    
    if results:
        # Print as JSON
        print("\n" + "="*60)
        print("RESULTS:")
        print("="*60)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
        # Save to file
        with open('amazon_links.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ Found {len(results)} products")
        print("✓ Results saved to amazon_links.json")
    else:
        print("\n✗ No results found. Possible reasons:")
        print("  - Amazon is blocking requests")
        print("  - Page structure has changed")
        print("  - Try saving the page as HTML and using option 2")
        print("\nRequired packages:")
        print("  pip install beautifulsoup4 requests")
        print("  pip install selenium  # (optional, for better reliability)")