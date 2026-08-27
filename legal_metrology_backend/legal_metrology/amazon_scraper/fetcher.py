#!/usr/bin/env python3
"""
Shared, hardened HTTP fetcher for Amazon product pages.

Every category scraper (amazon, book, food, skincare, electric, search) downloads
pages through this single module, so all anti-bot handling lives in ONE place
instead of being copy-pasted (and going stale) across six files.

Why this exists
---------------
The old scrapers used a bare ``requests.get`` with a single, hard-coded, 4-year-old
User-Agent (``Chrome/91``) and advertised ``br`` (brotli) encoding without the brotli
package installed.  Amazon flags that fingerprint instantly and replies with a
"Robot Check" / CAPTCHA / 503 page, and the brotli mismatch could return garbled
bytes.  Either way the parser found nothing and the API returned
``500 Failed to scrape product``.

Strategy (in order)
-------------------
1. ``requests.Session`` that looks like a real, modern browser:
     * a pool of current User-Agents, rotated per attempt,
     * a full, consistent header set (incl. Client Hints for Chromium UAs),
     * ``Accept-Encoding`` that only advertises what we can actually decode,
     * cookie *priming* (visit the domain home page once to pick up session cookies),
     * retry with exponential backoff + jitter on 429/5xx,
     * detection of Amazon bot-wall / CAPTCHA pages -> rotate identity and retry.
2. If requests is still blocked AND a browser driver is available, fall back to a
   headless Selenium / undetected-chromedriver render of the page.

Selenium is entirely optional: if it is not installed the module simply skips the
fallback and returns ``None`` (callers already treat ``None`` as "could not scrape").

Configuration via environment variables
----------------------------------------
    SCRAPER_PROXY            e.g. "http://user:pass@host:port" (used for http+https)
    SCRAPER_MAX_ATTEMPTS     integer, default 4
    SCRAPER_TIMEOUT          seconds, default 25
    SCRAPER_BROWSER_FALLBACK "1"/"0", default "1" (enable Selenium fallback)
    SCRAPER_MIN_DELAY        min polite delay between requests (seconds, default 0.5)
    SCRAPER_MAX_DELAY        max polite delay between requests (seconds, default 1.5)
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 v1 and v2 expose Retry from different paths
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    from urllib3.util import Retry  # type: ignore


# --------------------------------------------------------------------------- #
# Capability detection
# --------------------------------------------------------------------------- #

def _brotli_available() -> bool:
    """requests can only *decode* brotli if 'brotli' (or 'brotlicffi') is present.
    Advertising 'br' without it yields undecodable bytes, so we probe first."""
    for mod in ("brotli", "brotlicffi"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


_ACCEPT_ENCODING = "gzip, deflate, br" if _brotli_available() else "gzip, deflate"


# --------------------------------------------------------------------------- #
# Browser fingerprints
# --------------------------------------------------------------------------- #

# A small pool of realistic, current desktop User-Agents. Each entry carries the
# platform so the Client-Hint headers we emit stay internally consistent.
_USER_AGENTS = [
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "platform": '"Windows"', "brand": "chrome",
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "platform": '"macOS"', "brand": "chrome",
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "platform": '"Windows"', "brand": "edge",
    },
    {
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "platform": '"Linux"', "brand": "chrome",
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
              "Gecko/20100101 Firefox/125.0",
        "platform": None, "brand": "firefox",
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) "
              "Gecko/20100101 Firefox/125.0",
        "platform": None, "brand": "firefox",
    },
]


def _build_headers(agent: dict, referer: Optional[str] = None) -> dict:
    """Assemble a coherent header set for a given fingerprint."""
    ua = agent["ua"]
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": _ACCEPT_ENCODING,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }
    if referer:
        headers["Referer"] = referer

    # Client Hints only make sense for Chromium-family browsers.
    if agent["brand"] in ("chrome", "edge"):
        m = re.search(r"Chrome/(\d+)", ua)
        ver = m.group(1) if m else "124"
        if agent["brand"] == "edge":
            brands = (f'"Chromium";v="{ver}", "Not(A:Brand";v="24", '
                      f'"Microsoft Edge";v="{ver}"')
        else:
            brands = (f'"Chromium";v="{ver}", "Not(A:Brand";v="24", '
                      f'"Google Chrome";v="{ver}"')
        headers["sec-ch-ua"] = brands
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = agent["platform"] or '"Windows"'
    return headers


# --------------------------------------------------------------------------- #
# Bot-wall detection
# --------------------------------------------------------------------------- #

_BLOCK_MARKERS = (
    "enter the characters you see below",
    "type the characters you see in this image",
    "sorry, we just need to make sure you're not a robot",
    "sorry! something went wrong on our end",
    "/errors/validatecaptcha",
    "api-services-support@amazon.com",
    "to discuss automated access to amazon data",
    "robot check",
    "captcha",
)


def looks_blocked(html: Optional[str]) -> bool:
    """Return True if `html` looks like an Amazon bot-wall / CAPTCHA / empty page."""
    if not html or len(html) < 500:
        return True
    low = html.lower()
    if any(marker in low for marker in _BLOCK_MARKERS):
        # 'captcha' can rarely appear on legit pages, so require that a real
        # product title is NOT present alongside it.
        if "id=\"producttitle\"" in low or "id='producttitle'" in low:
            return False
        return True
    # amazon.in "Continue shopping" interstitial: tiny page, no product body.
    if len(html) < 12000 and "continue shopping" in low and "producttitle" not in low:
        return True
    return False


# --------------------------------------------------------------------------- #
# Selenium fallback (optional, lazily imported)
# --------------------------------------------------------------------------- #

def fetch_with_browser(url: str, timeout: int = 30) -> Optional[str]:
    """Render `url` with a headless browser. Returns page HTML or None.

    Tries undetected-chromedriver first (best at evading detection), then plain
    Selenium 4 (which auto-manages the driver via Selenium Manager). If neither is
    installed, logs once and returns None so the caller degrades gracefully.
    """
    agent = random.choice(_USER_AGENTS)
    driver = None
    try:
        # 1) undetected-chromedriver
        try:
            import undetected_chromedriver as uc  # type: ignore

            options = uc.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument(f"--user-agent={agent['ua']}")
            driver = uc.Chrome(options=options)
        except Exception:
            # 2) plain Selenium 4
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument(f"--user-agent={agent['ua']}")
            driver = webdriver.Chrome(options=options)
            try:
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": "Object.defineProperty(navigator,'webdriver',"
                               "{get: () => undefined})"},
                )
            except Exception:
                pass

        driver.set_page_load_timeout(timeout)
        print(f"[fetcher] Browser fallback fetching: {url}")
        driver.get(url)
        time.sleep(random.uniform(2.5, 4.5))
        html = driver.page_source
        return html
    except Exception as exc:  # ImportError, WebDriverException, timeouts, ...
        print(f"[fetcher] Browser fallback unavailable/failed: {exc}")
        return None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Main fetcher
# --------------------------------------------------------------------------- #

class AmazonFetcher:
    """Downloads Amazon pages while doing its best to look like a real browser."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_attempts: Optional[int] = None,
        use_browser_fallback: Optional[bool] = None,
        proxy: Optional[str] = None,
    ):
        self.timeout = int(timeout or os.getenv("SCRAPER_TIMEOUT", 25))
        self.max_attempts = int(max_attempts or os.getenv("SCRAPER_MAX_ATTEMPTS", 4))
        if use_browser_fallback is None:
            use_browser_fallback = os.getenv("SCRAPER_BROWSER_FALLBACK", "1") != "0"
        self.use_browser_fallback = use_browser_fallback

        proxy = proxy or os.getenv("SCRAPER_PROXY")
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

        self.min_delay = float(os.getenv("SCRAPER_MIN_DELAY", 0.5))
        self.max_delay = float(os.getenv("SCRAPER_MAX_DELAY", 1.5))

        self.session = self._build_session()
        self._primed_hosts: set = set()
        self._lock = threading.Lock()

        # Diagnostics for callers that want a reason on failure.
        self.last_status: Optional[int] = None
        self.last_reason: Optional[str] = None

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        # Transport-level retries for transient network/5xx errors. The
        # higher-level loop in fetch() handles bot-walls (which return 200/503
        # with CAPTCHA HTML that retrying the same identity won't fix).
        retries = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _prime(self, url: str) -> None:
        """Visit the domain home page once to collect session cookies, like a
        real user who lands on amazon.in before opening a product."""
        host = urlparse(url).netloc
        if not host or host in self._primed_hosts:
            return
        with self._lock:
            if host in self._primed_hosts:
                return
            self._primed_hosts.add(host)  # mark first so we never loop on failure
            try:
                scheme = urlparse(url).scheme or "https"
                home = f"{scheme}://{host}/"
                agent = random.choice(_USER_AGENTS)
                self.session.get(
                    home,
                    headers=_build_headers(agent),
                    timeout=self.timeout,
                    proxies=self.proxies,
                )
            except requests.RequestException as exc:
                print(f"[fetcher] Cookie priming failed for {host}: {exc}")

    def fetch(self, url: str) -> Optional[str]:
        """Return decoded HTML for `url`, or None if it could not be fetched
        without hitting a bot wall / after exhausting all strategies."""
        if not url:
            return None

        self.last_status = None
        self.last_reason = None
        self._prime(url)

        host = urlparse(url).netloc
        referer = f"https://{host}/" if host else None

        for attempt in range(1, self.max_attempts + 1):
            agent = random.choice(_USER_AGENTS)
            headers = _build_headers(agent, referer=referer)
            try:
                resp = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    proxies=self.proxies,
                )
            except requests.RequestException as exc:
                self.last_reason = f"request error: {exc}"
                print(f"[fetcher] Attempt {attempt}/{self.max_attempts} "
                      f"network error: {exc}")
                self._sleep_backoff(attempt)
                continue

            self.last_status = resp.status_code
            # Let requests pick the encoding; fall back to utf-8 for Amazon.
            if not resp.encoding:
                resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text

            if resp.status_code == 200 and not looks_blocked(html):
                return html

            if resp.status_code == 200:
                self.last_reason = "bot-wall / CAPTCHA page"
                print(f"[fetcher] Attempt {attempt}/{self.max_attempts} blocked "
                      f"(bot-wall detected). Rotating identity...")
            else:
                self.last_reason = f"HTTP {resp.status_code}"
                print(f"[fetcher] Attempt {attempt}/{self.max_attempts} got "
                      f"HTTP {resp.status_code}. Rotating identity...")

            # A fresh identity often needs fresh cookies too.
            self.session.cookies.clear()
            self._primed_hosts.discard(host)
            self._prime(url)
            self._sleep_backoff(attempt)

        # requests exhausted -> optional headless browser fallback.
        if self.use_browser_fallback:
            print("[fetcher] requests strategy exhausted; trying browser fallback.")
            html = fetch_with_browser(url, timeout=max(self.timeout, 30))
            if html and not looks_blocked(html):
                self.last_reason = None
                return html
            self.last_reason = (self.last_reason or "") + " + browser fallback failed"

        print(f"[fetcher] Could not fetch {url} ({self.last_reason}).")
        return None

    def _sleep_backoff(self, attempt: int) -> None:
        # Exponential backoff with jitter, plus a small polite base delay.
        base = random.uniform(self.min_delay, self.max_delay)
        backoff = base + (2 ** (attempt - 1)) * random.uniform(0.4, 0.9)
        time.sleep(min(backoff, 12.0))


# --------------------------------------------------------------------------- #
# Module-level shared instance
# --------------------------------------------------------------------------- #

_shared_fetcher: Optional[AmazonFetcher] = None
_shared_lock = threading.Lock()


def get_fetcher() -> AmazonFetcher:
    """Return a process-wide shared fetcher (reuses cookies across scrapes)."""
    global _shared_fetcher
    if _shared_fetcher is None:
        with _shared_lock:
            if _shared_fetcher is None:
                _shared_fetcher = AmazonFetcher()
    return _shared_fetcher


def fetch(url: str) -> Optional[str]:
    """Convenience wrapper around the shared fetcher."""
    return get_fetcher().fetch(url)


if __name__ == "__main__":
    import sys

    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.amazon.in/Leriya-Fashion-Men-Ord-Set/dp/B0F6K68VL4/"
    )
    print(f"Fetching: {test_url}")
    page = fetch(test_url)
    if page:
        print(f"OK - received {len(page)} chars of HTML")
    else:
        print("FAILED - page could not be retrieved (see log above)")
