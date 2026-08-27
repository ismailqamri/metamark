# Legal Metrology Compliance Backend 🛒⚖️

A Flask-based backend that intelligently scrapes Amazon product data, categorizes
products using Google's Gemini AI, runs **Legal Metrology compliance analysis**
(OCR + rule checks) on the product, and tracks seller–customer interactions to
generate activity heatmaps. It powers both a Next.js dashboard and a Chrome
extension overlay.

> **Canonical entry point:** `server.py`. Older prototypes (`app.py`, `main.py`,
> `tempCodeRunnerFile.py`) and the unused `rag_compliance.py` module have been
> moved to [`_archive/`](./_archive) — do not run them.

---

## 📋 Features

* **AI-Powered Routing:** Google Gemini analyzes each URL and routes it to a
  category-specific scraper (Books, Electronics, Food, Skincare, or a generic
  fallback).
* **Hardened Scraping:** A single shared fetcher (`amazon_scraper/fetcher.py`)
  handles user-agent rotation, cookie priming, ret/backoff, bot-wall detection,
  and an optional headless-browser fallback so scraping keeps working when
  Amazon serves CAPTCHAs or 503s.
* **Compliance Analysis:** OCR + rule-based checks produce a compliance score,
  grade, and violation summary for each product.
* **Seller Analytics:** Tracks customer scraping activity to generate geospatial
  heatmaps for sellers.
* **Media Storage:** Downloads and stores product images directly in the
  database as BLOBs.
* **Role-Based Access:** Distinct workflows for `customer` and `seller` accounts.

---

## 🛠 Prerequisites

* **Python:** 3.8+
* **Database:** MySQL 8.0+
* **Cloud API:** Google Cloud account with the **Generative AI API** enabled.
* **(Optional) Headless browser:** Chrome/Chromium + a driver (or
  `undetected-chromedriver`) if you want the Selenium fallback for tough pages.

---

## 🚀 Installation & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Database Setup
```bash
# Login to MySQL
mysql -u root -p

# Run the schema file
source database_schema.sql
```
*Note: increase `max_allowed_packet` in MySQL to handle image BLOBs (see Troubleshooting).*

### 3. Configure Environment (`.env`)
Configuration is read from environment variables — **do not hardcode secrets in
the source**. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```ini
# Flask
FLASK_SECRET_KEY=change-me-to-a-long-random-string

# MySQL
DB_HOST=localhost
DB_USER=your_mysql_username
DB_PASSWORD=your_mysql_password
DB_NAME=amazon_scraper_db

# Google Gemini
GOOGLE_API_KEY=your_gcp_api_key_here

# Scraper tuning (all optional — sensible defaults apply)
# SCRAPER_PROXY=http://user:pass@host:port
# SCRAPER_MAX_ATTEMPTS=4
# SCRAPER_TIMEOUT=25
# SCRAPER_BROWSER_FALLBACK=1
# SCRAPER_MIN_DELAY=0.5
# SCRAPER_MAX_DELAY=1.5
```

### 4. Run the Application
```bash
python server.py
```
The server starts at `http://localhost:5000`. CORS is pre-configured for the
frontend at `http://localhost:3000` with credentials (session cookies) enabled.

---

## 📂 Project Structure

```text
legal_metrology/
│
├── server.py               # ★ Canonical Flask app & all API routes
├── amazon_scraper/
│   ├── fetcher.py          # ★ Shared hardened HTTP fetcher (anti-bot, retries, browser fallback)
│   ├── amazon.py           # Default/generic product scraper
│   ├── book.py             # Book-specific scraper
│   ├── electric.py         # Electronics scraper
│   ├── food.py             # Food products scraper
│   ├── skincare.py         # Skincare products scraper
│   └── search.py           # Search-results link extractor
├── compliance.py           # Compliance analysis (used by /api/compliance/analyze)
├── compliance_copy.py      # Compliance analysis (used by /api/scrape auto-analyze & /validate)
├── comply.py               # Compliance helpers
├── chatbot_compliance.py   # Chatbot compliance assistant
├── database_schema.sql     # MySQL database schema
├── requirements.txt        # Python dependencies
├── .env.example            # Template for required environment variables
├── _archive/               # Deprecated/duplicate files kept for reference
└── README.md               # This file
```

---

## 📡 API Endpoints

### System
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Health probe (server + DB status). Used by the extension. |

### Authentication
| Method | Endpoint | Payload |
| :--- | :--- | :--- |
| `POST` | `/api/signup` | `{"username","password","role"}` |
| `POST` | `/api/login` | `{"username","password"}` |
| `POST` | `/api/logout` | N/A |

### Scraping & Compliance
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/scrape` | Scrape a product (auto-runs compliance by default). |
| `POST` | `/api/products/validate/<product_id>` | Run/re-run compliance for a product; returns score, grade, passed/total checks. |
| `POST` | `/api/compliance/analyze/<product_id>` | Full compliance report for a product. |
| `POST` | `/api/compliance/batch` | Batch compliance analysis. |
| `POST` | `/api/seller/check-upload` | Pre-upload check (multipart images + info). |
| `POST` | `/api/seller/check-upload-text` | Pre-upload check (text only). |
| `POST` | `/api/chat` | Compliance chatbot. |
| `POST` | `/extract-links` | Extract top product links from a search URL. |

### Data & Analytics
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard` | Dashboard summary. |
| `GET` | `/api/products` | List products. |
| `GET` | `/api/products/detailed` | List products with details. |
| `GET` | `/api/product/<product_id>` | Single product detail. |
| `GET` | `/api/image/<image_id>` | Fetch a stored image BLOB. |
| `GET` | `/api/seller/activity` | Who scraped the seller's products. |
| `GET` | `/api/heatmap` | Seller-scoped heatmap data. |
| `GET` | `/api/global-heatmap` | Global heatmap data. |

### Rewards (MT tokens / gifts)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/gifts` | Create a gift. |
| `POST` | `/api/gifts/redeem` | Redeem a gift. |
| `GET` | `/api/gifts/list` | List gifts. |
| `GET` | `/api/gifts/my-redemptions` | Current user's redemptions. |
| `POST` | `/api/gifts/add-tokens` | Add MT tokens. |
| `GET` | `/api/gifts/token-balance` | Current token balance. |

**Scrape payload example:**
```json
{ "url": "https://www.amazon.in/dp/B07G5829G9", "auto_analyze": true }
```

---

## 🔄 How It Works

1. **Submission:** User submits an Amazon URL (dashboard or extension overlay).
2. **AI Analysis:** The AI Router asks Gemini for the product category.
3. **Fetch:** The shared `fetcher` retrieves the page — rotating user agents,
   priming cookies, retrying with backoff, and falling back to a headless
   browser if Amazon shows a bot wall.
4. **Extraction:** The category scraper parses the HTML with BeautifulSoup.
5. **Storage:** Product is upserted by ASIN; images are stored as BLOBs.
6. **Compliance:** OCR + rule checks produce a score, grade, and violations.
7. **Analytics:** Customer-on-seller scrapes are logged for heatmaps.

### Heatmap & Activity Logic
* **Customer scrapes Seller's product:** logged with seller + customer + location; appears on the seller's heatmap.
* **Seller scrapes own product:** logged with `customer_id: NULL`; administrative only.
* **Seller scrapes another seller's product:** treated as a competitor scrape.

---

## 🧭 Scraping Reliability

The old scrapers advertised a stale Chrome/91 user agent, always requested
Brotli even without a decoder, and had no anti-bot handling — so Amazon returned
CAPTCHA/503 pages and scraping failed. All scrapers now share
`amazon_scraper/fetcher.py`, which:

* rotates among modern browser user agents (with matching Client-Hint headers),
* advertises Brotli **only** when a decoder is installed,
* primes cookies on the Amazon homepage before hitting product pages,
* detects bot walls / CAPTCHAs and retries with exponential backoff + jitter,
* optionally falls back to a headless browser (`SCRAPER_BROWSER_FALLBACK=1`).

Tune behavior via the `SCRAPER_*` environment variables listed above. For heavy
usage, set `SCRAPER_PROXY` to route requests through a rotating proxy.

---

## 🐛 Troubleshooting

* **Scraping returns nothing / 500:** Amazon may be blocking you. Install
  `brotli` and (optionally) `selenium` + a Chrome driver, then set
  `SCRAPER_BROWSER_FALLBACK=1`. Consider a proxy via `SCRAPER_PROXY`.
* **Image Storage Fails:** `SET GLOBAL max_allowed_packet=67108864;` (64MB) in MySQL.
* **Sessions not persisting:** ensure `FLASK_SECRET_KEY` is set in `.env`.
* **Location Tracking:** uses `ipapi.co` (free tier). Localhost won't geolocate.
* **AI Router Fails:** ensure the Generative AI API is enabled and `GOOGLE_API_KEY` is valid.

---

## 📈 Future Roadmap

* [ ] JWT Authentication
* [ ] Built-in rate limiting & proxy rotation
* [ ] Redis caching for frequent lookups
* [ ] Docker containerization
* [ ] Swagger/OpenAPI documentation
* [ ] Consolidate the compliance modules (`compliance*.py`, `comply.py`) into one package

---

## 📝 License

MIT License — feel free to use for your projects!
