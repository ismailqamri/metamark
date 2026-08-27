#!/usr/bin/env python3
"""
AI-Powered Regulatory Compliance & Chatbot Module
Uses LangChain + Google Gemini 2.5 Flash for Indian Regulatory Compliance Analysis
Updated with Legal Metrology (Packaged Commodities) Rules, 2011 (as amended up to Dec 2024)
With QR code support: if a QR is detected, its link is extracted and declaration-related issues are ignored.
"""

import os
import json
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import mysql.connector
from mysql.connector import Error

# LangChain imports
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain_community.agent_toolkits import create_sql_agent
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages import AIMessage

# Google AI imports
import google.generativeai as genai

from dotenv import load_dotenv

load_dotenv()

# ==================== CONFIGURATION ====================

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
genai.configure(api_key=GOOGLE_API_KEY)

# Initialize LangChain LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.3,
    convert_system_message_to_human=True
)

# Initialize Gemini for multimodal tasks
multimodal_model = genai.GenerativeModel('gemini-2.5-flash')

# ==================== INDIAN REGULATORY CRITERIA ====================
# Based on Legal Metrology (Packaged Commodities) Rules, 2011 (as amended)

REGULATORY_RULES = {
    'food': {
        'critical': [
            {
                'name': 'FSSAI License Number',
                'description': 'Must display valid 14-digit FSSAI license number as per Food Safety and Standards Act 2006',
                'weight': -25,
                'regex': r'\b\d{14}\b',
                'keywords': ['FSSAI', 'Lic', 'License', 'food license']
            },
            {
                'name': 'Manufacturer/Packer/Importer Name & Address',
                'description': 'Rule 6(a): Must display complete name and address of manufacturer/packer/importer',
                'weight': -22,
                'keywords': ['manufacturer', 'mfg', 'packed by', 'marketed by', 'importer', 'address']
            },
            {
                'name': 'Net Quantity Declaration',
                'description': 'Rule 6(c) & 13: Must declare net quantity in standard metric units (g/kg or ml/L)',
                'weight': -20,
                'keywords': ['net weight', 'net qty', 'net quantity', 'ml', 'gm', 'g', 'kg', 'litre', 'L']
            },
            {
                'name': 'MRP (Maximum Retail Price)',
                'description': 'Rule 6(e): Must state "MRP Rs. XX.XX incl. of all taxes" in Indian currency',
                'weight': -20,
                'keywords': ['MRP', 'maximum retail price', 'max retail price', 'price', 'Rs', '₹', 'INR', 'incl. of all taxes']
            }
        ],
        'major': [
            {
                'name': 'Best Before/Expiry Date',
                'description': 'Rule 6(da): Must display "Best Before" or "Use By Date" with month, year, day',
                'weight': -15,
                'keywords': ['best before', 'expiry', 'use by', 'exp', 'BB', 'use by date']
            },
            {
                'name': 'Manufacturing Date',
                'description': 'Rule 6(d): Must mention month and year of manufacture',
                'weight': -12,
                'keywords': ['mfg date', 'manufactured', 'manufacturing date', 'mfg', 'date of manufacture', 'DOM']
            },
            {
                'name': 'Veg/Non-Veg Symbol',
                'description': 'Rule 6(8): Must display green dot (veg) or red/brown dot (non-veg) at top of principal display panel',
                'weight': -12,
                'keywords': ['vegetarian', 'non-vegetarian', 'veg', 'non-veg', 'green dot', 'brown dot', 'red dot']
            },
            {
                'name': 'Customer Care Contact',
                'description': 'Rule 6(2): Must provide telephone number and e-mail for consumer complaints',
                'weight': -10,
                'keywords': ['customer care', 'contact', 'helpline', 'email', 'phone', 'telephone', 'consumer complaint']
            },
            {
                'name': 'Nutritional Information',
                'description': 'Should display nutritional facts as per FSSAI requirements',
                'weight': -10,
                'keywords': ['nutrition', 'nutritional information', 'energy', 'protein', 'carbohydrates', 'fat', 'per 100g']
            }
        ],
        'minor': [
            {
                'name': 'Ingredients List',
                'description': 'Should list all ingredients in descending order by weight',
                'weight': -8,
                'keywords': ['ingredients', 'contains', 'composition']
            },
            {
                'name': 'Country of Origin',
                'description': 'Rule 6(a): Required for imported products',
                'weight': -6,
                'keywords': ['country of origin', 'made in', 'product of', 'imported', 'origin']
            },
            {
                'name': 'Allergen Information',
                'description': 'Should declare common allergens as per FSSAI',
                'weight': -5,
                'keywords': ['allergen', 'contains', 'may contain', 'traces', 'allergy']
            },
            {
                'name': 'Batch/Lot Number',
                'description': 'Should display batch or lot number for traceability',
                'weight': -4,
                'keywords': ['batch', 'lot', 'lot no', 'batch no', 'batch number']
            }
        ]
    },

    'skincare': {
        'critical': [
            {
                'name': 'Manufacturer/Packer/Importer Name & Address',
                'description': 'Rule 6(a): Must display complete name and address',
                'weight': -22,
                'keywords': ['manufacturer', 'mfg', 'made by', 'packed by', 'importer', 'address']
            },
            {
                'name': 'Net Quantity Declaration',
                'description': 'Rule 6(c) & 13: Must declare net quantity in metric units (g/kg or ml/L)',
                'weight': -20,
                'keywords': ['net', 'net quantity', 'net weight', 'ml', 'gm', 'g', 'kg', 'volume']
            },
            {
                'name': 'MRP (Maximum Retail Price)',
                'description': 'Rule 6(e): Must state "MRP Rs. XX.XX incl. of all taxes"',
                'weight': -20,
                'keywords': ['MRP', 'maximum retail price', 'max retail price', 'Rs', '₹', 'incl. of all taxes']
            },
            {
                'name': 'Ingredients List',
                'description': 'Rule 6(b): Must list all ingredients as per Drugs & Cosmetics Rules 1945',
                'weight': -18,
                'keywords': ['ingredients', 'composition', 'contains', 'active ingredients']
            }
        ],
        'major': [
            {
                'name': 'Manufacturing Date',
                'description': 'Rule 6(d): Must display month and year of manufacture',
                'weight': -12,
                'keywords': ['mfg', 'manufactured', 'mfg date', 'date of manufacture', 'DOM']
            },
            {
                'name': 'Expiry Date or PAO',
                'description': 'Rule 6(da): Must display expiry date or Period After Opening (PAO) symbol',
                'weight': -12,
                'keywords': ['exp', 'expiry', 'best before', 'pao', 'period after opening', 'use within']
            },
            {
                'name': 'Batch Number',
                'description': 'Should display batch/lot number for traceability',
                'weight': -10,
                'keywords': ['batch', 'lot', 'lot no', 'batch no', 'batch number']
            },
            {
                'name': 'Customer Care Contact',
                'description': 'Rule 6(2): Must provide telephone and e-mail for complaints',
                'weight': -8,
                'keywords': ['customer care', 'contact', 'helpline', 'email', 'phone', 'telephone']
            }
        ],
        'minor': [
            {
                'name': 'External Use Warning',
                'description': 'Should display "For External Use Only" for topical products',
                'weight': -6,
                'keywords': ['external use', 'not for internal use', 'topical', 'for external use only']
            },
            {
                'name': 'Veg/Non-Veg Symbol',
                'description': 'Rule 6(8): Non-veg products must show red/brown dot; veg products green dot',
                'weight': -6,
                'keywords': ['vegetarian', 'non-vegetarian', 'green dot', 'brown dot', 'red dot']
            },
            {
                'name': 'Country of Origin',
                'description': 'Rule 6(a): Required for imported products',
                'weight': -5,
                'keywords': ['country of origin', 'made in', 'product of', 'imported']
            },
            {
                'name': 'Usage Instructions',
                'description': 'Should provide directions for use',
                'weight': -4,
                'keywords': ['directions', 'how to use', 'usage', 'apply', 'instructions']
            }
        ]
    },

    'electric': {
        'critical': [
            {
                'name': 'BIS/ISI Certification Mark',
                'description': 'Rule (Special): Must display BIS certification mark for electrical products',
                'weight': -25,
                'keywords': ['BIS', 'ISI', 'IS', 'standard mark', 'certification', 'BIS mark']
            },
            {
                'name': 'Manufacturer/Packer/Importer Name & Address',
                'description': 'Rule 6(a): Must display complete name and address',
                'weight': -22,
                'keywords': ['manufacturer', 'mfg', 'made by', 'importer', 'address']
            },
            {
                'name': 'MRP (Maximum Retail Price)',
                'description': 'Rule 6(e): Must state "MRP Rs. XX.XX incl. of all taxes"',
                'weight': -20,
                'keywords': ['MRP', 'maximum retail price', 'max retail price', 'Rs', '₹', 'incl. of all taxes']
            },
            {
                'name': 'Voltage Rating',
                'description': 'Must display voltage rating for electrical safety',
                'weight': -18,
                'keywords': ['voltage', 'V', 'AC', 'DC', '230V', 'volt', '220V', '110V']
            }
        ],
        'major': [
            {
                'name': 'Power Rating',
                'description': 'Should display power consumption in watts',
                'weight': -12,
                'keywords': ['watt', 'W', 'power', 'kW', 'power consumption']
            },
            {
                'name': 'Safety Warnings',
                'description': 'Should display safety instructions and warnings',
                'weight': -10,
                'keywords': ['warning', 'caution', 'danger', 'electric shock', 'safety', 'do not']
            },
            {
                'name': 'Manufacturing Date',
                'description': 'Rule 6(d): Must mention month and year of manufacture',
                'weight': -10,
                'keywords': ['mfg date', 'manufactured', 'date of manufacture', 'DOM', 'mfg']
            },
            {
                'name': 'Customer Care Contact',
                'description': 'Rule 6(2): Must provide telephone and e-mail for complaints',
                'weight': -8,
                'keywords': ['customer care', 'contact', 'helpline', 'email', 'phone', 'service center']
            }
        ],
        'minor': [
            {
                'name': 'Model Number',
                'description': 'Should display model number for identification',
                'weight': -6,
                'keywords': ['model', 'model no', 'model number', 'serial', 'SKU']
            },
            {
                'name': 'Warranty Information',
                'description': 'Should mention warranty period',
                'weight': -5,
                'keywords': ['warranty', 'guarantee', 'year warranty', 'months warranty', 'warrantee']
            },
            {
                'name': 'Country of Origin',
                'description': 'Rule 6(a): Required for imported products',
                'weight': -5,
                'keywords': ['made in', 'product of', 'origin', 'manufactured in', 'country of origin']
            },
            {
                'name': 'Net Quantity/Dimensions',
                'description': 'Rule 6(c) & 6(f): Should mention relevant dimensions',
                'weight': -4,
                'keywords': ['dimensions', 'size', 'weight', 'net', 'quantity']
            }
        ]
    },

    'book': {
        'critical': [
            {
                'name': 'ISBN',
                'description': 'Must display ISBN (10 or 13 digit)',
                'weight': -20,
                'regex': r'ISBN[:\s]*(?:\d{10}|\d{13})',
                'keywords': ['ISBN']
            },
            {
                'name': 'MRP (Maximum Retail Price)',
                'description': 'Rule 6(e): Must state "MRP Rs. XX.XX incl. of all taxes"',
                'weight': -20,
                'keywords': ['MRP', 'price', 'maximum retail price', 'Rs', '₹', 'INR', 'incl. of all taxes']
            },
            {
                'name': 'Publisher Name & Address',
                'description': 'Rule 6(a): Must display publisher name and complete address',
                'weight': -18,
                'keywords': ['publisher', 'published by', 'publication', 'address']
            }
        ],
        'major': [
            {
                'name': 'Edition & Year of Publication',
                'description': 'Should mention edition and year of publication',
                'weight': -10,
                'keywords': ['edition', 'year', 'published', 'reprint', 'first edition']
            },
            {
                'name': 'Copyright Information',
                'description': 'Should display copyright notice',
                'weight': -8,
                'keywords': ['copyright', '©', 'all rights reserved', 'copyrighted']
            },
            {
                'name': 'Country of Origin',
                'description': 'Rule 6(a): Should mention country of printing/origin',
                'weight': -6,
                'keywords': ['printed in', 'made in', 'country of origin']
            }
        ],
        'minor': [
            {
                'name': 'Printer Details',
                'description': 'Should mention printer name and address',
                'weight': -5,
                'keywords': ['printed by', 'printer', 'printed at', 'press']
            },
            {
                'name': 'Net Quantity/Pages',
                'description': 'May mention number of pages or weight',
                'weight': -3,
                'keywords': ['pages', 'pp', 'weight', 'net']
            }
        ]
    },

    'amazon': {  # Default/General Product Category
        'critical': [
            {
                'name': 'Manufacturer/Packer/Importer Name & Address',
                'description': 'Rule 6(a): Must display complete name and address of manufacturer/packer/importer',
                'weight': -22,
                'keywords': ['manufacturer', 'mfg', 'packed by', 'made by', 'importer', 'address', 'marketed by']
            },
            {
                'name': 'Net Quantity Declaration',
                'description': 'Rule 6(c) & 13: Must declare net quantity in standard metric units',
                'weight': -20,
                'keywords': ['net', 'net quantity', 'net weight', 'quantity', 'weight', 'dimensions', 'size', 'ml', 'g', 'kg', 'L']
            },
            {
                'name': 'MRP (Maximum Retail Price)',
                'description': 'Rule 6(e): Must state "Maximum Retail Price Rs. XX.XX incl. of all taxes" in Indian currency',
                'weight': -20,
                'keywords': ['MRP', 'maximum retail price', 'max retail price', 'price', 'Rs', '₹', 'incl. of all taxes']
            },
            {
                'name': 'Product Description',
                'description': 'Rule 6(b): Must display common or generic name of commodity',
                'weight': -15,
                'keywords': ['product name', 'description', 'commodity', 'generic name']
            }
        ],
        'major': [
            {
                'name': 'Country of Origin',
                'description': 'Rule 6(a): Must mention country of origin/manufacture (mandatory for imported products)',
                'weight': -12,
                'keywords': ['made in', 'product of', 'origin', 'manufactured in', 'country of origin']
            },
            {
                'name': 'Manufacturing Date',
                'description': 'Rule 6(d): Must mention month and year of manufacture',
                'weight': -10,
                'keywords': ['mfg date', 'manufactured', 'date of manufacture', 'mfg', 'DOM']
            },
            {
                'name': 'Customer Care Contact',
                'description': 'Rule 6(2): Must provide name, telephone number, and e-mail address for consumer complaints',
                'weight': -10,
                'keywords': ['customer care', 'contact', 'helpline', 'email', 'phone', 'telephone', 'consumer complaint']
            }
        ],
        'minor': [
            {
                'name': 'Unit Sale Price',
                'description': 'Rule 6(g): Should display unit sale price (Rs. per kg/L/meter/piece) - Mandatory from 01.04.2022',
                'weight': -6,
                'keywords': ['unit price', 'price per', 'per kg', 'per litre', 'per meter', 'per piece']
            },
            {
                'name': 'Best Before Date',
                'description': 'Rule 6(da): Required if commodity may become unfit after period of time',
                'weight': -5,
                'keywords': ['best before', 'use by', 'expiry', 'exp', 'BB']
            },
            {
                'name': 'Batch/Lot Number',
                'description': 'Should display batch or lot number for traceability',
                'weight': -4,
                'keywords': ['batch', 'lot', 'lot no', 'batch no', 'batch number']
            },
            {
                'name': 'Barcode/QR Code',
                'description': 'Rule 6(4A): Barcode, GTIN, or QR code permitted for additional information',
                'weight': -3,
                'keywords': ['barcode', 'QR code', 'GTIN', 'e-code']
            }
        ]
    }
}

# ==================== DATABASE CONNECTION ====================

def get_db_connection():
    """Create and return a database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"[ERROR] Database connection failed: {e}")
        return None

# ==================== IMAGE OCR & VISUAL ANALYSIS ====================

def analyze_images_with_ocr(image_blobs: List[bytes], category: str) -> Dict[str, Any]:
    """
    Perform OCR and visual analysis on product images using Gemini Vision
    Returns extracted text and compliance findings based on Legal Metrology Rules 2011

    NEW RULE:
    - If a QR code is present and its link is detectable in the OCR text/symbols, extract it as qr_link.
    - Later logic will assume declarations are inside the QR and ignore declaration-related violations.
    """
    # Fix ERROR 3: Handle None category
    if not category:
        category = 'amazon'
    
    print(f"[OCR] Analyzing {len(image_blobs)} images for category: {category}")
    
    if not image_blobs:
        return {
            'extracted_text': '',
            'visual_findings': [],
            'symbols_found': [],
            'image_quality': 'no_images',
            'confidence_score': 0.0,
            'ocr_success': False,
            'qr_link': None,
            'error': 'No images provided'
        }
    
    # Get regulatory rules for this category
    rules = REGULATORY_RULES.get(category, REGULATORY_RULES['amazon'])
    all_rules = rules['critical'] + rules['major'] + rules['minor']
    
    # Prepare regulatory checklist for the AI
    checklist = "\n".join([
        f"- {rule['name']}: {rule['description']}"
        for rule in all_rules
    ])
    
    # Create prompt for multimodal analysis based on Legal Metrology Rules
    prompt = f"""You are an expert in Indian product regulatory compliance, specifically the Legal Metrology (Packaged Commodities) Rules, 2011 (as amended up to December 2024), for {category.upper()} products.

Analyze these product package images and perform the following tasks:

1. *OCR EXTRACTION*: Extract ALL visible text from the images, especially:
   - Manufacturer/Packer/Importer name and complete address
   - MRP (Maximum Retail Price) with "incl. of all taxes" declaration
   - Net quantity in metric units (g, kg, ml, L, cm, m, pieces)
   - Manufacturing date (month and year format)
   - Best before/expiry date (if applicable)
   - Product name/description
   - Customer care contact (phone and email)
   - Batch/lot numbers
   - Country of origin (for imported products)
   - Any certification marks (BIS, ISI, FSSAI)
   - Veg/non-veg symbols (green or red/brown dots)
   - Legal declarations and fine print
   - Barcode/QR code presence (if QR code is readable, also decode and include its URL/text in the extracted text)

2. *LEGAL METROLOGY COMPLIANCE CHECK*: Verify the following mandatory requirements for Indian {category.upper()} products:

{checklist}

3. *PRINCIPAL DISPLAY PANEL CHECK*: 
   - Check if declarations are on the principal display panel
   - Verify font size and legibility (Rule 7 & 9)
   - Check if numerals are in contrasting color
   - Verify proper spacing around quantity and MRP declarations
   - Check if language is Hindi (Devanagari) or English

4. *DETAILED FINDINGS*: For each requirement, report:
   - Status: PRESENT, MISSING, or UNCLEAR
   - Location: WHERE found (front label, back panel, side, top, bottom)
   - Exact text/value: What you extracted
   - Compliance: Does it meet Legal Metrology format requirements?
   - Quality issues: Blurry, partially visible, too small, unclear

5. *SYMBOLS & CERTIFICATION MARKS*: Specifically identify:
   - BIS/ISI certification marks
   - FSSAI logo and license number
   - Veg/Non-veg symbols (green/red/brown dots)
   - Warning symbols and safety marks
   - QR codes or barcodes (if a QR code is present and its target link/URL is visible or decodable, include that URL clearly)

6. *COMMON VIOLATIONS CHECK*:
   - Missing "incl. of all taxes" with MRP
   - Net quantity not in metric units
   - Missing manufacturer address
   - Missing manufacturing date
   - Declarations not on principal display panel
   - Illegible or too small font

Return your analysis in the following JSON format:
{{
    "extracted_text": "Complete OCR text from all visible areas of packaging...",
    "findings": [
        {{
            "requirement": "Requirement name",
            "status": "present" or "missing" or "unclear",
            "location": "front label / back panel / side / etc.",
            "extracted_value": "exact text/value found",
            "compliance_notes": "meets Legal Metrology format / missing mandatory phrase / etc.",
            "quality_issue": "clear / blurry / too small / partially visible / none"
        }}
    ],
    "symbols_found": ["list of certification marks and symbols identified (including QR if present, and any decoded URL)"],
    "image_quality": "excellent / good / fair / poor / very poor",
    "confidence_score": 0.0-1.0,
    "principal_display_panel_check": "all declarations present / some missing / not visible",
    "language_used": "Hindi / English / Both / Other"
}}

Be thorough and precise. This analysis will be used for Legal Metrology compliance grading per Indian law."""

    try:
        # Convert images to format Gemini expects
        image_parts = []
        for i, blob in enumerate(image_blobs[:5]):  # Limit to 5 images to avoid token limits
            try:
                image_parts.append({
                    'mime_type': 'image/jpeg',
                    'data': base64.b64encode(blob).decode('utf-8')
                })
            except Exception as e:
                print(f"[WARNING] Failed to encode image {i}: {e}")
                continue
        
        if not image_parts:
            print(f"[ERROR] No valid images to analyze")
            return {
                'extracted_text': '',
                'visual_findings': [],
                'symbols_found': [],
                'image_quality': 'encoding_failed',
                'confidence_score': 0.0,
                'ocr_success': False,
                'qr_link': None,
                'error': 'All images failed to encode'
            }
        
        # Generate content with multimodal model
        response = multimodal_model.generate_content([prompt] + image_parts)
        
        # Fix ERROR 2: Handle None or empty response
        if not response or not response.text:
            print(f"[WARNING] Gemini returned empty response")
            return {
                'extracted_text': 'Unable to extract text from images',
                'visual_findings': [],
                'symbols_found': [],
                'image_quality': 'poor',
                'confidence_score': 0.0,
                'ocr_success': False,
                'qr_link': None,
                'error': 'Empty response from AI model'
            }
        
        # Parse response
        response_text = response.text.strip()
        
        # Try to extract JSON from response
        if 'json' in response_text:
            try:
                json_start = response_text.index('json') + 7
                json_end = response_text.rindex('')
                response_text = response_text[json_start:json_end].strip()
            except ValueError:
                print(f"[WARNING] Failed to extract JSON markers")
        
        try:
            ocr_results = json.loads(response_text)
        except (json.JSONDecodeError, TypeError) as e:
            # Fix ERROR 2: Handle JSON parsing failures
            print(f"[WARNING] JSON parsing failed: {e}")
            # Fallback: treat as plain text
            ocr_results = {
                'extracted_text': response_text if response_text else 'No text extracted',
                'findings': [],
                'symbols_found': [],
                'image_quality': 'unknown',
                'confidence_score': 0.5
            }
        
        # --- QR LINK EXTRACTION LOGIC ---
        qr_link = None

        # 1) Try from symbols_found (AI may list QR + URL there)
        symbols = ocr_results.get('symbols_found', []) or []
        for sym in symbols:
            if isinstance(sym, str) and ("http://" in sym or "https://" in sym):
                qr_link = sym.strip()
                break

        # 2) Fallback: scan extracted_text for a URL-like pattern
        if not qr_link:
            text_for_qr = ocr_results.get('extracted_text', '') or ''
            url_match = re.search(r'(https?://[^\s"\'<>]+)', text_for_qr)
            if url_match:
                qr_link = url_match.group(1).strip()
        # --------------------------------

        print(f"[OCR] SUCCESS: Analysis complete. Confidence: {ocr_results.get('confidence_score', 0.5)}")
        
        return {
            'extracted_text': ocr_results.get('extracted_text', ''),
            'visual_findings': ocr_results.get('findings', []),
            'symbols_found': ocr_results.get('symbols_found', []),
            'image_quality': ocr_results.get('image_quality', 'unknown'),
            'confidence_score': ocr_results.get('confidence_score', 0.5),
            'ocr_success': True,
            'qr_link': qr_link
        }
        
    except Exception as e:
        print(f"[ERROR] OCR analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'extracted_text': '',
            'visual_findings': [],
            'symbols_found': [],
            'image_quality': 'error',
            'confidence_score': 0.0,
            'ocr_success': False,
            'qr_link': None,
            'error': str(e)
        }

# ==================== TEXT DATA ANALYSIS ====================

def analyze_product_data(product_data: Dict[str, Any], category: str) -> Dict[str, Any]:
    """
    Analyze product text data (title, description, specifications) for Legal Metrology compliance
    """
    # Fix ERROR 3: Handle None category
    if not category:
        category = 'amazon'
    
    print(f"[DATA ANALYSIS] Analyzing product data for category: {category}")
    
    # Compile all text data with safe defaults
    text_content = {
        'title': product_data.get('title', '') or '',
        'description': product_data.get('description', '') or '',
        'feature_bullets': product_data.get('feature_bullets', []) or [],
        'product_details': product_data.get('product_details', {}) or {},
        'specifications': product_data.get('specifications', {}) or {},
        'seller_info': product_data.get('seller_information', {}) or {}
    }
    
    # Get regulatory rules
    rules = REGULATORY_RULES.get(category, REGULATORY_RULES['amazon'])
    all_rules = rules['critical'] + rules['major'] + rules['minor']
    
    # Create comprehensive text for analysis - Fix ERROR 1: Handle list properly
    feature_text = ''
    if isinstance(text_content['feature_bullets'], list):
        feature_text = ' '.join(str(item) for item in text_content['feature_bullets'])
    elif isinstance(text_content['feature_bullets'], str):
        feature_text = text_content['feature_bullets']
    
    full_text = f"""
    Title: {text_content['title']}
    Description: {text_content['description']}
    Features: {feature_text}
    Specifications: {json.dumps(text_content['specifications'])}
    Product Details: {json.dumps(text_content['product_details'])}
    """
    
    # Create analysis prompt based on Legal Metrology Rules
    checklist = "\n".join([
        f"- {rule['name']}: {rule['description']} (Keywords: {', '.join(rule['keywords'])})"
        for rule in all_rules
    ])
    
    prompt = f"""You are an expert in Indian product regulatory compliance, specifically the Legal Metrology (Packaged Commodities) Rules, 2011 (as amended up to December 2024), for {category.upper()} products.

Analyze the following product listing data for compliance with Legal Metrology requirements:

PRODUCT DATA:
{full_text}

MANDATORY LEGAL METROLOGY REQUIREMENTS FOR {category.upper()} IN INDIA:
{checklist}

For each requirement, determine:
1. Is the information PRESENT, MISSING, or PARTIALLY PRESENT in the product listing data?
2. If present, what is the specific value/text that satisfies this requirement?
3. Does it meet Legal Metrology format requirements?
   - MRP must include "incl. of all taxes"
   - Net quantity must be in metric units (g, kg, ml, L)
   - Manufacturer address must be complete
   - Manufacturing date must show month and year
   - Customer contact must include phone and email
4. Is the information ADEQUATE and CLEAR for customers?

SPECIFIC CHECKS:
- Rule 6(e): MRP format check - Must say "Maximum Retail Price Rs. XX.XX incl. of all taxes"
- Rule 6(c) & 13: Net quantity in metric units only (no imperial units)
- Rule 6(a): Complete manufacturer/packer address required
- Rule 6(d): Manufacturing date in month-year format
- Rule 6(2): Customer care phone and email required
- Rule 6(b): Common/generic product name required
- Rule 18: Cannot exceed MRP declared on package

Return your analysis in JSON format:
{{
    "findings": [
        {{
            "requirement": "Requirement name",
            "status": "present" or "missing" or "partial",
            "found_in": "which field (title/description/specs/details)",
            "extracted_value": "the actual value found",
            "legal_metrology_format": "compliant" or "non-compliant" or "needs_verification",
            "format_issue": "specific format issue if non-compliant",
            "adequacy": "adequate" or "inadequate" or "unclear",
            "notes": "specific observations"
        }}
    ],
    "data_quality_score": 0.0-1.0,
    "missing_critical_info": ["list of critical missing items per Legal Metrology"],
    "format_violations": ["list of format issues like missing 'incl. of all taxes'"],
    "recommendations": ["specific Legal Metrology compliance suggestions"]
}}"""

    try:
        response = llm.invoke(prompt)
        
        # Fix ERROR 2: Handle None or empty response
        if not response or not hasattr(response, 'content') or not response.content:
            print(f"[WARNING] LLM returned empty response")
            return {
                'findings': [],
                'data_quality_score': 0.5,
                'missing_critical_info': ['Unable to analyze - AI returned no response'],
                'recommendations': ['Please try analyzing again']
            }
        
        response_text = response.content.strip()
        
        # Extract JSON
        if 'json' in response_text:
            try:
                json_start = response_text.index('json') + 7
                json_end = response_text.rindex('')
                response_text = response_text[json_start:json_end].strip()
            except ValueError:
                print(f"[WARNING] Failed to extract JSON markers")
        
        try:
            analysis_results = json.loads(response_text)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[WARNING] JSON parsing failed for data analysis: {e}")
            analysis_results = {
                'findings': [],
                'data_quality_score': 0.5,
                'missing_critical_info': ['Unable to parse analysis results'],
                'recommendations': ['Ensure product description contains all Legal Metrology required information']
            }
        
        print(f"[DATA ANALYSIS] SUCCESS: Complete. Quality Score: {analysis_results.get('data_quality_score', 0.5)}")
        
        return analysis_results
        
    except Exception as e:
        print(f"[ERROR] Data analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'findings': [],
            'data_quality_score': 0.0,
            'missing_critical_info': ['Analysis failed'],
            'recommendations': ['Please check product data and try again'],
            'error': str(e)
        }

# ==================== COMPLIANCE SCORING ====================

def calculate_compliance_score(ocr_results: Dict, data_analysis: Dict, category: str) -> Dict[str, Any]:
    """
    FIXED VERSION: Avoid double-penalizing same requirement
    Strategy: Check BOTH sources, penalize only ONCE per requirement
    Based on Legal Metrology (Packaged Commodities) Rules, 2011

    NEW QR RULE:
    - If a QR link is present (ocr_results['qr_link']), we assume it contains legal declarations.
    - All declaration-related requirements (MRP, net quantity, manufacturer/address, batch, dates, etc.)
      are NOT penalized even if missing from panel text.
    """
    print(f"[SCORING] Calculating compliance score for category: {category}")
    
    rules = REGULATORY_RULES.get(category, REGULATORY_RULES['amazon'])
    
    # If QR is present, declaration issues will be ignored (per your rule)
    qr_present = bool(ocr_results.get('qr_link'))

    # Requirements that are treated as "covered by QR"
    declaration_keywords = [
        'MRP',
        'Net Quantity',
        'Net Quantity Declaration',
        'Manufacturer',
        'Packer',
        'Importer',
        'Name & Address',
        'Address',
        'Batch',
        'Lot',
        'Best Before',
        'Expiry',
        'Manufacturing Date',
        'Best Before/Expiry Date',
        'Customer Care',
        'Nutritional Information',
        'Ingredients',
        'Country of Origin',
        'Unit Sale Price',
        'Barcode/QR Code'
    ]
    
    # Start with perfect score
    total_score = 100
    violations = []
    
    # Track which requirements we've already penalized
    penalized_requirements = set()
    
    # Get findings from both sources
    ocr_findings = {f.get('requirement', ''): f for f in ocr_results.get('visual_findings', [])}
    data_findings = {f.get('requirement', ''): f for f in data_analysis.get('findings', [])}
    
    # Check each rule requirement ONCE
    for severity in ['critical', 'major', 'minor']:
        for rule in rules[severity]:
            requirement_name = rule['name']
            
            # Skip if already processed
            if requirement_name in penalized_requirements:
                continue

            # If QR is present and this looks like a declaration requirement, skip penalties
            if qr_present:
                lower_req = requirement_name.lower()
                if any(k.lower() in lower_req for k in declaration_keywords):
                    penalized_requirements.add(requirement_name)
                    continue
            
            # Check both OCR and data analysis
            ocr_finding = ocr_findings.get(requirement_name)
            data_finding = data_findings.get(requirement_name)
            
            # Determine overall status (prioritize "present" if found in either source)
            is_present_in_ocr = ocr_finding and ocr_finding.get('status') == 'present'
            is_present_in_data = data_finding and data_finding.get('status') == 'present'
            is_adequate_in_data = data_finding and data_finding.get('adequacy') == 'adequate'
            
            is_unclear_in_ocr = ocr_finding and ocr_finding.get('status') == 'unclear'
            is_partial_in_data = data_finding and (data_finding.get('status') == 'partial' or data_finding.get('adequacy') == 'inadequate')
            
            # Decision logic: If found adequately in EITHER source, no penalty
            if is_present_in_ocr or (is_present_in_data and is_adequate_in_data):
                # Requirement satisfied - no penalty
                penalized_requirements.add(requirement_name)
                continue
            
            # If unclear/partial in either source, apply reduced penalty
            elif is_unclear_in_ocr or is_partial_in_data:
                penalty = rule['weight'] * 0.3  # Only 30% penalty for partial
                total_score += penalty
                violations.append({
                    'type': 'partial',
                    'severity': severity,
                    'requirement': requirement_name,
                    'penalty': penalty,
                    'description': f"{rule['description']} (partially visible/incomplete)",
                    'rule_reference': 'Legal Metrology Rules 2011'
                })
                penalized_requirements.add(requirement_name)
            
            # If missing in both sources, apply full penalty
            else:
                penalty = rule['weight']
                total_score += penalty
                violations.append({
                    'type': 'missing',
                    'severity': severity,
                    'requirement': requirement_name,
                    'penalty': penalty,
                    'description': rule['description'],
                    'rule_reference': 'Legal Metrology Rules 2011'
                })
                penalized_requirements.add(requirement_name)
    
    # Ensure score doesn't go below 0
    total_score = max(0, total_score)
    
    # MORE LENIENT GRADING SCALE
    if total_score >= 85:
        grade = 'A+'
    elif total_score >= 75:
        grade = 'A'
    elif total_score >= 65:
        grade = 'B+'
    elif total_score >= 55:
        grade = 'B'
    elif total_score >= 45:
        grade = 'C+'
    elif total_score >= 35:
        grade = 'C'
    elif total_score >= 25:
        grade = 'D'
    else:
        grade = 'F'
    
    # Count violations by severity
    critical_violations = [v for v in violations if v['severity'] == 'critical']
    major_violations = [v for v in violations if v['severity'] == 'major']
    minor_violations = [v for v in violations if v['severity'] == 'minor']
    
    print(f"[SCORING] SUCCESS: Final Score: {total_score:.1f}/100 | Grade: {grade}")
    print(f"[SCORING] Violations - Critical: {len(critical_violations)}, Major: {len(major_violations)}, Minor: {len(minor_violations)}")
    
    return {
        'score': round(total_score, 1),
        'grade': grade,
        'violations': violations,
        'violation_summary': {
            'critical': len(critical_violations),
            'major': len(major_violations),
            'minor': len(minor_violations),
            'total': len(violations)
        }
    }

# ==================== RECOMMENDATIONS GENERATOR ====================

def generate_recommendations(violations: List[Dict], ocr_results: Dict, data_analysis: Dict, category: str) -> List[str]:
    """
    Generate SMARTER recommendations based on Legal Metrology violation types.
    
    NEW RULE:
    - If QR link is present, declaration-related recommendations are removed since QR covers them.
    """
    if not category:
        category = 'amazon'
    
    recommendations = []
    qr_present = bool(ocr_results.get('qr_link'))

    # Declaration-type keywords (ignored if QR exists)
    declaration_keywords = [
        'MRP', 'Net Quantity', 'Manufacturer', 'Address', 'Batch', 'Expiry',
        'Best Before', 'Manufacturing Date', 'Customer Care', 'Ingredients',
        'Nutritional', 'Country of Origin', 'Unit Sale Price'
    ]

    # Separate violations by category
    missing_violations = [v for v in violations if v.get('type') == 'missing']
    partial_violations = [v for v in violations if v.get('type') == 'partial']

    # Filter out declaration violations if QR exists
    if qr_present:
        missing_violations = [
            v for v in missing_violations
            if not any(k.lower() in v["requirement"].lower() for k in declaration_keywords)
        ]
        partial_violations = [
            v for v in partial_violations
            if not any(k.lower() in v["requirement"].lower() for k in declaration_keywords)
        ]

    critical_missing = [v for v in missing_violations if v.get('severity') == 'critical']
    major_missing = [v for v in missing_violations if v.get('severity') == 'major']
    minor_missing = [v for v in missing_violations if v.get('severity') == 'minor']

    # If QR is present, note that declarations are assumed covered
    if qr_present:
        recommendations.append(
            f"📌 A QR code was detected and decoded: {ocr_results.get('qr_link')}\n"
            "All legal declarations are assumed to be included inside the QR, "
            "so declaration-related violations have been ignored."
        )

    # Critical actions
    if critical_missing:
        recommendations.append("🚨 CRITICAL ACTIONS REQUIRED:")
        for v in critical_missing:
            recommendations.append(f" • Add: {v['requirement']} ({v['description']})")

    # Major improvements
    if major_missing:
        recommendations.append("\nWARNING: IMPORTANT IMPROVEMENTS REQUIRED:")
        for v in major_missing:
            recommendations.append(f" • Add: {v['requirement']}")

    # Partial clarity items
    if partial_violations:
        recommendations.append("\n📋 IMPROVE CLARITY:")
        for v in partial_violations:
            recommendations.append(f" • Improve visibility: {v['requirement']}")

    # Minor suggestions
    if minor_missing:
        recommendations.append("\n💡 OPTIONAL BUT RECOMMENDED:")
        for v in minor_missing[:5]:
            recommendations.append(f" • Consider adding: {v['requirement']}")

    # Packaging display tips
    if len(ocr_results.get('visual_findings', [])) < 3:
        recommendations.append("\n📸 PACKAGING IMPROVEMENT TIPS:")
        recommendations.append(" • Ensure all declarations are on the principal display panel")
        recommendations.append(" • Improve clarity and lighting in images")
        recommendations.append(" • Use larger, contrasting fonts for declarations")

    # Legal Metrology reminders
    recommendations.append("\n📜 LEGAL METROLOGY REMINDERS:")
    recommendations.append(" • All declarations must be in Hindi or English (Rule 9)")
    recommendations.append(" • MRP cannot be exceeded (Rule 18)")
    recommendations.append(" • Only metric units allowed (Rule 13)")

    return recommendations if recommendations else ["SUCCESS: No major compliance issues found."]


# ==================== MAIN COMPLIANCE ANALYSIS FUNCTION ====================

def analyze_compliance(product_id: int) -> Dict[str, Any]:
    """
    Main function: Analyze product compliance from database.
    NEW RULE:
    - QR link included in final report.
    - Declaration issues ignored if QR present.
    """
    print(f"\n[COMPLIANCE ENGINE] Starting analysis for Product ID: {product_id}")

    connection = get_db_connection()
    if not connection:
        return {'error': 'Database connection failed'}

    cursor = connection.cursor(dictionary=True)

    try:
        # Fetch product data
        cursor.execute("SELECT * FROM Products WHERE product_id = %s", (product_id,))
        product = cursor.fetchone()

        if not product:
            return {'error': 'Product not found'}

        product_json = json.loads(product.get('product_json', '{}'))
        category = product_json.get('detected_category', 'amazon')

        # Fetch images
        cursor.execute("SELECT image_data FROM Images WHERE product_id = %s LIMIT 10", (product_id,))
        images = cursor.fetchall()
        image_blobs = [img['image_data'] for img in images]

        # Step 1: OCR + QR detection
        ocr_results = analyze_images_with_ocr(image_blobs, category)

        # Step 2: Data analysis
        raw_seller_info = product.get('seller_information') or "{}"
        try:
            seller_info = json.loads(raw_seller_info)
        except:
            seller_info = {}

        product_data = {
            'title': product.get('title'),
            'description': product_json.get('description'),
            'feature_bullets': product_json.get('feature_bullets'),
            'product_details': product_json.get('product_details'),
            'specifications': product_json.get('specifications'),
            'seller_information': seller_info
        }

        data_analysis = analyze_product_data(product_data, category)

        # Step 3: Compliance Score
        scoring = calculate_compliance_score(ocr_results, data_analysis, category)

        # Step 4: Recommendations
        recommendations = generate_recommendations(
            scoring['violations'],
            ocr_results,
            data_analysis,
            category
        )

        # Compile final report
        compliance_report = {
            'product_id': product_id,
            'asin': product.get('asin'),
            'title': product.get('title') or 'Untitled Product',
            'category': category,
            'analysis_date': datetime.now().isoformat(),
            'qr_link': ocr_results.get('qr_link'),  # <-- NEW FIELD
            'compliance_framework': 'Legal Metrology (Packaged Commodities) Rules, 2011',
            'compliance_score': scoring['score'],
            'compliance_grade': scoring['grade'],
            'violation_summary': scoring['violation_summary'],
            'violations': scoring['violations'],
            'ocr_analysis': {
                'success': ocr_results.get('ocr_success'),
                'extracted_text': ocr_results.get('extracted_text')[:500],
                'symbols_found': ocr_results.get('symbols_found'),
                'image_quality': ocr_results.get('image_quality'),
                'confidence': ocr_results.get('confidence_score'),
                'qr_link': ocr_results.get('qr_link')
            },
            'data_analysis': {
                'quality_score': data_analysis.get('data_quality_score'),
                'missing_critical_info': data_analysis.get('missing_critical_info')
            },
            'recommendations': recommendations,
            'is_compliant': scoring['score'] >= 70,
            'requires_action': scoring['violation_summary']['critical'] > 0
        }

        # Save results to DB
        try:
            cursor.execute("""
                UPDATE Products
                SET analysis_results = %s,
                    rating = %s,
                    remarks = %s,
                    last_analysed = %s
                WHERE product_id = %s
            """, (
                json.dumps(compliance_report),
                scoring['score'],
                f"Grade: {scoring['grade']} | Violations: {scoring['violation_summary']['total']}",
                datetime.now(),
                product_id
            ))
            connection.commit()
        except Error as e:
            print(f"[WARNING] Failed to save report: {e}")

        cursor.close()
        connection.close()

        return compliance_report

    except Exception as e:
        print(f"[ERROR] Compliance analysis failed: {e}")
        import traceback
        traceback.print_exc()

        try:
            cursor.close()
            connection.close()
        except:
            pass

        return {'error': str(e)}


# ==================== SELLER UPLOAD ANALYSIS ====================

def analyze_seller_upload(images: List[bytes], product_data: Dict[str, Any], category: str = 'amazon') -> Dict[str, Any]:
    """
    Analyze seller's product BEFORE uploading to Amazon.
    NEW RULE: QR detected → declaration issues ignored.
    """
    print(f"\n[SELLER UPLOAD CHECK] Analyzing upload for category: {category}")

    try:
        if not images:
            return {
                'error': 'No images provided',
                'compliance_score': 0,
                'compliance_grade': 'F',
                'ready_for_upload': False
            }

        safe_product_data = {
            'title': product_data.get('title', ''),
            'description': product_data.get('description', ''),
            'feature_bullets': product_data.get('feature_bullets', []),
            'product_details': product_data.get('product_details', {}),
            'specifications': product_data.get('specifications', {}),
            'seller_information': product_data.get('seller_information', {})
        }

        # OCR + QR detection
        ocr_results = analyze_images_with_ocr(images, category)

        # Data analysis
        data_analysis = analyze_product_data(safe_product_data, category)

        # Compliance scoring
        scoring = calculate_compliance_score(ocr_results, data_analysis, category)

        # Recommendations
        recommendations = generate_recommendations(
            scoring['violations'],
            ocr_results,
            data_analysis,
            category
        )

        # Final upload readiness report
        feedback_report = {
            'category': category,
            'analysis_date': datetime.now().isoformat(),
            'qr_link': ocr_results.get('qr_link'),
            'compliance_score': scoring['score'],
            'compliance_grade': scoring['grade'],
            'violation_summary': scoring['violation_summary'],
            'critical_issues': [v for v in scoring['violations'] if v['severity'] == 'critical'],
            'major_issues': [v for v in scoring['violations'] if v['severity'] == 'major'],
            'minor_issues': [v for v in scoring['violations'] if v['severity'] == 'minor'],
            'image_analysis': {
                'quality': ocr_results.get('image_quality'),
                'confidence': ocr_results.get('confidence_score'),
                'symbols_found': ocr_results.get('symbols_found'),
                'qr_link': ocr_results.get('qr_link')
            },
            'recommendations': recommendations,
            'ready_for_upload': scoring['score'] >= 70 and scoring['violation_summary']['critical'] == 0,
            'estimated_approval_chance': (
                'High' if scoring['score'] >= 85 else
                'Medium' if scoring['score'] >= 70 else
                'Low'
            )
        }

        return feedback_report

    except Exception as e:
        print(f"[ERROR] Seller upload analysis failed: {e}")
        import traceback
        traceback.print_exc()

        return {
            'error': str(e),
            'compliance_score': 0,
            'compliance_grade': 'F',
            'ready_for_upload': False
        }


# ==================== INTELLIGENT CHATBOT ====================

def create_db_agent():
    """Create SQL Agent with Legal Metrology expertise."""
    try:
        db_url = f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}/{DB_CONFIG['database']}"
        db = SQLDatabase.from_uri(db_url)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)

        system_message = """
        You are an intelligent assistant specializing in Legal Metrology (Packaged Commodities) Rules, 2011.
        You can query database products, provide explanations, and assist with compliance.
        """

        agent = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            agent_type="zero-shot-react-description",
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=5,
            prefix=system_message
        )

        return agent
    except Exception as e:
        print(f"[ERROR] Failed to create DB agent: {e}")
        return None


_db_agent = None

def chatbot_agent(user_message: str) -> str:
    """Chatbot with QR-aware compliance logic."""
    global _db_agent
    print(f"[CHATBOT] Message: {user_message}")

    irrelevant = ["sports", "cricket", "celeb", "movie", "weather", "news"]
    if any(k in user_message.lower() for k in irrelevant):
        return "I specialise in Legal Metrology compliance and Amazon product analysis."

    try:
        if _db_agent is None:
            _db_agent = create_db_agent()

        if _db_agent is None:
            resp = llm.invoke("Provide LM-compliance based answer:\n" + user_message)
            return resp.content
        
        result = _db_agent.invoke({"input": user_message})
        return result.get("output", "Error processing request.")

    except Exception as e:
        return f"Chatbot error: {str(e)}"


# ==================== BATCH ANALYSIS ====================

def batch_analyze_products(product_ids: List[int]) -> Dict[str, Any]:
    """Analyze multiple products."""
    results = []
    summary = {'total': len(product_ids), 'analyzed': 0, 'failed': 0, 'grades': {}, 'avg_score': 0}

    for pid in product_ids:
        try:
            rep = analyze_compliance(pid)
            if 'error' not in rep:
                results.append(rep)
                summary['analyzed'] += 1
                grade = rep['compliance_grade']
                summary['grades'][grade] = summary['grades'].get(grade, 0) + 1
                summary['avg_score'] += rep['compliance_score']
            else:
                summary['failed'] += 1
        except:
            summary['failed'] += 1

    if summary['analyzed']:
        summary['avg_score'] /= summary['analyzed']

    return {'summary': summary, 'results': results}


# ==================== EXPORTS ====================

_all_ = [
    'analyze_compliance',
    'analyze_seller_upload',
    'chatbot_agent',
    'batch_analyze_products',
    'REGULATORY_RULES'
]


if __name__ == '_main_':
    print("[AI COMPLIANCE MODULE] Ready.")
