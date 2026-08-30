#!/usr/bin/env python3
"""
Flask Backend for Amazon Product Scraper
Integrates AI Router, MySQL Database, Multiple Scrapers, and AI Compliance Module
"""

from flask import Flask, request, jsonify, session, send_file, abort
import io
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
import hashlib
import os
import re
import requests
from datetime import datetime
import json
import google.generativeai as genai

from dotenv import load_dotenv

# Import scraper modules (assuming they're in the same directory)
import amazon_scraper.amazon as amazon
import amazon_scraper.book as book
import amazon_scraper.electric as electric
import amazon_scraper.food as food
import amazon_scraper.skincare as skincare
import amazon_scraper.search as search
import chatbot_compliance
import comply as comply

# Import AI Compliance Module
import compliance
import compliance_copy
from datetime import timedelta

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=24)
CORS(app, 
     origins=["http://localhost:3000"],  # Your frontend URL
     supports_credentials=True,
     allow_headers=["Content-Type"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

load_dotenv()  # Load environment variables from .env file

# ==================== CONFIGURATION ====================

# MySQL Configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

# GCP Generative AI Configuration
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# ==================== DATABASE CONNECTION ====================

def get_db_connection():
    """Create and return a database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"[ERROR] Database connection failed: {e}")
        return None

# ==================== AI ROUTER (STEP 1) ====================

def ai_router(url: str) -> dict:
    """
    Uses Google Generative AI to determine which scraper to use.
    Returns the scraped product data.
    """
    print(f"[AI ROUTER] Analyzing URL: {url}")
    
    # Prompt for AI
    prompt = f"""
    Analyze this Amazon product URL and determine the product category:
    URL: {url}
    
    Categories available:
    - book: For novels, textbooks, any printed books
    - food: For food items, snacks, beverages, groceries
    - skincare: For beauty products, cosmetics, skincare items
    - electric: For electronics, computers, gaming devices
    - amazon: For anything else (default)
    
    Respond with ONLY ONE WORD - the category name (book, food, skincare, electric, or amazon).
    """
    
    category = 'amazon'  # Default fallback
    
    try:
        response = model.generate_content(prompt)
        category = response.text.strip().lower()
        
        # Validate response
        valid_categories = ['book', 'food', 'skincare', 'electric', 'amazon']
        if category not in valid_categories:
            print(f"[AI ROUTER] Invalid category '{category}', using default 'amazon'")
            category = 'amazon'
        else:
            print(f"[AI ROUTER] SUCCESS: Detected category: {category}")
        
    except Exception as e:
        print(f"[AI ROUTER] WARNING: AI analysis failed: {e}")
        print(f"[AI ROUTER] Using URL-based heuristics as fallback...")
        
        # Fallback: Simple URL/keyword analysis
        url_lower = url.lower()
        if '/books/' in url_lower or 'book' in url_lower:
            category = 'book'
        elif 'food' in url_lower or 'grocery' in url_lower or 'snack' in url_lower:
            category = 'food'
        elif 'beauty' in url_lower or 'skincare' in url_lower or 'cosmetic' in url_lower:
            category = 'skincare'
        elif 'electronics' in url_lower or 'computer' in url_lower or 'gaming' in url_lower:
            category = 'electric'
        else:
            category = 'amazon'
        
        print(f"[AI ROUTER] Fallback detected category: {category}")
    
    # Map category to scraper
    scraper_map = {
        'book': book.AmazonScraper(),
        'food': food.AmazonScraper(),
        'skincare': skincare.AmazonScraper(),
        'electric': electric.AmazonScraper(),
        'amazon': amazon.AmazonScraper()
    }
    
    scraper = scraper_map.get(category, amazon.AmazonScraper())
    
    # Execute scraping
    product_data = scraper.scrape_product(url)
    
    if product_data:
        product_data['detected_category'] = category
        return product_data
    else:
        return None

# ==================== HELPER FUNCTIONS ====================

def hash_password(password: str) -> str:
    """Simple password hashing using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def extract_asin_from_url(url: str) -> str:
    """Extract ASIN from Amazon URL"""
    match = re.search(r'/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{9,13})', url, re.IGNORECASE)
    return match.group(1) if match else None

def download_image(image_url: str) -> bytes:
    """Download image and return as bytes"""
    try:
        response = requests.get(image_url, timeout=10)
        if response.status_code == 200:
            return response.content
        return None
    except Exception as e:
        print(f"[ERROR] Failed to download image: {e}")
        return None

def get_location_from_ip(ip_address: str) -> dict:
    """
    Get geographic location from IP address for heatmap generation.
    Uses ipapi.co free tier (1000 requests/day).
    """
    try:
        response = requests.get(f'https://ipapi.co/{ip_address}/json/', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                'location': f"{data.get('city', 'Unknown')}, {data.get('region', '')}, {data.get('country_name', '')}",
                'latitude': data.get('latitude'),
                'longitude': data.get('longitude'),
                'city': data.get('city'),
                'country': data.get('country_name')
            }
    except Exception as e:
        print(f"[WARNING] Failed to get location from IP: {e}")
    
    return {
        'location': 'Unknown',
        'latitude': None,
        'longitude': None,
        'city': None,
        'country': None
    }

def log_customer_scrape_activity(product_data: dict, seller_id: int, customer_id: int, asin: str, customer_ip: str = None):
    """
    Log when a CUSTOMER scrapes a SELLER's product.
    Safely handles missing seller_information or location fields.
    """
    connection = get_db_connection()
    if not connection:
        return
    
    # Safe location extraction
    try:
        location_data = get_location_from_ip(customer_ip) if customer_ip else {}
    except:
        location_data = {}

    location = location_data.get('location', 'Unknown')
    latitude = location_data.get('latitude')
    longitude = location_data.get('longitude')

    # Safe seller_information extraction
    try:
        seller_info = product_data.get('seller')
        seller_info_json = json.dumps(seller_info) if seller_info else None
    except:
        seller_info_json = None

    cursor = connection.cursor()
    query = """
        INSERT INTO SellerActivity 
        (seller_id, customer_id, action, seller_information, location, latitude, longitude, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    action = f"Customer scraped product ASIN {asin}"

    try:
        cursor.execute(query, (
            None,
            customer_id,
            action,
            seller_info_json,
            location,
            latitude,
            longitude,
            datetime.now()
        ))

        connection.commit()
        print(f"[LOG] Customer activity logged: Seller {seller_id}, Customer {customer_id}, Location: {location}")

    except Error as e:
        print(f"[ERROR] Failed to log customer activity (non-critical): {e}")
        try:
            connection.commit()
        except:
            pass

    finally:
        cursor.close()
        connection.close()


def log_seller_own_activity(product_data: dict, seller_id: int, action: str, seller_ip: str = None):
    """
    Log when a SELLER scrapes their own product.
    Safely handles missing seller_information or location fields.
    """
    connection = get_db_connection()
    if not connection:
        return

    # Safe location extraction
    try:
        location_data = get_location_from_ip(seller_ip) if seller_ip else {}
    except:
        location_data = {}

    location = location_data.get('location', 'Unknown')
    latitude = location_data.get('latitude')
    longitude = location_data.get('longitude')

    # Safe seller_information extraction
    try:
        seller_info = product_data.get('seller')
        seller_info_json = json.dumps(seller_info) if seller_info else None
    except:
        seller_info_json = None

    cursor = connection.cursor()
    query = """
        INSERT INTO SellerActivity 
        (seller_id, customer_id, action, seller_information, location, latitude, longitude, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    try:
        cursor.execute(query, (
            seller_id,
            None,
            action,
            seller_info_json,
            location,
            latitude,
            longitude,
            datetime.now()
        ))

        connection.commit()
        print(f"[LOG] Seller own activity logged: {action}")

    except Error as e:
        print(f"[ERROR] Failed to log seller activity (non-critical): {e}")
        try:
            connection.commit()
        except:
            pass

    finally:
        cursor.close()
        connection.close()


# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Lightweight health probe used by the browser extension.

    Returns 200 as long as the Flask process is up. Also reports database
    connectivity (non-fatal) and whether the current session is logged in,
    which is handy for debugging the extension connection.
    """
    db_ok = False
    try:
        conn = get_db_connection()
        if conn is not None:
            db_ok = conn.is_connected()
            conn.close()
    except Exception as e:
        print(f"[HEALTH] DB check failed: {e}")

    return jsonify({
        'status': 'ok',
        'service': 'metamark-backend',
        'database': 'connected' if db_ok else 'unavailable',
        'logged_in': bool(session.get('logged_in')),
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.route('/api/signup', methods=['POST'])
def signup():
    """User registration endpoint"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'customer')  # Default to customer
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    if role not in ['customer', 'seller']:
        return jsonify({'error': 'Invalid role. Must be customer or seller'}), 400
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor()
    
    # Check if username exists
    cursor.execute("SELECT id FROM Users WHERE username = %s", (username,))
    if cursor.fetchone():
        cursor.close()
        connection.close()
        return jsonify({'error': 'Username already exists'}), 409
    
    # Insert new user
    hashed_pw = hash_password(password)
    query = "INSERT INTO Users (username, password, role) VALUES (%s, %s, %s)"
    
    try:
        cursor.execute(query, (username, hashed_pw, role))
        connection.commit()
        user_id = cursor.lastrowid
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'message': 'User created successfully',
            'user_id': user_id,
            'username': username,
            'role': role
        }), 201
        
    except Error as e:
        cursor.close()
        connection.close()
        return jsonify({'error': f'Failed to create user: {str(e)}'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """User login endpoint"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    hashed_pw = hash_password(password)
    
    query = "SELECT id, username, role FROM Users WHERE username = %s AND password = %s"
    cursor.execute(query, (username, hashed_pw))
    user = cursor.fetchone()
    
    cursor.close()
    connection.close()
    
    if user:
        # Set session
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['logged_in'] = True
        
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'role': user['role']
            }
        }), 200
    else:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    """User logout endpoint"""
    session.clear()
    return jsonify({'message': 'Logged out successfully'}), 200

# ==================== SCRAPING ENDPOINT ====================

from flask import request, jsonify, session
import json
import base64
from mysql.connector import Error

def detect_scraper_category(product_data: dict) -> str:
    """Heuristic detection of scraper/category from returned keys."""
    if not isinstance(product_data, dict):
        return "unknown"
    keys = set(product_data.keys())
    # Book scrapers often have 'about_author' or 'ISBN' inside product_details
    if "about_author" in keys or any("ISBN" in k for k in (product_data.get("product_details") or {})):
        return "book"
    # Food scrapers often have nutrition/ingredients/important_info/product_metadata
    if "nutrition_info" in keys or "important_info" in keys or "product_metadata" in keys:
        return "food"
    # Skincare / beauty often provide 'important_info' and 'product_metadata' too,
    # but may include 'Safety Information' in important_info.
    if "important_info" in keys and ("Ingredients" in (product_data.get("important_info") or {} ) or "Safety Information" in (product_data.get("important_info") or {})):
        return "skincare"
    # Electronics / general produce 'technical_details' or 'additional_info'
    if "technical_details" in keys or "additional_info" in keys or "specifications" in keys:
        return "electronics"
    # Fallback: if feature_bullets present => general/grocery/retail
    if "feature_bullets" in keys:
        return "general"
    return "unknown"

def normalize_scraper_output(data: dict) -> dict:
    """
    Normalize different scraper outputs into a consistent DB schema.
    Keep fields that are common and also copy scraper-specific blocks under names.
    """
    if not isinstance(data, dict):
        return {}

    # canonical top-level fields (first-class)
    normalized = {
        "url": data.get("url"),
        "asin": data.get("asin"),
        "title": data.get("title"),
        "price": data.get("price"),
        "currency": data.get("currency"),
        "country": data.get("country"),
        "language": data.get("language"),
        "rating": data.get("rating"),
        "reviews_count": data.get("reviews_count"),
        "availability": data.get("availability"),
        "shipping_details": data.get("shipping_details") or data.get("shipping") or None,
        "detected_category": data.get("detected_category") or detect_scraper_category(data),
        # Primary descriptive buckets (fallbacks in order)
        "description": data.get("description") or data.get("about_product") or None,
        "feature_bullets": data.get("feature_bullets") or data.get("highlights") or [],
        "about_author": data.get("about_author") or None,
        # specs/tech/product details (merge sensible sources)
        "product_details": data.get("product_details") or data.get("product_metadata") or data.get("product_information") or {},
        "specifications": data.get("specifications") or data.get("technical_details") or {},
        "important_information": data.get("important_information") or data.get("important_info") or {},
        # food/skincare specific
        "ingredients": data.get("ingredients") or (data.get("important_info") or {}).get("Ingredients") or None,
        "nutrition_info": data.get("nutrition_info") or (data.get("important_info") or {}).get("Nutrition") or None,
        # seller block preserved
        "seller_information": data.get("seller"),
        # any other captured raw buckets kept for debugging / QA
        "extra": {}
    }

    # Preserve common named extras that appear per-scraper
    for key in ("additional_info", "product_metadata", "important_info", "technical_details", "about_author", "product_json"):
        if key in data and data[key] is not None:
            normalized["extra"][key] = data[key]

    # Images: many scrapers use 'images' but some use 'image_urls' or 'img' — fallback chain
    imgs = data.get("images") or data.get("image_urls") or data.get("image_list") or []
    # ensure list
    if isinstance(imgs, str):
        imgs = [imgs]
    normalized["images"] = imgs

    return normalized

@app.route('/api/scrape', methods=['POST'])
def scrape_product():
    """Main scraping endpoint with database integration + AUTO compliance analysis + selleractivity logging"""
    # ---------------------------------------------------
    # AUTH CHECK
    # ---------------------------------------------------
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session.get('user_id')
    user_role = session.get('role')

    data = request.json or {}
    url = data.get('url')
    auto_analyze = data.get('auto_analyze', True)

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # ---------------------------------------------------
    # EXTRACT ASIN (use your existing func)
    # ---------------------------------------------------
    asin = extract_asin_from_url(url)
    if not asin:
        return jsonify({'error': 'Invalid Amazon URL'}), 400

    # Get customer IP address
    customer_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if customer_ip and ',' in customer_ip:
        customer_ip = customer_ip.split(',')[0].strip()

    print(f"[SCRAPE] User {user_id} ({user_role}) scraping ASIN: {asin} from IP: {customer_ip}")

    # ---------------------------------------------------
    # STEP 1 — AI ROUTER SCRAPER
    # ---------------------------------------------------
    product_data = ai_router(url)
    if not product_data:
        return jsonify({'error': 'Failed to scrape product'}), 500

    # Normalize and also keep raw
    normalized = normalize_scraper_output(product_data)
    # Ensure detected_category is set from heuristics if not present
    if not normalized.get("detected_category"):
        normalized["detected_category"] = detect_scraper_category(product_data)

    # ---------------------------------------------------
    # STEP 2 — DB CONNECTION
    # ---------------------------------------------------
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT product_id, user_id AS seller_id FROM Products WHERE asin = %s", (asin,))
        existing_product = cursor.fetchone()

        # core landing fields (use normalized where possible)
        title = normalized.get('title')
        price = normalized.get('price')
        currency = normalized.get('currency')
        country = normalized.get('country')
        language = normalized.get('language')

        # Build JSON blobs:
        # - product_json_raw: store original scraper output unmodified (for QA)
        # - product_json: standardized format used by UI/consumers
        product_json_raw = product_data
        product_json = normalized

        seller_id = None

        if existing_product:
            product_id = existing_product['product_id']
            seller_id = existing_product['seller_id']
            print(f"[UPDATE] Updating product {product_id} (seller: {seller_id})")

            update_query = """
                UPDATE Products
                SET url=%s, title=%s, price=%s, currency=%s, country=%s,
                    language=%s, seller_information=%s, product_json=%s, product_json_raw=%s
                WHERE product_id=%s
            """
            cursor.execute(update_query, (
                url, title, price, currency, country, language,
                json.dumps(normalized.get('seller_information') or product_data.get('seller')),
                json.dumps(product_json),
                json.dumps(product_json_raw),
                product_id
            ))

            # delete existing images to replace with new ones
            cursor.execute("DELETE FROM Images WHERE product_id = %s", (product_id,))
            print(f"[DELETE] Old images removed for {product_id}")

        else:
            print(f"[INSERT] Creating new product entry")
            insert_query = """
                INSERT INTO Products 
                (user_id, url, asin, title, price, currency, country, language, seller_information, product_json, product_json_raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                user_id, url, asin, title, price, currency, country, language,
                json.dumps(normalized.get('seller_information') or product_data.get('seller')),
                json.dumps(product_json),
                json.dumps(product_json_raw)
            ))
            product_id = cursor.lastrowid
            seller_id = user_id  # first scraper becomes owner

        connection.commit()

        # ---------------------------------------------------
        # STEP 3 — STORE IMAGES AS BLOBS
        # ---------------------------------------------------
        images = normalized.get('images') or []
        print(f"[IMAGES] Found {len(images)} images (keys tried: images/image_urls/image_list)")

        images_inserted = 0
        for img_url in images[:10]:
            image_data = download_image(img_url)
            if image_data:
                cursor.execute(
                    "INSERT INTO Images (product_id, image_data) VALUES (%s, %s)",
                    (product_id, image_data)
                )
                images_inserted += 1

        connection.commit()
        print(f"[IMAGES] Stored {images_inserted} images")

        # ---------------------------------------------------
        # STEP 4 — SELLER ACTIVITY LOGGING
        # ---------------------------------------------------
        from datetime import datetime
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        action = f"{user_role.capitalize()} scraped product ASIN {asin}"
        seller_info_json = json.dumps(product_data.get('seller'))

        if user_role == "customer":
            sa_seller_id = None
            sa_customer_id = user_id
        elif user_role == "seller" and seller_id == user_id:
            sa_seller_id = user_id
            sa_customer_id = None
        elif user_role == "seller" and seller_id and seller_id != user_id:
            sa_seller_id = seller_id
            sa_customer_id = user_id
        else:
            sa_seller_id = None
            sa_customer_id = None

        seller_activity_query = """
            INSERT INTO selleractivity
            (seller_id, customer_id, action, seller_information,
             location, latitude, longitude, timestamp, created_at)
            VALUES (%s, %s, %s, %s, NULL, NULL, NULL, %s, %s)
        """
        cursor.execute(
            seller_activity_query,
            (sa_seller_id, sa_customer_id, action, seller_info_json, ts, ts)
        )
        connection.commit()
        print(f"[SELLER-ACTIVITY] Logged: {action}")

        # ---------------------------------------------------
        # STEP 5 — AUTO COMPLIANCE ANALYSIS
        # ---------------------------------------------------
        compliance_report = None
        if auto_analyze:
            print(f"[AUTO-ANALYZE] Running compliance...")
            try:
                compliance_report = compliance_copy.analyze_compliance(product_id)
            except Exception as e:
                print(f"[AUTO-ANALYZE] FAILED: {e}")

        # ---------------------------------------------------
        # STEP 6 — RETRIEVE STORED IMAGES AS BASE64
        # ---------------------------------------------------
        cursor.execute(
            "SELECT image_id, image_data FROM Images WHERE product_id = %s ORDER BY image_id",
            (product_id,)
        )
        image_rows = cursor.fetchall()
        image_blobs = []
        for row in image_rows:
            image_blobs.append({
                'image_id': row['image_id'],
                'image_data': base64.b64encode(row['image_data']).decode('utf-8')
            })

        print(f"[RETRIEVE] Retrieved {len(image_blobs)} images from database")

        cursor.close()
        connection.close()

        # ---------------------------------------------------
        # FINAL RESPONSE
        # ---------------------------------------------------
        response = {
            'message': 'Product scraped & stored successfully',
            'product_id': product_id,
            'asin': asin,
            'title': title,
            'images_stored': images_inserted,
            'images': image_blobs,
            'is_update': existing_product is not None,
            'seller_id': seller_id,
            'seller_info': product_data.get('seller'),
            'price': price,
            'product_json': product_json,         # standardized
            'product_json_raw': product_json_raw  # raw for QA
        }

        if compliance_report and 'error' not in compliance_report:
            response['compliance_analysis'] = {
                'score': compliance_report.get('compliance_score'),
                'grade': compliance_report.get('compliance_grade'),
                'is_compliant': compliance_report.get('is_compliant'),
                'requires_action': compliance_report.get('requires_action'),
                'violations_count': compliance_report.get('violation_summary', {}).get('total', 0)
            }

        return jsonify(response), 200

    except Error as e:
        connection.rollback()
        print(f"[DB ERROR] {e}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500
# ==================== AI COMPLIANCE ENDPOINTS (NEW!) ====================

@app.route('/api/compliance/analyze/<int:product_id>', methods=['POST'])
def analyze_product_compliance(product_id):
    """
    Trigger compliance analysis for a specific product
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    print(f"[API] Compliance analysis requested for product {product_id}")
    
    try:
        compliance_report = compliance.analyze_compliance(product_id)
        
        if 'error' in compliance_report:
            return jsonify({'error': compliance_report['error']}), 500
        
        return jsonify({
            'message': 'Compliance analysis complete',
            'report': compliance_report
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Compliance analysis failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/validate/<int:product_id>', methods=['POST'])
def validate_product(product_id):
    """
    Run (or re-run) compliance validation for a product and return a result
    shaped for the browser-extension overlay.

    The extension calls this as a fallback when /api/scrape did not already
    include a `compliance_analysis` block. The response fields
    (compliance_score, final_grade, passed_checks, total_checks) mirror what
    the extension builds inline from the scrape response, so both code paths
    render identically. We use `compliance_copy.analyze_compliance` here to
    match the auto-analyze path in /api/scrape.
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    print(f"[API] Product validation requested for product {product_id}")

    try:
        report = compliance_copy.analyze_compliance(product_id)

        if not report or 'error' in report:
            return jsonify({
                'error': (report or {}).get('error', 'Validation failed'),
                'product_id': product_id
            }), 500

        total_checks = 10
        violations_total = report.get('violation_summary', {}).get('total', 0)
        passed_checks = max(0, total_checks - violations_total)

        return jsonify({
            'product_id': product_id,
            'compliance_score': report.get('compliance_score', 0),
            'final_grade': report.get('compliance_grade', 'N/A'),
            'passed_checks': passed_checks,
            'total_checks': total_checks,
            'is_compliant': report.get('is_compliant', False),
            'requires_action': report.get('requires_action', False),
            'report': report
        }), 200

    except Exception as e:
        print(f"[ERROR] Product validation failed: {e}")
        return jsonify({'error': str(e), 'product_id': product_id}), 500

@app.route('/api/seller/check-upload', methods=['POST'])
def check_seller_upload():
    """
    Analyze seller's product BEFORE uploading to Amazon
    Accepts multipart form data with images and product information
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    # Get category (either from form or auto-detect)
    category = request.form.get('category', 'amazon')
    
    # Get product data
    product_data = {
        'title': request.form.get('title', ''),
        'description': request.form.get('description', ''),
        'feature_bullets': json.loads(request.form.get('features', '[]')),
        'product_details': json.loads(request.form.get('details', '{}')),
        'specifications': json.loads(request.form.get('specifications', '{}')),
        'seller_information': {}
    }
    
    # Get uploaded images
    image_files = request.files.getlist('images')
    image_blobs = []
    
    for img_file in image_files[:10]:  # Limit to 10 images
        try:
            image_blobs.append(img_file.read())
        except Exception as e:
            print(f"[WARNING] Failed to read image: {e}")
    
    if not image_blobs:
        return jsonify({'error': 'At least one image is required'}), 400
    
    print(f"[SELLER CHECK] Analyzing upload with {len(image_blobs)} images")
    
    try:
        feedback_report = comply.analyze_seller_upload(image_blobs, product_data, category)
        
        if 'error' in feedback_report:
            return jsonify({'error': feedback_report['error']}), 500
        
        return jsonify({
            'message': 'Pre-upload compliance check complete',
            'feedback': feedback_report
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Seller upload check failed: {e}")
        return jsonify({'error': str(e)}), 500
    
# @app.route('/api/seller/check-upload-text', methods=['POST'])
# def check_seller_upload_text():
#     """
#     Analyze seller's product using raw text description from speech-to-text
#     Accepts multipart form data with images and raw text description
#     """
#     if not session.get('logged_in'):
#         return jsonify({'error': 'Authentication required'}), 401
    
#     # Get category
#     category = request.form.get('category', 'amazon')
    
#     # Get raw text description (from speech-to-text)
#     raw_text = request.form.get('description', '').strip()
    
#     if not raw_text:
#         return jsonify({'error': 'Product description is required'}), 400
    
#     # Get uploaded images
#     image_files = request.files.getlist('images')
#     image_blobs = []
    
#     for img_file in image_files[:10]:  # Limit to 10 images
#         try:
#             image_blobs.append(img_file.read())
#         except Exception as e:
#             print(f"[WARNING] Failed to read image: {e}")
    
#     if not image_blobs:
#         return jsonify({'error': 'At least one image is required'}), 400
    
#     print(f"[SELLER TEXT CHECK] Analyzing upload with {len(image_blobs)} images and text description ({len(raw_text)} chars)")
    
#     try:
#         feedback_report = compliance_copy.analyze_seller_upload_text(image_blobs, raw_text, category)
        
#         if 'error' in feedback_report:
#             return jsonify({'error': feedback_report['error']}), 500
        
#         return jsonify({
#             'message': 'Pre-upload compliance check complete (text-based)',
#             'feedback': feedback_report
#         }), 200
        
#     except Exception as e:
#         print(f"[ERROR] Seller text upload check failed: {e}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


# ==================== AI-POWERED INTENT DETECTION ====================

def detect_user_intent_with_ai(message: str, user_role: str, username: str) -> str:
    """
    Use Gemini AI to detect whether user wants:
    1. 'personal_data' - Query their own products/data
    2. 'general_compliance' - General compliance questions
    
    Returns: 'personal_data' or 'general_compliance'
    """
    try:
        prompt = f"""You are an intent classifier for an e-commerce compliance platform.

Current User:
- Username: {username}
- Role: {user_role}

User Message: "{message}"

Analyze the message and determine the user's intent:

1. **personal_data**: User wants to query THEIR OWN data
   - Examples: "Show me my products", "What's my score?", "How many products do I have?", "My dashboard", "Do I have any compliant products?"
   - Keywords: my, mine, I, me, show me, my products, my score, dashboard, statistics about me
   
2. **general_compliance**: User wants general information about compliance/regulations
   - Examples: "What is MRP?", "How to improve compliance?", "Tell me about Legal Metrology Act", "What are the requirements for food products?"
   - Keywords: what is, how to, tell me about, explain, requirements, regulations, rules

IMPORTANT: 
- If the message mentions "my", "I", "mine", "me" in relation to products/data → personal_data
- If asking about regulations, rules, general advice → general_compliance
- When in doubt, prefer 'personal_data' for logged-in users

Respond with ONLY ONE WORD: either "personal_data" or "general_compliance"

Intent:"""

        response = model.generate_content(prompt)
        intent = response.text.strip().lower()
        
        # Validate response
        if 'personal_data' in intent:
            return 'personal_data'
        elif 'general_compliance' in intent:
            return 'general_compliance'
        else:
            # Default to personal_data if unclear
            print(f"[WARNING] Unclear intent from AI: {intent}. Defaulting to personal_data")
            return 'personal_data'
            
    except Exception as e:
        print(f"[ERROR] Intent detection failed: {e}")
        # Fallback: simple keyword check
        if any(word in message.lower() for word in ['my', 'mine', 'i have', 'show me', 'dashboard']):
            return 'personal_data'
        return 'general_compliance'

# ==================== SMART CHAT ROUTE ====================

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Intelligent chatbot endpoint with AI-powered intent detection
    Routes to either:
    - User-specific chatbot (personal data queries)
    - General compliance chatbot (regulatory questions)
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.json
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'error': 'Message is required'}), 400
    
    try:
        # Get user info from session
        user_id = session.get('user_id')
        user_role = session.get('role', 'customer')
        username = session.get('username', 'User')
        
        # Use AI to detect intent
        intent = detect_user_intent_with_ai(user_message, user_role, username)
        
        print(f"[CHAT ROUTER] User: {username} (ID: {user_id}) | Intent: {intent} | Message: {user_message[:80]}")
        
        if intent == 'personal_data':
            # Use user-context chatbot for personal queries
            print("[CHAT ROUTER] → Routing to User-Context Chatbot")
            result = chatbot_compliance.user_chatbot(user_id, user_message)
            
            return jsonify({
                'message': result['response'],
                'intent': 'personal_data',
                'user_context': result.get('user_context'),
                'timestamp': datetime.now().isoformat()
            }), 200
            
        else:
            # Use general compliance chatbot
            print("[CHAT ROUTER] → Routing to General Compliance Chatbot")
            response = compliance.chatbot_agent(user_message)
            
            return jsonify({
                'message': response,
                'intent': 'general_compliance',
                'timestamp': datetime.now().isoformat()
            }), 200
        
    except Exception as e:
        print(f"[ERROR] Chatbot error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to process message'}), 500
    
@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    """Get personalized dashboard for current user"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        user_id = session.get('user_id')
        dashboard_data = chatbot_compliance.get_user_dashboard(user_id)
        
        if 'error' in dashboard_data:
            return jsonify({'error': dashboard_data['error']}), 500
        
        return jsonify(dashboard_data), 200
        
    except Exception as e:
        print(f"[ERROR] Dashboard endpoint failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/compliance/batch', methods=['POST'])
def batch_analyze():
    """
    Batch analyze multiple products
    """
    if not session.get('logged_in') or session.get('role') != 'seller':
        return jsonify({'error': 'Seller access required'}), 403
    
    data = request.json
    product_ids = data.get('product_ids', [])
    
    if not product_ids:
        return jsonify({'error': 'Product IDs required'}), 400
    
    try:
        results = compliance.batch_analyze_products(product_ids)
        
        return jsonify({
            'message': 'Batch analysis complete',
            'results': results
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Batch analysis failed: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== EXISTING ENDPOINTS ====================




@app.route('/api/products', methods=['GET'])
def get_products():
    """Get all products for the logged-in user"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    user_id = session.get('user_id')
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    cursor.execute(
        """SELECT product_id, asin, title, price, currency, url, rating, remarks, last_analysed 
           FROM Products WHERE user_id = %s""",
        (user_id,)
    )
    products = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    return jsonify({'products': products}), 200

@app.route('/api/image/<int:image_id>')
def get_image(image_id):
    connection = get_db_connection()
    print("route gets called")
    cursor = connection.cursor(dictionary=True)
    print("cursor declaration is successful")
    
    # Only fetch the binary data for this specific image
    cursor.execute("SELECT image_data FROM Images WHERE image_id = %s", (image_id,))
    result = cursor.fetchone()
    print(f"result: {result}")
    
    cursor.close()
    connection.close()

    if result and result['image_data']:
        # Convert binary data to a file-like object
        return send_file(
            io.BytesIO(result['image_data']),
            mimetype='image/jpeg'  # Change to 'image/png' if your images are PNGs
        )
    
    return abort(404)

@app.route('/api/product/<int:product_id>', methods=['GET'])
def get_product_detail(product_id):
    """Get detailed product information including compliance report"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    
    # Get product details
    cursor.execute("SELECT * FROM Products WHERE product_id = %s", (product_id,))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        connection.close()
        return jsonify({'error': 'Product not found'}), 404
    
    # Parse JSON fields
    if product.get('product_json'):
        product['product_json'] = json.loads(product['product_json'])
    
    if product.get('analysis_results'):
        product['compliance_report'] = json.loads(product['analysis_results'])
    
    # NOTICE: We removed 'image_data' from this SELECT to keep it fast/light
    cursor.execute("SELECT image_id, created_at FROM Images WHERE product_id = %s", (product_id,))
    
    images = cursor.fetchall()
    image_count = len(images)

    # Add the URL to each image dictionary
    # request.host_url builds the full http://localhost:5000/... link
    for img in images:
        img['url'] = f"{request.host_url}api/image/{img['image_id']}"

    product['image_count'] = image_count
    product['images'] = images
    
    cursor.close()
    connection.close()
    
    return jsonify({'product': product}), 200

@app.route('/api/products/detailed', methods=['GET'])
def get_products_detailed():
    """Get all products with full details for the logged-in user"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    user_id = session.get('user_id')
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    
    # Get all products for the user
    cursor.execute("SELECT * FROM Products WHERE user_id = %s", (user_id,))
    products = cursor.fetchall()
    
    # Enrich each product with images (same as individual endpoint)
    for product in products:
        product_id = product['product_id']
        
        # Parse JSON fields
        if product.get('product_json'):
            product['product_json'] = json.loads(product['product_json'])
        
        if product.get('analysis_results'):
            product['compliance_report'] = json.loads(product['analysis_results'])
        
        # NOTICE: We removed 'image_data' from this SELECT to keep it fast/light
        cursor.execute("SELECT image_id, created_at FROM Images WHERE product_id = %s", (product_id,))
        
        images = cursor.fetchall()
        image_count = len(images)

        # Add the URL to each image dictionary
        # request.host_url builds the full http://localhost:5000/... link
        for img in images:
            img['url'] = f"{request.host_url}api/image/{img['image_id']}"

        product['image_count'] = image_count
        product['images'] = images
    
    cursor.close()
    connection.close()
    
    return jsonify({'products': products}), 200



@app.route('/api/seller/activity', methods=['GET'])
def get_seller_activity():
    """Get activity logs for sellers - shows who scraped their products"""
    if not session.get('logged_in') or session.get('role') != 'seller':
        return jsonify({'error': 'Seller access required'}), 403
    
    seller_id = session.get('user_id')
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    
    query = """
        SELECT 
            sa.*,
            u.username as customer_username
        FROM SellerActivity sa
        LEFT JOIN Users u ON sa.customer_id = u.id
        WHERE sa.seller_id = %s
        ORDER BY sa.timestamp DESC
        LIMIT 100
    """
    
    cursor.execute(query, (seller_id,))
    activities = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    return jsonify({'activities': activities}), 200

@app.route('/api/heatmap', methods=['GET'])
def get_heatmap_data():
    print("\n====== /api/heatmap (PRODUCTS ONLY) CALLED ======")

    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session['user_id']
    role = session['role']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ---------- QUERY FOR BOTH ROLES ----------
    query = """
        SELECT
            JSON_UNQUOTE(JSON_EXTRACT(p.seller_information, '$.ai_insights.location')) AS location,
            JSON_UNQUOTE(JSON_EXTRACT(p.seller_information, '$.name')) AS seller_name,

            COUNT(*) AS total_scrapes,

            AVG(
                CAST(
                    JSON_UNQUOTE(JSON_EXTRACT(p.analysis_results, '$.compliance_score'))
                    AS DECIMAL(5,2)
                )
            ) AS avg_compliance_score,

            MAX(p.created_at) AS last_activity,

            -- NEW FIELD: Product details grouped inside JSON array
            JSON_ARRAYAGG(
                JSON_OBJECT(
                    'product_id', p.product_id,
                    'title', p.title,
                    'rating', p.rating,
                    'compliance_score',
                        CAST(
                            JSON_UNQUOTE(JSON_EXTRACT(p.analysis_results, '$.compliance_score'))
                            AS DECIMAL(5,2)
                        ),
                    'created_at', p.created_at
                )
            ) AS products

        FROM Products p
        WHERE p.user_id = %s
        AND JSON_EXTRACT(p.seller_information, '$.ai_insights.location') IS NOT NULL
        GROUP BY location, seller_name
        ORDER BY total_scrapes DESC;
    """

    print("\nExecuting SQL:\n", query)
    cursor.execute(query, (user_id,))
    rows = cursor.fetchall()

    print(f"\nReturned {len(rows)} rows:")
    for r in rows:
        print(r)

    cursor.close()
    conn.close()

    return jsonify({
        "user_role": role,
        "heatmap_data": rows,
        "total_locations": len(rows),
        "total_scrapes": sum(x['total_scrapes'] for x in rows)
    })







@app.route('/api/global-heatmap', methods=['GET'])
def get_global_heatmap_data():
    print("\n====== /api/global-heatmap (PRODUCTS ONLY) CALLED ======")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT
            JSON_UNQUOTE(JSON_EXTRACT(p.seller_information, '$.ai_insights.location')) AS location,
            JSON_UNQUOTE(JSON_EXTRACT(p.seller_information, '$.name')) AS seller_name,

            COUNT(*) AS total_scrapes,

            AVG(
                CAST(
                    JSON_UNQUOTE(JSON_EXTRACT(p.analysis_results, '$.compliance_score'))
                    AS DECIMAL(5,2)
                )
            ) AS avg_compliance_score,

            MAX(p.created_at) AS last_activity,

            -- NEW: return all matched products
            JSON_ARRAYAGG(
                JSON_OBJECT(
                    'product_id', p.product_id,
                    'title', p.title,
                    'rating', p.rating,
                    'compliance_score',
                        CAST(
                            JSON_UNQUOTE(JSON_EXTRACT(p.analysis_results, '$.compliance_score'))
                            AS DECIMAL(5,2)
                        ),
                    'created_at', p.created_at
                )
            ) AS products

        FROM Products p
        WHERE JSON_EXTRACT(p.seller_information, '$.ai_insights.location') IS NOT NULL
        AND JSON_EXTRACT(p.seller_information, '$.ai_insights.location') != ''
        GROUP BY location, seller_name
        ORDER BY total_scrapes DESC
        LIMIT 1000;
    """

    print("\nExecuting SQL:\n", query)
    cursor.execute(query)
    rows = cursor.fetchall()

    print(f"\nGLOBAL returned {len(rows)} rows:")
    for r in rows:
        print(r)

    cursor.close()
    conn.close()

    return jsonify({
        'global_heatmap_data': rows,
        'total_locations': len(rows),
        'total_scrapes': sum(x['total_scrapes'] for x in rows)
    })

#==SEARCH PAGE EXTRACTION==

@app.route('/extract-links', methods=['POST'])
def extract_links():
    """
    Extract product links from Amazon search URL
    
    Request body:
    {
        "url": "https://www.amazon.in/s?k=cricket+bat",
        "num_links": 3  // optional, defaults to 3
    }
    
    Response:
    {
        "success": true,
        "data": [
            {
                "title": "Product Title",
                "url": "https://www.amazon.in/Product/dp/ASIN"
            }
        ],
        "count": 3
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: url'
            }), 400
        
        url = data['url']
        num_links = data.get('num_links', 3)
        
        # Validate URL
        if not url.startswith('http'):
            return jsonify({
                'success': False,
                'error': 'Invalid URL format'
            }), 400
        
        # Validate num_links
        if not isinstance(num_links, int) or num_links < 1 or num_links > 20:
            return jsonify({
                'success': False,
                'error': 'num_links must be an integer between 1 and 20'
            }), 400
        
        # Extract links
        results = search.extract_top_links_from_url(url, num_links)
        
        if not results:
            return jsonify({
                'success': False,
                'error': 'No products found or failed to fetch page'
            }), 404
        
        return jsonify({
            'success': True,
            'data': results,
            'count': len(results)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ====== Rewards =======

@app.route('/api/gifts', methods=['POST'])
def create_gift():
    """
    Insert a new gift into the gifts table.
    Authentication NOT required.
    """
    data = request.json

    gift_code = data.get('gift_code')
    gift_pin = data.get('gift_pin')
    partner = data.get('partner')
    value = data.get('value')   # NEW FIELD
    mt_tokens_required = data.get('mt_tokens_required')

    # Validate required fields
    if not gift_code or not gift_pin or not mt_tokens_required:
        return jsonify({'error': 'gift_code, gift_pin, mt_tokens_required are required'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor()

    try:
        query = """
            INSERT INTO gifts (gift_code, gift_pin, partner, value, mt_tokens_required)
            VALUES (%s, %s, %s, %s, %s)
        """

        cursor.execute(query, (gift_code, gift_pin, partner, value, mt_tokens_required))
        connection.commit()

        new_gift_id = cursor.lastrowid

        cursor.close()
        connection.close()

        return jsonify({
            'message': 'Gift created successfully',
            'gift_id': new_gift_id,
            'gift_code': gift_code,
            'gift_pin': gift_pin,
            'partner': partner,
            'value': value,
            'mt_tokens_required': mt_tokens_required
        }), 201

    except Exception as e:
        cursor.close()
        connection.close()
        return jsonify({'error': f'Failed to insert gift: {str(e)}'}), 500


@app.route('/api/gifts/redeem', methods=['POST'])
def redeem_gift():
    """
    Redeem a gift code for the logged-in user.
    Steps:
      1. Validate session & get user info
      2. Validate gift exists & is available
      3. Validate user has enough mt_tokens
      4. Deduct tokens
      5. Insert into gifts_redeemed
      6. Update gift status → 'Redeem'
    """
    # -----------------------------
    # AUTH CHECK
    # -----------------------------
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session.get('user_id')
    role = session.get('role')

    # Optional: Only customers can redeem
    if role != "customer":
        return jsonify({'error': 'Only customers can redeem gifts'}), 403

    data = request.json
    gift_id = data.get('gift_id')

    if not gift_id:
        return jsonify({'error': 'gift_id is required'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    try:
        # Begin transaction
        connection.start_transaction()

        # ------------------------------------------
        # 1. Fetch gift details
        # ------------------------------------------
        cursor.execute("SELECT * FROM gifts WHERE id = %s", (gift_id,))
        gift = cursor.fetchone()

        if not gift:
            return jsonify({'error': 'Gift not found'}), 404

        if gift['mt_tokens_required'] is None:
            return jsonify({'error': 'Gift has invalid token value'}), 400

        # ------------------------------------------
        # 2. Check if already redeemed
        # ------------------------------------------
        cursor.execute("""
            SELECT * FROM gifts_redeemed
            WHERE gift_id = %s AND user_id = %s
        """, (gift_id, user_id))
        already = cursor.fetchone()

        if already:
            return jsonify({'error': 'You already redeemed this gift'}), 409

        # ------------------------------------------
        # 3. Check user token balance
        # ------------------------------------------
        cursor.execute("SELECT mt_tokens FROM Users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        user_tokens = user['mt_tokens']
        required_tokens = gift['mt_tokens_required']

        if user_tokens < required_tokens:
            return jsonify({
                'error': 'Insufficient tokens',
                'required': required_tokens,
                'available': user_tokens
            }), 400

        # ------------------------------------------
        # 4. Deduct tokens
        # ------------------------------------------
        new_balance = user_tokens - required_tokens
        cursor.execute(
            "UPDATE Users SET mt_tokens = %s WHERE id = %s",
            (new_balance, user_id)
        )

        # ------------------------------------------
        # 5. Insert into gifts_redeemed
        # ------------------------------------------
        cursor.execute("""
            INSERT INTO gifts_redeemed (user_id, gift_id, status)
            VALUES (%s, %s, 'Redeem')
        """, (user_id, gift_id))

        redeemed_id = cursor.lastrowid

        # ------------------------------------------
        # 6. Update gift status → Redeem
        # ------------------------------------------
        cursor.execute(
        "UPDATE gifts_redeemed SET status = 'Redeem' WHERE gift_id = %s AND user_id = %s",
        (gift_id, user_id)
    )


        # Commit transaction
        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({
            'message': 'Gift redeemed successfully',
            'gift_id': gift_id,
            'redeemed_id': redeemed_id,
            'tokens_spent': required_tokens,
            'tokens_remaining': new_balance
        }), 200

    except Exception as e:
        connection.rollback()
        cursor.close()
        connection.close()
        return jsonify({'error': f'Redemption failed: {str(e)}'}), 500

@app.route('/api/gifts/list', methods=['GET'])
def list_all_gifts():
    """
    Public route → Show ALL gifts.
    No authentication required.
    """
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
                id,
                gift_code,
                gift_pin,
                partner,
                value,
                mt_tokens_required
            FROM gifts
            ORDER BY id DESC
        """)
        gifts = cursor.fetchall()

        cursor.close()
        connection.close()

        return jsonify({
            'message': 'All gifts fetched successfully',
            'total_gifts': len(gifts),
            'gifts': gifts
        }), 200

    except Exception as e:
        cursor.close()
        connection.close()
        return jsonify({'error': f'Failed to fetch gifts: {str(e)}'}), 500


@app.route('/api/gifts/my-redemptions', methods=['GET'])
def get_my_redemptions():
    """
    Show all gifts redeemed by the logged-in user.
    Authentication required.
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session.get('user_id')

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT 
                gr.id AS redemption_id,
                g.id AS gift_id,
                g.gift_code,
                g.gift_pin,
                g.partner,
                g.value,                   -- IMPORTANT NEW FIELD
                g.mt_tokens_required,
                gr.status                  -- Only if your table has it!
            FROM gifts_redeemed gr
            INNER JOIN gifts g ON gr.gift_id = g.id
            WHERE gr.user_id = %s
            ORDER BY gr.id DESC
        """

        cursor.execute(query, (user_id,))
        rows = cursor.fetchall()

        cursor.close()
        connection.close()

        return jsonify({
            'message': 'Redeemed gift list fetched successfully',
            'redemptions': rows,
            'count': len(rows)
        }), 200

    except Exception as e:
        cursor.close()
        connection.close()
        return jsonify({'error': f'Failed to fetch redemptions: {str(e)}'}), 500


@app.route('/api/gifts/add-tokens', methods=['POST'])
def add_mt_tokens():
    """
    Add MT tokens to the logged-in customer's account.
    Authentication required.
    """
    # -----------------------------
    # AUTH CHECK
    # -----------------------------
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session.get('user_id')
    role = session.get('role')

    # Only customers can increase their tokens (You can remove this rule if not needed)
    if role != "customer":
        return jsonify({'error': 'Only customers can add tokens'}), 403

    data = request.json
    tokens_to_add = data.get('mt_tokens')

    # Validation
    if tokens_to_add is None:
        return jsonify({'error': 'mt_tokens is required'}), 400

    if not isinstance(tokens_to_add, int) or tokens_to_add <= 0:
        return jsonify({'error': 'mt_tokens must be a positive integer'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    try:
        # Fetch current balance
        cursor.execute("SELECT mt_tokens FROM Users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        new_balance = user['mt_tokens'] + tokens_to_add

        # Update token balance
        cursor.execute(
            "UPDATE Users SET mt_tokens = %s WHERE id = %s",
            (new_balance, user_id)
        )

        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({
            'message': 'Tokens added successfully',
            'tokens_added': tokens_to_add,
            'new_token_balance': new_balance
        }), 200

    except Exception as e:
        connection.rollback()
        cursor.close()
        connection.close()
        return jsonify({'error': f'Failed to add tokens: {str(e)}'}), 500

@app.route('/api/gifts/token-balance', methods=['GET'])
def get_token_balance():
    """
    Get MT token balance for the logged-in user.
    Authentication required.
    """
    # -----------------------------
    # AUTH CHECK
    # -----------------------------
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session.get('user_id')

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("SELECT mt_tokens FROM Users WHERE id = %s", (user_id,))
        result = cursor.fetchone()

        cursor.close()
        connection.close()

        if not result:
            return jsonify({'error': 'User not found'}), 404

        return jsonify({
            'message': 'Token balance fetched successfully',
            'user_id': user_id,
            'mt_tokens': result['mt_tokens']
        }), 200

    except Exception as e:
        cursor.close()
        connection.close()
        return jsonify({'error': f'Failed to fetch token balance: {str(e)}'}), 500
    
@app.route('/api/seller/check-upload-text', methods=['POST'])
def check_seller_upload_text():
    """
    Analyze seller's product using raw text description from speech-to-text
    Accepts multipart form data with images, text description, actual weight, and actual dimensions
    """
    # Get category
    category = request.form.get('category', 'amazon')
    
    # Get raw text description (from speech-to-text)
    raw_text = request.form.get('description', '').strip()
    
    # Get seller-declared actual weight and dimensions
    actual_weight = request.form.get('actual_weight', '').strip()  # e.g., "250g" or "1.5kg"
    actual_dimensions = request.form.get('actual_dimensions', '').strip()  # e.g., "15x10x5 cm"
    
    if not raw_text:
        return jsonify({'error': 'Product description is required'}), 400
    
    # Get uploaded images
    image_files = request.files.getlist('images')
    image_blobs = []
    
    for img_file in image_files[:10]:  # Limit to 10 images
        try:
            image_blobs.append(img_file.read())
        except Exception as e:
            print(f"[WARNING] Failed to read image: {e}")
    
    if not image_blobs:
        return jsonify({'error': 'At least one image is required'}), 400
    
    print(f"[SELLER TEXT CHECK] Analyzing upload with {len(image_blobs)} images and text description ({len(raw_text)} chars)")
    print(f"[SELLER TEXT CHECK] Declared weight: {actual_weight}, Declared dimensions: {actual_dimensions}")
    
    try:
        feedback_report = compliance_copy.analyze_seller_upload_text(
            image_blobs, 
            raw_text, 
            category,
            actual_weight=actual_weight,
            actual_dimensions=actual_dimensions
        )
        
        if 'error' in feedback_report:
            return jsonify({'error': feedback_report['error']}), 500
        
        return jsonify({
            'message': 'Pre-upload compliance check complete (text-based)',
            'feedback': feedback_report
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Seller text upload check failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


# ==================== MAIN ====================

if __name__ == '__main__':
    print("[INFO] Starting Flask Amazon Scraper Backend with AI Compliance")
    print("[INFO] Make sure to:")
    print("       1. Update .env with your MySQL credentials")
    print("       2. Update .env with your GOOGLE_API_KEY")
    print("       3. Run database_schema.sql to create tables")
    print("       4. Install required packages:")
    print("          pip install langchain langchain-google-genai langchain-community sqlalchemy")
    print("\n[AI COMPLIANCE] Module loaded successfully")
    print("       - analyze_compliance(product_id)")
    print("       - analyze_seller_upload(images, data, category)")
    print("       - chatbot_agent(message)")
    app.run(host='0.0.0.0', port=5001)
