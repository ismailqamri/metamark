#!/usr/bin/env python3
"""
Flask Backend for Amazon Product Scraper
Integrates AI Router, MySQL Database, Multiple Scrapers, and AI Compliance Module
"""

from flask import Flask, request, jsonify, session
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
import chatbot_compliance

# Import AI Compliance Module
import compliance
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
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{9,13})', url)
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

    data = request.json
    url = data.get('url')
    auto_analyze = data.get('auto_analyze', True)

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # ---------------------------------------------------
    # EXTRACT ASIN
    # ---------------------------------------------------
    asin = extract_asin_from_url(url)
    if not asin:
        return jsonify({'error': 'Invalid Amazon URL'}), 400

    # Get customer IP address
    customer_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ',' in customer_ip:
        customer_ip = customer_ip.split(',')[0].strip()

    print(f"[SCRAPE] User {user_id} ({user_role}) scraping ASIN: {asin} from IP: {customer_ip}")

    # ---------------------------------------------------
    # STEP 1 — AI ROUTER SCRAPER
    # ---------------------------------------------------
    product_data = ai_router(url)

    if not product_data:
        return jsonify({'error': 'Failed to scrape product'}), 500

    # ---------------------------------------------------
    # STEP 2 — DB CONNECTION
    # ---------------------------------------------------
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    try:
        # ---------------------------------------------------
        # CHECK IF PRODUCT EXISTS
        # ---------------------------------------------------
        cursor.execute("SELECT product_id, user_id AS seller_id FROM Products WHERE asin = %s", (asin,))
        existing_product = cursor.fetchone()

        # Core fields
        title = product_data.get('title')
        price = product_data.get('price')
        currency = product_data.get('currency')
        country = product_data.get('country')
        language = product_data.get('language')

        # Build product JSON
        json_data = {
            'description': product_data.get('description'),
            'feature_bullets': product_data.get('feature_bullets'),
            'about_author': product_data.get('about_author'),
            'product_details': product_data.get('product_details'),
            'specifications': product_data.get('specifications'),
            'technical_details': product_data.get('technical_details'),
            'important_information': product_data.get('important_information'),
            'availability': product_data.get('availability'),
            'shipping_details': product_data.get('shipping_details'),
            'detected_category': product_data.get('detected_category'),
            'rating': product_data.get('rating'),
            'reviews_count': product_data.get('reviews_count'),
            'seller_information': product_data.get('seller')
        }

        seller_id = None

        # ---------------------------------------------------
        # INSERT OR UPDATE PRODUCT
        # ---------------------------------------------------
        if existing_product:
            # UPDATE
            product_id = existing_product['product_id']
            seller_id = existing_product['seller_id']

            print(f"[UPDATE] Updating product {product_id} (seller: {seller_id})")

            update_query = """
                UPDATE Products
                SET url=%s, title=%s, price=%s, currency=%s, country=%s,
                    language=%s, seller_information=%s, product_json=%s
                WHERE product_id=%s
            """
            cursor.execute(update_query, (
                url, title, price, currency, country, language,
                json.dumps(product_data.get('seller')),
                json.dumps(json_data),
                product_id
            ))

            # Delete old images
            cursor.execute("DELETE FROM Images WHERE product_id = %s", (product_id,))
            print(f"[DELETE] Old images removed for {product_id}")

        else:
            # INSERT NEW PRODUCT
            print(f"[INSERT] Creating new product entry")

            insert_query = """
                INSERT INTO Products 
                (user_id, url, asin, title, price, currency, country, language, seller_information, product_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                user_id, url, asin, title, price, currency, country, language,
                json.dumps(product_data.get('seller')),
                json.dumps(json_data)
            ))

            product_id = cursor.lastrowid
            seller_id = user_id  # first scraper becomes owner

        connection.commit()

        # ---------------------------------------------------
        # STEP 3 — STORE IMAGES AS BLOBS
        # ---------------------------------------------------
        images = product_data.get('images', [])
        print(f"[IMAGES] Found {len(images)} images")

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

        # Determine seller_id & customer_id for logging
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
                compliance_report = compliance.analyze_compliance(product_id)
            except Exception as e:
                print(f"[AUTO-ANALYZE] FAILED: {e}")

        # ---------------------------------------------------
        # STEP 6 — RETRIEVE STORED IMAGES AS BASE64
        # ---------------------------------------------------
        import base64
        
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
            'images': image_blobs,  # ← NEW: Return all image blobs
            'is_update': existing_product is not None,
            'seller_id': seller_id,
            'seller_info': product_data.get('seller')
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
        return jsonify({'error': f'Database error: {str(e)}'}),500

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
        feedback_report = compliance.analyze_seller_upload(image_blobs, product_data, category)
        
        if 'error' in feedback_report:
            return jsonify({'error': feedback_report['error']}), 500
        
        return jsonify({
            'message': 'Pre-upload compliance check complete',
            'feedback': feedback_report
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Seller upload check failed: {e}")
        return jsonify({'error': str(e)}), 500

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
    
    # Get image count
    cursor.execute("SELECT COUNT(*) as count FROM Images WHERE product_id = %s", (product_id,))
    image_count = cursor.fetchone()['count']
    product['image_count'] = image_count
    
    cursor.close()
    connection.close()
    
    return jsonify({'product': product}), 200

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
    """Get geographic heatmap data using seller_information JSON"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    user_id = session.get('user_id')
    user_role = session.get('role')

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    if user_role == 'seller':
        # Customers scraping THIS seller's products
        query = """
            SELECT 
                sa.location,
                COUNT(*) AS scrape_count,
                MAX(sa.timestamp) AS last_scrape,
                COUNT(DISTINCT sa.customer_id) AS unique_customers,
                p.title AS product_title,
                p.asin
            FROM (
                SELECT 
                    JSON_UNQUOTE(JSON_EXTRACT(seller_information, '$.ai_insights.location')) AS location,
                    seller_id,
                    customer_id,
                    timestamp
                FROM SellerActivity
            ) AS sa
            LEFT JOIN Products p ON p.user_id = sa.seller_id
            WHERE sa.seller_id = %s
              AND sa.customer_id IS NOT NULL
              AND sa.location IS NOT NULL
              AND sa.location != ''
            GROUP BY sa.location, p.title, p.asin
            ORDER BY scrape_count DESC
        """
        cursor.execute(query, (user_id,))
    
    else:
        # Customer viewing their own scrape history
        query = """
            SELECT 
                sa.location,
                COUNT(*) AS scrape_count,
                MAX(sa.timestamp) AS last_scrape,
                u.username AS seller_name,
                'customer_activity' AS activity_type
            FROM (
                SELECT 
                    JSON_UNQUOTE(JSON_EXTRACT(seller_information, '$.ai_insights.location')) AS location,
                    seller_id,
                    customer_id,
                    timestamp
                FROM SellerActivity
            ) AS sa
            LEFT JOIN Users u ON sa.seller_id = u.id
            WHERE sa.customer_id = %s
              AND sa.location IS NOT NULL
              AND sa.location != ''
            GROUP BY sa.location, seller_name
            ORDER BY scrape_count DESC
        """
        cursor.execute(query, (user_id,))

    heatmap_data = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify({
        'user_role': user_role,
        'heatmap_data': heatmap_data,
        'total_locations': len(heatmap_data),
        'total_scrapes': sum(d['scrape_count'] for d in heatmap_data)
    }), 200



@app.route('/api/global-heatmap', methods=['GET'])
def get_global_heatmap_data():
    """Get GLOBAL heatmap using JSON seller_information"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT 
            sa.location,
            COUNT(*) AS total_scrapes,
            COUNT(DISTINCT sa.customer_id) AS unique_customers,
            COUNT(DISTINCT sa.seller_id) AS products_from_sellers,
            MAX(sa.timestamp) AS last_activity
        FROM (
            SELECT 
                JSON_UNQUOTE(JSON_EXTRACT(seller_information, '$.ai_insights.location')) AS location,
                seller_id,
                customer_id,
                timestamp
            FROM SellerActivity
        ) AS sa
        WHERE sa.location IS NOT NULL
          AND sa.location != ''
        GROUP BY sa.location
        ORDER BY total_scrapes DESC
        LIMIT 1000
    """

    cursor.execute(query)
    global_data = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify({
        'global_heatmap_data': global_data,
        'total_locations': len(global_data),
        'total_scrapes': sum(d['total_scrapes'] for d in global_data)
    }), 200



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
    app.run(debug=True, host='0.0.0.0', port=5000)
