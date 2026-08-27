#!/usr/bin/env python3
"""
Flask Backend for Amazon Product Scraper
Integrates AI Router, MySQL Database, and Multiple Scrapers
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
import amazon
import book
import electric
import food
import skincare



app = Flask(__name__)
app.secret_key = os.urandom(24)  # Simple session management
CORS(app)

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
        # DO NOT rollback the whole transaction
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
        # DO NOT rollback the whole transaction
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
    """Main scraping endpoint with database integration"""
    
    # Check authentication
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    user_id = session.get('user_id')
    user_role = session.get('role')
    
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Extract ASIN
    asin = extract_asin_from_url(url)
    if not asin:
        return jsonify({'error': 'Invalid Amazon URL'}), 400
    
    # Get customer's IP address for location tracking
    customer_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ',' in customer_ip:
        customer_ip = customer_ip.split(',')[0].strip()
    
    print(f"[SCRAPE] User {user_id} ({user_role}) scraping ASIN: {asin} from IP: {customer_ip}")
    
    # Step 1: AI Router - Scrape the product
    product_data = ai_router(url)
    
    if not product_data:
        return jsonify({'error': 'Failed to scrape product'}), 500
    
    # Step 2: Database operations
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Check if product exists and get its owner (seller)
        cursor.execute(
            "SELECT product_id, user_id as seller_id FROM Products WHERE asin = %s", 
            (asin,)
        )
        existing_product = cursor.fetchone()
        
        # Prepare core fields
        title = product_data.get('title')
        price = product_data.get('price')
        currency = product_data.get('currency')
        country = product_data.get('country')
        language = product_data.get('language')
        
        # Prepare JSON field (all other data)
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
            'reviews_count': product_data.get('reviews_count')
        }

        json_data['seller_information'] = product_data.get('seller')
        
        seller_id = None
        
        if existing_product:
            # UPDATE existing product
            product_id = existing_product['product_id']
            seller_id = existing_product['seller_id']
            print(f"[UPDATE] Updating existing product: {product_id}, owned by seller: {seller_id}")
            
            update_query = """
                UPDATE Products 
                SET url = %s, title = %s, price = %s, currency = %s, 
                    country = %s, language = %s, seller_information = %s, product_json = %s
                WHERE product_id = %s
            """
            cursor.execute(update_query, (
                url, title, price, currency, country, language,
                json.dumps(product_data.get('seller')),  # NEW
                json.dumps(json_data),
                product_id
            ))

            
            # Delete old images
            cursor.execute("DELETE FROM Images WHERE product_id = %s", (product_id,))
            print(f"[DELETE] Removed old images for product: {product_id}")
            
        else:
            # INSERT new product
            print(f"[INSERT] Creating new product entry")
            
            insert_query = """
                INSERT INTO Products 
                (user_id, url, asin, title, price, currency, country, language, seller_information, product_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                user_id, url, asin, title, price, currency, country, language, json.dumps(product_data.get('seller')),
                json.dumps(json_data)
            ))
            product_id = cursor.lastrowid
            seller_id = user_id  # The person who scraped it first is the seller
        
        connection.commit()
        
        # Step 3: Download and store images as BLOBs
        images = product_data.get('images', [])
        print(f"[IMAGES] Processing {len(images)} images")
        
        images_inserted = 0
        for img_url in images[:10]:  # Limit to 10 images to avoid overload
            image_data = download_image(img_url)
            if image_data:
                cursor.execute(
                    "INSERT INTO Images (product_id, image_data) VALUES (%s, %s)",
                    (product_id, image_data)
                )
                images_inserted += 1
        
        connection.commit()
        print(f"[SUCCESS] Stored {images_inserted} images")
        
        # Step 4: CRITICAL - Log activity based on who scraped
        if user_role == 'customer':
            print("customer block getting called")
            # A CUSTOMER scraped a SELLER's product
            # This is the key logging for heatmap generation
            log_customer_scrape_activity(json_data, seller_id, user_id, asin, customer_ip)
            activity_logged = "customer_scrape"
            
        elif user_role == 'seller' and seller_id == user_id:
            # A SELLER scraped their own product
            log_seller_own_activity(seller_id, f"Seller scraped own product ASIN {asin}", customer_ip)
            activity_logged = "seller_own_scrape"
            
        elif user_role == 'seller' and seller_id and seller_id != user_id:
            # A SELLER scraped another SELLER's product (treat as customer)
            log_customer_scrape_activity(json_data, seller_id, user_id, asin, customer_ip)
            activity_logged = "seller_viewing_competitor"
        else:
            activity_logged = "none"
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'message': 'Product scraped and stored successfully',
            'product_id': product_id,
            'asin': asin,
            'title': title,
            'images_stored': images_inserted,
            'is_update': existing_product is not None,
            'seller_id': seller_id,
            'seller_info': product_data.get('seller'),
            'activity_logged': activity_logged
        }), 200
        
    except Error as e:
        connection.rollback()
        cursor.close()
        connection.close()
        print(f"[ERROR] Database operation failed: {e}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500

# ==================== ADDITIONAL ENDPOINTS ====================

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
        "SELECT product_id, asin, title, price, currency, url FROM Products WHERE user_id = %s",
        (user_id,)
    )
    products = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    return jsonify({'products': products}), 200

@app.route('/api/product/<int:product_id>', methods=['GET'])
def get_product_detail(product_id):
    """Get detailed product information including images"""
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
    
    # Parse JSON field
    if product.get('product_json'):
        product['product_json'] = json.loads(product['product_json'])
    
    # Get image count (not the actual BLOBs to avoid heavy response)
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
    
    # Get all activity for this seller's products
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
    """
    Get geographic heatmap data for ALL users (customers and sellers).
    Shows where products are being scraped from globally.
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    user_id = session.get('user_id')
    user_role = session.get('role')
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    
    if user_role == 'seller':
        # SELLERS: See who's scraping THEIR products (where their customers are)
        query = """
            SELECT 
                sa.location,
                sa.latitude,
                sa.longitude,
                COUNT(*) as scrape_count,
                MAX(sa.timestamp) as last_scrape,
                COUNT(DISTINCT sa.customer_id) as unique_customers,
                p.title as product_title,
                p.asin
            FROM SellerActivity sa
            LEFT JOIN Products p ON p.user_id = sa.seller_id
            WHERE sa.seller_id = %s 
                AND sa.customer_id IS NOT NULL
                AND sa.latitude IS NOT NULL
                AND sa.longitude IS NOT NULL
            GROUP BY sa.location, sa.latitude, sa.longitude, p.title, p.asin
            ORDER BY scrape_count DESC
        """
        cursor.execute(query, (user_id,))
        
    else:
        # CUSTOMERS: See where THEY have been scraping from (their own activity locations)
        query = """
            SELECT 
                sa.location,
                sa.latitude,
                sa.longitude,
                COUNT(*) as scrape_count,
                MAX(sa.timestamp) as last_scrape,
                u.username as seller_name,
                'customer_activity' as activity_type
            FROM SellerActivity sa
            LEFT JOIN Users u ON sa.seller_id = u.id
            WHERE sa.customer_id = %s
                AND sa.latitude IS NOT NULL
                AND sa.longitude IS NOT NULL
            GROUP BY sa.location, sa.latitude, sa.longitude, u.username
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
        'total_scrapes': sum(d['scrape_count'] for d in heatmap_data),
        'description': 'Sellers see customer locations; Customers see their own activity locations'
    }), 200

@app.route('/api/global-heatmap', methods=['GET'])
def get_global_heatmap_data():
    """
    Get GLOBAL heatmap showing ALL scraping activity across the platform.
    Available to all authenticated users.
    """
    if not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = connection.cursor(dictionary=True)
    
    # Get all scraping activity globally
    query = """
        SELECT 
            location,
            latitude,
            longitude,
            COUNT(*) as total_scrapes,
            COUNT(DISTINCT customer_id) as unique_customers,
            COUNT(DISTINCT seller_id) as products_from_sellers,
            MAX(timestamp) as last_activity
        FROM SellerActivity
        WHERE latitude IS NOT NULL
            AND longitude IS NOT NULL
        GROUP BY location, latitude, longitude
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
        'total_scrapes': sum(d['total_scrapes'] for d in global_data),
        'description': 'Global view of all scraping activity on the platform'
    }), 200

# ==================== MAIN ====================

if __name__ == '__main__':
    print("[INFO] Starting Flask Amazon Scraper Backend")
    print("[INFO] Make sure to:")
    print("       1. Update DB_CONFIG with your MySQL credentials")
    print("       2. Update GOOGLE_API_KEY with your GCP API key")
    print("       3. Run database_schema.sql to create tables")
    app.run(debug=True, host='0.0.0.0', port=5000)
