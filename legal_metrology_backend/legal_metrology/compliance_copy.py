#!/usr/bin/env python3

"""
AI-Powered Regulatory Compliance & Chatbot Module
Uses LangChain + Google Gemini 2.5 Flash for Indian Regulatory Compliance Analysis
"""

import os
import json
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime
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

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from langchain_core._api.deprecation import LangChainDeprecationWarning
warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)

LOG_BUFFER = []

def log(msg):
    global LOG_BUFFER
    LOG_BUFFER.append(msg)
    print(msg)

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
    request_timeout=120,
    temperature=0.3,
    convert_system_message_to_human=True
)

# Initialize Gemini for multimodal tasks
multimodal_model = genai.GenerativeModel('gemini-2.5-flash')

# ==================== UNIVERSAL LEGAL METROLOGY RULES ====================
# Universal rules based on Legal Metrology (Packaged Commodities) Rules, 2011
LEGAL_METROLOGY_RULES = {
    "high_priority": [
        {
            "name": "MRP (Maximum Retail Price)",
            "description": "Retail sale price in Indian currency (inclusive of all taxes)",
            "keywords": ["mrp", "price", "₹", "rs", "rupees", "inr"],
            "check_in": ["both"],  # both data and images
        },
        {
            "name": "Country of Origin",
            "description": "Country where the product was manufactured or imported from",
            "keywords": ["country", "origin", "made in", "imported", "india"],
            "check_in": ["both"],
        },
        {
            "name": "Manufacturer/Packer/Importer Name and Address",
            "description": "Complete name and address of manufacturer, packer, or importer (context-dependent)",
            "keywords": ["manufacturer", "packer", "importer", "address", "manufactured by", "packed by", "imported by"],
            "check_in": ["both"],
        },
        {
            "name": "Consumer Care/Contact Information",
            "description": "Consumer care number, email, or any contact information",
            "keywords": ["customer care", "consumer care", "contact", "phone", "email", "helpline"],
            "check_in": ["images"],  # Must be printed on package
        },
        {
            "name": "Net Quantity",
            "description": "Net quantity in standard units (weight, measure, or number of items)",
            "keywords": ["net quantity", "net wt", "weight", "volume", "ml", "gm", "kg", "litre", "pcs", "pieces"],
            "check_in": ["both"],
        },
    ],
    "low_priority": [
        {
            "name": "Unit Price",
            "description": "Price per unit (e.g., per gram, per ml)",
            "keywords": ["unit price", "per gram", "per ml", "per kg", "/gram", "/ml"],
            "check_in": ["both"],
        },
        {
            "name": "Manufacturing/Expiry/Best Before Date",
            "description": "Manufacturing date, expiry date, best before date, or shelf life",
            "keywords": ["mfg", "exp", "expiry", "best before", "use by", "shelf life", "manufacture date"],
            "check_in": ["both"],
        },
        {
            "name": "Product Dimensions/Size",
            "description": "Dimensions or size of the commodity if relevant",
            "keywords": ["size", "dimensions", "length", "width", "height", "diameter"],
            "check_in": ["both"],
        },
    ],
    "common_name": {
        "name": "Common/Generic Name",
        "description": "Common or generic name of the commodity",
        "keywords": ["product name", "commodity", "generic name"],
        "check_in": ["both"],
    }
}

# # Category-specific additional rules (optional enhancements beyond Legal Metrology)
# CATEGORY_SPECIFIC_RULES = {
#     'food': {
#         'high_priority': [
#             {
#                 'name': 'FSSAI License Number',
#                 'description': 'Must display valid 14-digit FSSAI license number',
#                 'regex': r'\b\d{14}\b',
#                 'keywords': ['FSSAI', 'Lic', 'License'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Expiry/Best Before Date',
#                 'description': 'Must clearly mention expiry date or best before date',
#                 'keywords': ['expiry', 'best before', 'use by', 'exp'],
#                 'check_in': ['both']
#             }
#         ],
#         'low_priority': [
#             {
#                 'name': 'Veg/Non-Veg Symbol',
#                 'description': 'Should display green dot (veg) or brown dot (non-veg)',
#                 'keywords': ['vegetarian', 'non-vegetarian', 'veg', 'dot'],
#                 'check_in': ['images']
#             },
#             {
#                 'name': 'Nutritional Information',
#                 'description': 'Should display nutritional facts',
#                 'keywords': ['nutrition', 'energy', 'protein', 'carbohydrates', 'fat'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Ingredients List',
#                 'description': 'Should list all ingredients',
#                 'keywords': ['ingredients', 'contains'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Allergen Information',
#                 'description': 'Should declare common allergens',
#                 'keywords': ['allergen', 'contains', 'may contain', 'traces'],
#                 'check_in': ['both']
#             }
#         ]
#     },
#     'skincare': {
#         'high_priority': [
#             {
#                 'name': 'Ingredients List',
#                 'description': 'Must list all ingredients',
#                 'keywords': ['ingredients', 'composition', 'contains'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Expiry Date',
#                 'description': 'Must display expiry date or PAO',
#                 'keywords': ['exp', 'expiry', 'best before', 'pao'],
#                 'check_in': ['both']
#             }
#         ],
#         'low_priority': [
#             {
#                 'name': 'Manufacturing Date',
#                 'description': 'Should display manufacturing date',
#                 'keywords': ['mfg', 'manufactured', 'mfg date', 'dom'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Batch Number',
#                 'description': 'Should display batch/lot number',
#                 'keywords': ['batch', 'lot', 'lot no', 'batch no'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'External Use Warning',
#                 'description': 'Should display "For External Use Only"',
#                 'keywords': ['external use', 'not for internal use', 'topical'],
#                 'check_in': ['images']
#             },
#             {
#                 'name': 'Usage Instructions',
#                 'description': 'Should provide directions',
#                 'keywords': ['directions', 'how to use', 'usage', 'apply'],
#                 'check_in': ['both']
#             }
#         ]
#     },
#     'electric': {
#         'high_priority': [
#             {
#                 'name': 'BIS/ISI Mark',
#                 'description': 'Must display BIS certification mark',
#                 'keywords': ['BIS', 'ISI', 'IS', 'standard mark', 'certification'],
#                 'check_in': ['images']
#             },
#             {
#                 'name': 'Voltage Rating',
#                 'description': 'Must display voltage rating',
#                 'keywords': ['voltage', 'V', 'AC', 'DC', '230V', 'volt'],
#                 'check_in': ['both']
#             }
#         ],
#         'low_priority': [
#             {
#                 'name': 'Power Rating',
#                 'description': 'Should display power in watts',
#                 'keywords': ['watt', 'W', 'power', 'kW'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Safety Warnings',
#                 'description': 'Should display safety instructions',
#                 'keywords': ['warning', 'caution', 'danger', 'electric shock', 'safety'],
#                 'check_in': ['images']
#             },
#             {
#                 'name': 'Model Number',
#                 'description': 'Should display model number',
#                 'keywords': ['model', 'model no', 'serial', 'SKU'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Warranty Information',
#                 'description': 'Should mention warranty',
#                 'keywords': ['warranty', 'guarantee', 'year warranty', 'months warranty'],
#                 'check_in': ['both']
#             }
#         ]
#     },
#     'book': {
#         'high_priority': [
#             {
#                 'name': 'ISBN',
#                 'description': 'Must display ISBN',
#                 'regex': r'ISBN[:\s]*(?:\d{10}|\d{13})',
#                 'keywords': ['ISBN'],
#                 'check_in': ['both']
#             }
#         ],
#         'low_priority': [
#             {
#                 'name': 'Publisher Details',
#                 'description': 'Should display publisher info',
#                 'keywords': ['publisher', 'published by', 'publication'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Edition & Year',
#                 'description': 'Should mention edition and year',
#                 'keywords': ['edition', 'year', 'published', 'reprint'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Copyright Information',
#                 'description': 'Should display copyright',
#                 'keywords': ['copyright', '©', 'all rights reserved'],
#                 'check_in': ['both']
#             },
#             {
#                 'name': 'Printer Details',
#                 'description': 'Should mention printer',
#                 'keywords': ['printed by', 'printer', 'printed at'],
#                 'check_in': ['both']
#             }
#         ]
#     }
# }

# ==================== DATABASE CONNECTION ====================
def get_db_connection():
    """Create and return a database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        log(f"[ERROR] Database connection failed: {e}")
        return None

# ==================== IMPROVED IMAGE OCR & VISUAL ANALYSIS ====================
def analyze_images_with_ocr(image_blobs: List[bytes], category: str) -> Dict[str, Any]:
    """
    IMPROVED: More aggressive OCR extraction with better prompting for Legal Metrology Rules
    """
    if not category:
        category = "amazon"
    
    log(f"[OCR] Analyzing {len(image_blobs)} images for category: {category}")
    
    if not image_blobs:
        return {
            "extracted_text": "",
            "visual_findings": [],
            "symbols_found": [],
            "image_quality": "no_images",
            "confidence_score": 0.0,
            "ocr_success": False,
            "error": "No images provided"
        }
    
    # Build comprehensive rules list (Universal + Category-specific)
    universal_high = LEGAL_METROLOGY_RULES["high_priority"]
    universal_low = LEGAL_METROLOGY_RULES["low_priority"]
    common_name = [LEGAL_METROLOGY_RULES["common_name"]]
    
    # category_rules = CATEGORY_SPECIFIC_RULES.get(category.lower(), {'high_priority': [], 'low_priority': []})
    # category_high = category_rules.get('high_priority', [])
    # category_low = category_rules.get('low_priority', [])
    
    all_high_rules = universal_high #+ category_high
    all_low_rules = universal_low #+ category_low
    all_rules = all_high_rules + all_low_rules + common_name
    
    checklist = "\n".join(
        [f"- {rule['name']}: {rule.get('description', '')}" for rule in all_rules]
    )
    
    # IMPROVED PROMPT - More explicit about comprehensive extraction
    prompt = f"""You are an OCR expert analyzing product packaging for Indian regulatory compliance based on Legal Metrology (Packaged Commodities) Rules, 2011.

TASK 1: COMPREHENSIVE OCR EXTRACTION
Extract EVERY piece of text visible in these images. This includes:
- Product names, brand names, taglines
- ALL numbers (prices, barcodes, batch numbers, dates, phone numbers, pin codes)
- Manufacturer/packer/importer names and COMPLETE addresses
- Licenses, certifications, registration numbers
- Ingredient lists, nutritional information
- Warnings, instructions, usage directions
- ANY text in fine print, even if partially visible
- Text on stickers, labels, tags, and packaging
- Text in multiple languages

**DO NOT summarize or skip anything. Extract the COMPLETE text verbatim.**

TASK 2: REGULATORY COMPLIANCE CHECK for {category.upper()}
Check for these specific requirements:
{checklist}

TASK 3: DETAILED ANALYSIS
For EACH requirement above, report:
- **Status**: "present" (clearly visible), "partial" (exists but unclear/incomplete), "missing" (not found)
- **Location**: Exactly where found (e.g., "front label top-right", "back panel center", "side tag")
- **Extracted Value**: The EXACT text/number you found (copy it verbatim, don't paraphrase)
- **Quality Notes**: Any visibility issues (blurry, cut-off, small text, etc.)

🚨 CRITICAL RULES FOR MRP (Maximum Retail Price) - READ CAREFULLY:

MRP STATUS MUST BE DETERMINED AS FOLLOWS:

✅ Status = "present" ONLY IF you can see:
   - The currency symbol (₹ or Rs.) AND
   - The actual numeric price value (e.g., 499, 1299, 2500.00)
   - Examples of VALID MRP that should be marked "present":
     * "MRP: ₹499"
     * "Rs. 1,299 (Incl. of all taxes)"
     * "₹2500.00"
     * "Maximum Retail Price: Rs. 799/-"

❌ Status = "missing" IF you see:
   - Only "MRP:" without a price number
   - Only "₹" or "Rs." without a number
   - "MRP: ₹ (Inclusive of all taxes)" - NO NUMBER = MISSING
   - "Price varies" or "See website for price"
   - Blurry/unclear numbers that you cannot read
   - Examples that MUST be marked "missing":
     * "MRP: ₹"
     * "MRP: ₹ (Inclusive of all taxes)"
     * "Price: Rs."
     * "Maximum Retail Price: [blank]"

WARNING:️ Status = "partial" is NOT ALLOWED for MRP
   - For MRP, use ONLY "present" or "missing"
   - If you can see some digits but not all (e.g., "₹4__" where __ is unclear), mark as "missing"

**EXAMPLES FOR MRP:**

Example 1 (CORRECT):
Image shows: "MRP: ₹499 (Incl. of all taxes)"
Your response:
{{
  "requirement": "MRP (Maximum Retail Price)",
  "status": "present",
  "location": "back label top",
  "extracted_value": "MRP: ₹499 (Incl. of all taxes)",
  "notes": "Clear and complete"
}}

Example 2 (CORRECT):
Image shows: "MRP: ₹ (Inclusive of all taxes)" with no visible number
Your response:
{{
  "requirement": "MRP (Maximum Retail Price)",
  "status": "missing",
  "location": "back label",
  "extracted_value": "MRP: ₹ (Inclusive of all taxes)",
  "notes": "Label present but numeric price value is missing"
}}

Example 3 (CORRECT):
Image shows: "Rs. 1,299/-"
Your response:
{{
  "requirement": "MRP (Maximum Retail Price)",
  "status": "present",
  "location": "price sticker",
  "extracted_value": "Rs. 1,299/-",
  "notes": "Clear price visible"
}}

Example 4 (CORRECT):
Image shows: "Maximum Retail Price:" with blank space after
Your response:
{{
  "requirement": "MRP (Maximum Retail Price)",
  "status": "missing",
  "location": "front panel",
  "extracted_value": "Maximum Retail Price:",
  "notes": "Label present but price value not filled in"
}}

IMPORTANT RULES FOR ALL REQUIREMENTS:
1. Mark as "present" ONLY if the requirement is clearly and completely fulfilled
2. Mark as "partial" if information exists but is incomplete, unclear, or low quality
3. Mark as "missing" if you cannot find it anywhere in the images
4. **For MRP specifically: NEVER use "partial" - only "present" (with numeric value) or "missing" (without numeric value)**
5. For text extraction, capture EVERYTHING - don't leave out details
6. For addresses, capture the COMPLETE address including street, city, state, pincode
7. For prices, look for "MRP", "Price", "Rs.", "₹" symbols **with numeric values**
8. For manufacturer info, look for "Mfd. by", "Packed by", "Marketed by", "Imported by"

Return STRICT JSON format (no markdown, no code blocks):
{{
  "extracted_text": "Complete verbatim text from ALL images, preserving line breaks and structure...",
  "findings": [
    {{
      "requirement": "Exact requirement name",
      "status": "present|partial|missing",
      "location": "specific location in image",
      "extracted_value": "EXACT text found (verbatim copy)",
      "notes": "quality/visibility issues if any"
    }}
  ],
  "symbols_found": ["list all certification marks, logos, symbols identified"],
  "image_quality": "excellent|good|fair|poor - overall assessment",
  "confidence_score": 0.95
}}"""

    try:
        # IMPROVED: Process ALL images, not just first 5
        image_parts: List[Any] = []
        for i, blob in enumerate(image_blobs[:10]):  # Increased to 10 images
            try:
                image_parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(blob).decode("utf-8")
                    }
                })
            except Exception as e:
                log(f"[WARNING] Failed to encode image {i}: {e}")
                continue
        
        if not image_parts:
            return {
                "extracted_text": "",
                "visual_findings": [],
                "symbols_found": [],
                "image_quality": "encoding_failed",
                "confidence_score": 0.0,
                "ocr_success": False,
                "error": "All images failed to encode"
            }
        
        # Call Gemini with improved configuration
        generation_config = genai.types.GenerationConfig(
            temperature=0.1,  # Low temperature for consistent extraction
            top_p=0.95,
            top_k=40
        )
        
        response = multimodal_model.generate_content(
            [prompt] + image_parts,
            generation_config=generation_config
        )
        
        if not response or not getattr(response, "text", None):
            log("[WARNING] Gemini returned empty response")
            return {
                "extracted_text": "Unable to extract text from images",
                "visual_findings": [],
                "symbols_found": [],
                "image_quality": "poor",
                "confidence_score": 0.0,
                "ocr_success": False,
                "error": "Empty response from AI model"
            }
        
        response_text = response.text.strip()
        response_text = _strip_json_fence(response_text)
        
        try:
            ocr_results = json.loads(response_text)
        except (json.JSONDecodeError, TypeError) as e:
            log(f"[WARNING] JSON parsing failed, attempting to extract text directly")
            # Fallback: treat entire response as extracted text
            ocr_results = {
                "extracted_text": response_text if response_text else "No text extracted",
                "findings": [],
                "symbols_found": [],
                "image_quality": "unknown",
                "confidence_score": 0.3
            }
        
        log(f"[OCR] SUCCESS: Extracted {len(ocr_results.get('extracted_text', ''))} characters")
        log(f"[OCR] Found {len(ocr_results.get('findings', []))} compliance items")
        
        return {
            "extracted_text": ocr_results.get("extracted_text", ""),
            "visual_findings": ocr_results.get("findings", []),
            "symbols_found": ocr_results.get("symbols_found", []),
            "image_quality": ocr_results.get("image_quality", "unknown"),
            "confidence_score": ocr_results.get("confidence_score", 0.5),
            "ocr_success": True
        }
    
    except Exception as e:
        log(f"[ERROR] OCR analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "extracted_text": "",
            "visual_findings": [],
            "symbols_found": [],
            "image_quality": "error",
            "confidence_score": 0.0,
            "ocr_success": False,
            "error": str(e)
        }

def _strip_json_fence(text: str) -> str:
    """
    Remove markdown JSON code fences if present.
    """
    if not text:
        return text

    text = text.strip()
    
    # Remove ```json fence
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    
    # Remove trailing fence
    if text.endswith("```"):
        text = text[:-3]
    
    return text.strip()

# ==================== TEXT DATA ANALYSIS ====================
def analyze_product_data(product_data: Dict[str, Any], category: str) -> Dict[str, Any]:
    """
    COMPREHENSIVE VERSION: Flattens entire JSON and searches everywhere for Legal Metrology compliance.
    """
    if not category:
        category = "amazon"
    
    log(f"[DATA ANALYSIS] Analyzing product data for category: {category}")
    
    # Recursively flatten the entire product data structure
    def flatten_dict(d: Any, parent_key: str = '', sep: str = ' > ') -> Dict[str, str]:
        """
        Recursively flatten nested dictionaries and lists into key-value pairs.
        """
        items = {}
        if isinstance(d, dict):
            for k, v in d.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, dict):
                    items.update(flatten_dict(v, new_key, sep=sep))
                elif isinstance(v, list):
                    # Handle lists
                    for i, item in enumerate(v):
                        if isinstance(item, (dict, list)):
                            items.update(flatten_dict(item, f"{new_key}[{i}]", sep=sep))
                        else:
                            items[f"{new_key}[{i}]"] = str(item)
                else:
                    # Leaf value
                    if v is not None:
                        items[new_key] = str(v)
        elif isinstance(d, list):
            for i, item in enumerate(d):
                if isinstance(item, (dict, list)):
                    items.update(flatten_dict(item, f"{parent_key}[{i}]", sep=sep))
                else:
                    items[f"{parent_key}[{i}]"] = str(item)
        else:
            if d is not None:
                items[parent_key] = str(d)
        
        return items
    
    # Flatten entire product data
    flattened = flatten_dict(product_data)
    
    # Create a comprehensive text dump of ALL data
    full_text_lines = []
    for key, value in flattened.items():
        if value and len(value.strip()) > 0:
            full_text_lines.append(f"{key}: {value}")
    
    full_text = "\n".join(full_text_lines)
    
    log(f"[DATA ANALYSIS] Flattened {len(flattened)} data fields from entire JSON")
    log(f"[DATA ANALYSIS] Total text length: {len(full_text)} characters")
    
    # Build comprehensive rules list (Universal + Category-specific)
    universal_high = LEGAL_METROLOGY_RULES["high_priority"]
    universal_low = LEGAL_METROLOGY_RULES["low_priority"]
    common_name = [LEGAL_METROLOGY_RULES["common_name"]]
    
    # category_rules = CATEGORY_SPECIFIC_RULES.get(category.lower(), {'high_priority': [], 'low_priority': []})
    # category_high = category_rules.get('high_priority', [])
    # category_low = category_rules.get('low_priority', [])
    
    all_high_rules = universal_high #+ category_high
    all_low_rules = universal_low #+ category_low
    all_rules = all_high_rules + all_low_rules + common_name
    
    checklist = "\n".join(
        [
            f"- {rule['name']}: {rule.get('description', '')} "
            f"(Keywords: {', '.join(rule.get('keywords', []))})"
            for rule in all_rules
        ]
    )
    
    prompt = f"""
You are an expert in Indian product regulatory compliance based on Legal Metrology (Packaged Commodities) Rules, 2011 for {category.upper()} products.
I am providing you with a COMPLETE FLATTENED DUMP of all product data from Amazon.
Your job is to search through this ENTIRE dataset to find compliance information.

COMPLETE PRODUCT DATA (ALL FIELDS):
{full_text}

REGULATORY REQUIREMENTS FOR {category.upper()} IN INDIA:
{checklist}

CRITICAL INSTRUCTIONS:
1. Search the ENTIRE data dump above - the information could be ANYWHERE
2. Look for variations and partial matches (e.g., "Country of origin", "Made in", "Manufactured in")
3. Mark status as "present" if you find the information ANYWHERE in the complete data
4. Mark as "partial" ONLY if information is incomplete (e.g., "Made in Asia" instead of specific country)
5. Mark as "missing" ONLY if you absolutely cannot find it anywhere

SEARCH STRATEGIES:
- For MRP: Look for "MRP", "price", "Rs.", "₹", "rupees", "INR"
- For Country of Origin: Look for "Country of origin", "Made in", "Manufactured in", country names
- For Manufacturer/Packer/Importer: Look for "manufacturer", "packer", "importer", "made by", "packed by", "imported by", company addresses
- For Consumer Care: Look for "customer care", "consumer care", "contact", phone numbers, email addresses
- For Net Quantity: Look for "net quantity", "net wt", "weight", "volume", "ml", "gm", "kg", "litre"
- For Unit Price: Look for "per gram", "per ml", "per kg", "/gram", "/ml"
- For Dates: Look for "mfg", "exp", "expiry", "best before", "use by", "shelf life"
- For Dimensions: Look for "size", "dimensions", measurements

EXAMPLES:
SUCCESS: "Country of origin > text: China" → Country of Origin: status="present", value="China", adequacy="adequate"
SUCCESS: "MRP > text: ₹499" → MRP: status="present", value="₹499", adequacy="adequate"
SUCCESS: "Net Quantity > text: 250 gm" → Net Quantity: status="present", value="250 gm", adequacy="adequate"

For each requirement:
1. SEARCH EVERYWHERE in the data dump for related information
2. Status: "present" (found clearly), "partial" (found but incomplete), "missing" (not found)
3. Extracted value: The EXACT text you found
4. Found in: The JSON path/key where you found it
5. Adequacy: "adequate" (clear), "inadequate" (unclear), "missing" (not found)

Return ONLY valid JSON (no markdown, no explanations):
{{
  "findings": [
    {{
      "requirement": "Exact requirement name from checklist",
      "status": "present" or "partial" or "missing",
      "found_in": "exact JSON path where found",
      "extracted_value": "exact text found",
      "adequacy": "adequate" or "inadequate" or "missing",
      "notes": "brief explanation"
    }}
  ],
  "data_quality_score": 0.0 to 1.0,
  "missing_critical_info": ["list of items truly missing"],
  "recommendations": ["specific suggestions"]
}}
"""
    
    try:
        response = llm.invoke(prompt)
        
        if not response or not hasattr(response, "content") or not response.content:
            log("[WARNING] LLM returned empty response for data analysis")
            return {
                "findings": [],
                "data_quality_score": 0.5,
                "missing_critical_info": ["Unable to analyze - AI returned no response"],
                "recommendations": ["Please try analyzing again"]
            }
        
        response_text = response.content.strip()
        response_text = _strip_json_fence(response_text)
        
        try:
            analysis_results = json.loads(response_text)
        except (json.JSONDecodeError, TypeError) as e:
            log(f"[WARNING] JSON parsing failed for data analysis: {e}")
            log(f"[WARNING] Raw response: {response_text[:500]}")
            analysis_results = {
                "findings": [],
                "data_quality_score": 0.5,
                "missing_critical_info": ["Unable to parse analysis results"],
                "recommendations": ["Ensure product description contains all required information"]
            }
        
        # DEBUG: Print what AI found
        log(f"[DATA ANALYSIS DEBUG] AI returned {len(analysis_results.get('findings', []))} findings:")
        for f in analysis_results.get("findings", [])[:10]:  # Show first 10
            status = f.get("status", "?")
            adequacy = f.get("adequacy", "?")
            value = f.get("extracted_value", "")
            found_in = f.get("found_in", "")
            log(f"  • {f.get('requirement', 'Unknown')}: status={status}, adequacy={adequacy}")
            log(f"   └─ value='{value[:60]}...' from: {found_in[:50]}")
        
        log(f"[DATA ANALYSIS] SUCCESS: Complete. Quality Score: {analysis_results.get('data_quality_score', 0.5)}")
        
        return analysis_results
    
    except Exception as e:
        log(f"[ERROR] Data analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "findings": [],
            "data_quality_score": 0.0,
            "missing_critical_info": ["Analysis failed"],
            "recommendations": ["Please check product data and try again"],
            "error": str(e)
        }

# ==================== COMPLIANCE SCORING ====================
def calculate_compliance_score(
    ocr_results: Dict[str, Any],
    data_analysis: Dict[str, Any],
    category: str
) -> Dict[str, Any]:
    """
    NEW WEIGHTAGE LOGIC:
    - High priority rules: 90% total weightage (each rule gets 90/num_high_rules %)
    - Low priority rules: 10% total weightage (each rule gets 10/num_low_rules %)
    - Violations reduce the score by their respective weightage
    """
    log(f"[SCORING] Calculating compliance score for category: {category}")
    
    # Build comprehensive rules list (Universal + Category-specific)
    universal_high = LEGAL_METROLOGY_RULES["high_priority"]
    universal_low = LEGAL_METROLOGY_RULES["low_priority"]
    common_name = [LEGAL_METROLOGY_RULES["common_name"]]
    
    # category_rules = CATEGORY_SPECIFIC_RULES.get(category.lower(), {'high_priority': [], 'low_priority': []})
    # category_high = category_rules.get('high_priority', [])
    # category_low = category_rules.get('low_priority', [])
    
    all_high_rules = universal_high #+ category_highcategory_low
    all_low_rules = universal_low + common_name #+ category_low  # Common name goes to low priority
    
    # Calculate weightage per rule
    num_high = len(all_high_rules)
    num_low = len(all_low_rules)
    
    high_weightage_per_rule = 90.0 / num_high if num_high > 0 else 0.0
    low_weightage_per_rule = 10.0 / num_low if num_low > 0 else 0.0
    
    log(f"[SCORING] High priority rules: {num_high} (each worth {high_weightage_per_rule:.2f}%)")
    log(f"[SCORING] Low priority rules: {num_low} (each worth {low_weightage_per_rule:.2f}%)")
    
    total_score = 100.0
    violations: List[Dict[str, Any]] = []
    penalized_requirements = set()
    
    # Build lookup dictionaries with normalized keys
    def normalize_key(s: str) -> str:
        """Normalize requirement names for matching."""
        return s.lower().replace("/", " ").replace("-", " ").strip()
    
    ocr_findings_by_req = {}
    for f in ocr_results.get("visual_findings", []):
        req_name = f.get("requirement", "")
        if req_name:
            ocr_findings_by_req[normalize_key(req_name)] = f
    
    data_findings_by_req = {}
    for f in data_analysis.get("findings", []):
        req_name = f.get("requirement", "")
        if req_name:
            data_findings_by_req[normalize_key(req_name)] = f
    
    log(f"[SCORING DEBUG] OCR findings: {len(ocr_findings_by_req)} items")
    log(f"[SCORING DEBUG] Data findings: {len(data_findings_by_req)} items")
    
    # Process HIGH priority rules
    for rule in all_high_rules:
        requirement_name = rule.get("name", "")
        if not requirement_name or requirement_name in penalized_requirements:
            continue
        
        req_normalized = normalize_key(requirement_name)
        
        # Try exact normalized match first
        ocr_finding = ocr_findings_by_req.get(req_normalized)
        data_finding = data_findings_by_req.get(req_normalized)
        
        # Fallback: keyword matching
        if not ocr_finding:
            req_keywords = set(req_normalized.split())
            for key, finding in ocr_findings_by_req.items():
                key_keywords = set(key.split())
                if len(req_keywords & key_keywords) >= 2:  # At least 2 matching words
                    ocr_finding = finding
                    break
        
        if not data_finding:
            req_keywords = set(req_normalized.split())
            for key, finding in data_findings_by_req.items():
                key_keywords = set(key.split())
                if len(req_keywords & key_keywords) >= 2:
                    data_finding = finding
                    break
        
        # Determine status from findings
        ocr_status = ocr_finding.get("status", "missing") if ocr_finding else "missing"
        data_status = data_finding.get("status", "missing") if data_finding else "missing"
        data_adequacy = data_finding.get("adequacy", "missing") if data_finding else "missing"
        
        ocr_value = ocr_finding.get("extracted_value", "").strip() if ocr_finding else ""
        data_value = data_finding.get("extracted_value", "").strip() if data_finding else ""


        
        # COMPREHENSIVE PRESENCE CHECK
        is_present = False
        
        # Method 1: Explicit "present" status
        if ocr_status == "present" or data_status == "present":
            is_present = True
        
        # Method 2: Adequate data
        if data_adequacy == "adequate":
            is_present = True
        
        # Method 3: Has meaningful extracted value
        excluded_values = ["n/a", "not found", "missing", "none", "not available", "na", ""]
        if ocr_value and len(ocr_value) > 2 and ocr_value.lower() not in excluded_values:
            is_present = True
        if data_value and len(data_value) > 2 and data_value.lower() not in excluded_values:
            is_present = True
        
        # Method 4: Status is not explicitly "missing"
        if ocr_status not in ["missing", ""] or data_status not in ["missing", ""]:
            if (ocr_value and ocr_value.lower() not in excluded_values) or \
               (data_value and data_value.lower() not in excluded_values):
                is_present = True
        
        log(f"[SCORING DEBUG] HIGH: {requirement_name}:")
        log(f"  └─ OCR: {ocr_status} = '{ocr_value[:30] if ocr_value else 'empty'}'")
        log(f"  └─ Data: {data_status}/{data_adequacy} = '{data_value[:30] if data_value else 'empty'}'")
        log(f"  └─ Present: {is_present}")
        
        # If present, skip this requirement
        if is_present:
            penalized_requirements.add(requirement_name)
            continue
        
        # Determine if partial
        is_partial = (
            ocr_status in ["unclear", "partial"] or
            data_status in ["partial"] or
            data_adequacy in ["inadequate"]
        )
        
        # Calculate penalty
        if is_partial:
            penalty = high_weightage_per_rule * 0.5  # 50% penalty for partial
            violation_type = "partial"
        else:
            penalty = high_weightage_per_rule  # Full penalty for missing
            violation_type = "missing"
        
        total_score -= penalty
        
        violations.append({
            "type": violation_type,
            "severity": "high",
            "requirement": requirement_name,
            "penalty": penalty,
            "description": rule.get("description", ""),
            "ocr_status": ocr_status,
            "data_status": data_status,
            "data_adequacy": data_adequacy
        })
        
        penalized_requirements.add(requirement_name)
    
    # Process LOW priority rules
    for rule in all_low_rules:
        requirement_name = rule.get("name", "")
        if not requirement_name or requirement_name in penalized_requirements:
            continue
        
        req_normalized = normalize_key(requirement_name)
        
        # Try exact normalized match first
        ocr_finding = ocr_findings_by_req.get(req_normalized)
        data_finding = data_findings_by_req.get(req_normalized)
        
        # Fallback: keyword matching
        if not ocr_finding:
            req_keywords = set(req_normalized.split())
            for key, finding in ocr_findings_by_req.items():
                key_keywords = set(key.split())
                if len(req_keywords & key_keywords) >= 2:
                    ocr_finding = finding
                    break
        
        if not data_finding:
            req_keywords = set(req_normalized.split())
            for key, finding in data_findings_by_req.items():
                key_keywords = set(key.split())
                if len(req_keywords & key_keywords) >= 2:
                    data_finding = finding
                    break
        
        # Determine status from findings
        ocr_status = ocr_finding.get("status", "missing") if ocr_finding else "missing"
        data_status = data_finding.get("status", "missing") if data_finding else "missing"
        data_adequacy = data_finding.get("adequacy", "missing") if data_finding else "missing"
        
        ocr_value = ocr_finding.get("extracted_value", "").strip() if ocr_finding else ""
        data_value = data_finding.get("extracted_value", "").strip() if data_finding else ""
        
        # COMPREHENSIVE PRESENCE CHECK
        is_present = False
        
        if ocr_status == "present" or data_status == "present":
            is_present = True
        
        if data_adequacy == "adequate":
            is_present = True
        
        excluded_values = ["n/a", "not found", "missing", "none", "not available", "na", ""]
        if ocr_value and len(ocr_value) > 2 and ocr_value.lower() not in excluded_values:
            is_present = True
        if data_value and len(data_value) > 2 and data_value.lower() not in excluded_values:
            is_present = True
        
        if ocr_status not in ["missing", ""] or data_status not in ["missing", ""]:
            if (ocr_value and ocr_value.lower() not in excluded_values) or \
               (data_value and data_value.lower() not in excluded_values):
                is_present = True
        
        log(f"[SCORING DEBUG] LOW: {requirement_name}:")
        log(f"  └─ OCR: {ocr_status} = '{ocr_value[:30] if ocr_value else 'empty'}'")
        log(f"  └─ Data: {data_status}/{data_adequacy} = '{data_value[:30] if data_value else 'empty'}'")
        log(f"  └─ Present: {is_present}")
        
        # If present, skip this requirement
        if is_present:
            penalized_requirements.add(requirement_name)
            continue
        
        # Determine if partial
        is_partial = (
            ocr_status in ["unclear", "partial"] or
            data_status in ["partial"] or
            data_adequacy in ["inadequate"]
        )
        
        # Calculate penalty
        if is_partial:
            penalty = low_weightage_per_rule * 0.5  # 50% penalty for partial
            violation_type = "partial"
        else:
            penalty = low_weightage_per_rule  # Full penalty for missing
            violation_type = "missing"
        
        total_score -= penalty
        
        violations.append({
            "type": violation_type,
            "severity": "low",
            "requirement": requirement_name,
            "penalty": penalty,
            "description": rule.get("description", ""),
            "ocr_status": ocr_status,
            "data_status": data_status,
            "data_adequacy": data_adequacy
        })
        
        penalized_requirements.add(requirement_name)

    # ==================== CROSS-VALIDATION: Address vs Country of Origin ====================
    # Check if manufacturer/packer address matches declared country of origin
    log("[CROSS-VALIDATION] Checking address consistency with country of origin...")
    
    def find_requirement_data(req_name: str, findings_dict: Dict) -> tuple:
        """Helper to find requirement data from findings"""
        normalized = normalize_key(req_name)
        finding = findings_dict.get(normalized)
        if finding:
            return finding.get("extracted_value", ""), finding.get("status", "missing")
        return "", "missing"
    
    # Get country of origin
    country_value, country_status = find_requirement_data("Country of Origin", ocr_findings_by_req)
    if not country_value or country_status == "missing":
        country_value, country_status = find_requirement_data("Country of Origin", data_findings_by_req)
    
    # Get manufacturer/packer/importer address
    address_value, address_status = find_requirement_data("Manufacturer/Packer/Importer Name and Address", ocr_findings_by_req)
    if not address_value or address_status == "missing":
        address_value, address_status = find_requirement_data("Manufacturer/Packer/Importer Name and Address", data_findings_by_req)
    
    log(f"[CROSS-VALIDATION] Country: '{country_value}' (status: {country_status})")
    log(f"[CROSS-VALIDATION] Address: '{address_value[:100] if address_value else 'empty'}...' (status: {address_status})")
    
    # Perform validation only if both are present
    if country_value and address_value and country_status != "missing" and address_status != "missing":
        country_lower = country_value.lower().strip()
        address_lower = address_value.lower().strip()
        
        # Country name variations
        country_variants = {
            'india': ['india', 'indian', 'bharat', 'ind'],
            'china': ['china', 'chinese', 'prc', 'peoples republic of china'],
            'usa': ['usa', 'united states', 'america', 'us'],
            'uk': ['uk', 'united kingdom', 'britain', 'great britain', 'england'],
            'germany': ['germany', 'german', 'deutschland'],
            'japan': ['japan', 'japanese', 'nihon'],
            'korea': ['korea', 'korean', 'south korea'],
            'taiwan': ['taiwan', 'taiwanese', 'roc'],
            'thailand': ['thailand', 'thai'],
            'vietnam': ['vietnam', 'vietnamese'],
            'malaysia': ['malaysia', 'malaysian'],
            'singapore': ['singapore', 'singaporean'],
            'indonesia': ['indonesia', 'indonesian'],
            'bangladesh': ['bangladesh', 'bangladeshi'],
            'pakistan': ['pakistan', 'pakistani'],
            'sri lanka': ['sri lanka', 'srilankan', 'ceylon']
        }
        
        # Determine declared country
        declared_country = None
        for country_key, variants in country_variants.items():
            if any(variant in country_lower for variant in variants):
                declared_country = country_key
                break
        
        # Determine address country
        address_country = None
        for country_key, variants in country_variants.items():
            if any(variant in address_lower for variant in variants):
                address_country = country_key
                break
        
        log(f"[CROSS-VALIDATION] Declared country normalized: '{declared_country}'")
        log(f"[CROSS-VALIDATION] Address country detected: '{address_country}'")
        
        # Check for mismatch
        mismatch = False
        if declared_country and address_country:
            if declared_country != address_country:
                mismatch = True
                log(f"[CROSS-VALIDATION] âš ï¸ MISMATCH DETECTED: Country of Origin ({declared_country}) != Address Country ({address_country})")
        elif declared_country and not address_country:
            # Country declared but address doesn't clearly indicate country
            # This is suspicious but not conclusive
            log(f"[CROSS-VALIDATION] âš ï¸ WARNING: Country declared as '{declared_country}' but address location unclear")
        
        if mismatch:
            # Add HIGH priority violation for country-address mismatch
            mismatch_penalty = high_weightage_per_rule * 0.75  # 75% of high rule weightage
            total_score -= mismatch_penalty
            
            violations.append({
                "type": "mismatch",
                "severity": "high",
                "requirement": "Country of Origin vs Address Consistency",
                "penalty": mismatch_penalty,
                "description": f"Declared country of origin ({declared_country.upper()}) does not match the manufacturer/packer address location ({address_country.upper()})",
                "declared_country": declared_country,
                "address_country": address_country,
                "country_value": country_value,
                "address_value": address_value[:200],  # First 200 chars
                "ocr_status": "inconsistent",
                "data_status": "inconsistent",
                "data_adequacy": "inadequate"
            })
            
            log(f"[CROSS-VALIDATION] Added mismatch violation with penalty: {mismatch_penalty:.2f}")
    else:
        log("[CROSS-VALIDATION] Skipping validation - country or address not available")
    
    total_score = max(0.0, total_score)
    
    # Grade assignment
    if total_score >= 85:
        grade = "A+"
    elif total_score >= 75:
        grade = "A"
    elif total_score >= 65:
        grade = "B+"
    elif total_score >= 55:
        grade = "B"
    elif total_score >= 45:
        grade = "C+"
    elif total_score >= 35:
        grade = "C"
    elif total_score >= 25:
        grade = "D"
    else:
        grade = "F"
    
    high_violations = [v for v in violations if v["severity"] == "high"]
    low_violations = [v for v in violations if v["severity"] == "low"]
    
    log(
        f"[SCORING] SUCCESS: Final Score: {total_score:.1f}/100 | Grade: {grade}. "
        f"High: {len(high_violations)}, Low: {len(low_violations)}"
    )
    
    return {
        "score": round(total_score, 1),
        "grade": grade,
        "violations": violations,
        "violation_summary": {
            "high": len(high_violations),
            "low": len(low_violations),
            "total": len(violations)
        }
    }

# ==================== RECOMMENDATIONS GENERATOR ====================
def generate_recommendations(violations: List[Dict], ocr_results: Dict, data_analysis: Dict, category: str) -> List[str]:
    """
    Generate SMARTER recommendations based on violation type
    """
    if not category:
        category = 'amazon'
    
    recommendations = []
    
    # Separate by violation severity
    high_missing = [v for v in violations if v.get('type') == 'missing' and v.get('severity') == 'high']
    high_partial = [v for v in violations if v.get('type') == 'partial' and v.get('severity') == 'high']
    low_missing = [v for v in violations if v.get('type') == 'missing' and v.get('severity') == 'low']
    low_partial = [v for v in violations if v.get('type') == 'partial' and v.get('severity') == 'low']
    
    # High priority missing - CRITICAL
    if high_missing:
        recommendations.append("🚨 CRITICAL ACTIONS REQUIRED (High Priority):")
        for v in high_missing:
            recommendations.append(f"  • Add: {v.get('requirement', 'Unknown')}")
    
    # High priority partial - IMPORTANT
    if high_partial:
        recommendations.append("\nWARNING:️ IMPORTANT IMPROVEMENTS (High Priority):")
        for v in high_partial:
            recommendations.append(f"  • Complete/Clarify: {v.get('requirement', 'Unknown')}")
    
    # Low priority missing
    if low_missing and len(recommendations) < 15:
        recommendations.append("\n📋 ADDITIONAL REQUIREMENTS (Low Priority):")
        for v in low_missing[:5]:  # Limit to 5
            recommendations.append(f"  • Include: {v.get('requirement', 'Unknown')}")
    
    # Low priority partial
    if low_partial and len(recommendations) < 20:
        recommendations.append("\n💡 SUGGESTED IMPROVEMENTS (Low Priority):")
        for v in low_partial[:5]:
            recommendations.append(f"  • Improve: {v.get('requirement', 'Unknown')}")
    
    # Image quality tips
    if len(ocr_results.get('visual_findings', [])) < 3:
        recommendations.append("\n📸 IMAGE TIPS:")
        recommendations.append("  • Upload clear photos of product labels")
        recommendations.append("  • Include front, back, and side label images")
    
    return recommendations if recommendations else ["SUCCESS: Product meets basic compliance requirements"]

# ==================== MAIN COMPLIANCE ANALYSIS FUNCTION ====================
def analyze_compliance(product_id: int) -> Dict[str, Any]:
    """
    Main function: Analyze product compliance from database
    
    Args:
        product_id: Database product ID
    
    Returns:
        Complete compliance report with score, grade, violations, and recommendations
    """
    log(f"\n[COMPLIANCE ENGINE] Starting analysis for Product ID: {product_id}")
    
    connection = get_db_connection()
    if not connection:
        return {'error': 'Database connection failed'}
    
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Fetch product data
        cursor.execute("SELECT * FROM Products WHERE product_id = %s", (product_id,))
        product = cursor.fetchone()
        log(product)
        
        if not product:
            return {'error': 'Product not found'}
        
        # Parse JSON data
        product_json = json.loads(product.get('product_json', '{}'))
        product_json_raw = json.loads(product.get('product_json_raw', '{}'))
        category = product_json.get('detected_category', 'amazon')
        
        log(f"[COMPLIANCE] Product: {product.get('title', 'Unknown')}")
        log(f"[COMPLIANCE] Category: {category}")
        
        # Fetch images
        cursor.execute("SELECT image_data FROM Images WHERE product_id = %s LIMIT 10", (product_id,))
        images = cursor.fetchall()
        image_blobs = [img['image_data'] for img in images]
        
        log(f"[COMPLIANCE] Found {len(image_blobs)} images")
        
        # Step 1: OCR and Visual Analysis
        ocr_results = analyze_images_with_ocr(image_blobs, category)
        
        raw_seller_info = product.get('seller_information')
        if not raw_seller_info:
            raw_seller_info = "{}"
        try:
            seller_info = json.loads(raw_seller_info)
        except Exception:
            seller_info = {}
        
        # Step 2: Text Data Analysis
        product_data = product_json_raw
        data_analysis = analyze_product_data(product_data, category)
        
        # Step 3: Calculate Compliance Score
        scoring = calculate_compliance_score(ocr_results, data_analysis, category)
        
        # Step 4: Generate Recommendations
        recommendations = generate_recommendations(
            scoring['violations'],
            ocr_results,
            data_analysis,
            category
        )
        
        # Compile final report
        compliance_report = {
            'product_id': product_id,
            'asin': product.get('asin') or '',
            'title': product.get('title') or 'Untitled Product',
            'category': category,
            'analysis_date': datetime.now().isoformat(),
            'compliance_score': scoring['score'],
            'compliance_grade': scoring['grade'],
            'violation_summary': scoring['violation_summary'],
            'violations': scoring['violations'],
            'ocr_analysis': {
                'success': ocr_results.get('ocr_success', False),
                'extracted_text': (ocr_results.get('extracted_text', '') or '')[:500],  # First 500 chars
                'image_quality': ocr_results.get('image_quality', 'unknown'),
                'confidence': ocr_results.get('confidence_score', 0.0),
                'symbols_found': ocr_results.get('symbols_found', [])
            },
            'data_analysis': {
                'quality_score': data_analysis.get('data_quality_score', 0.0),
                'missing_critical_info': data_analysis.get('missing_critical_info', [])
            },
            'recommendations': recommendations,
            'is_compliant': scoring['score'] >= 70,
            'requires_action': len([v for v in scoring['violations'] if v.get('severity') == 'high']) > 0,
            'log': LOG_BUFFER
        }
        
        # Update database with compliance results
        try:
            cursor.execute("""
                UPDATE Products
                SET analysis_results = %s,
                    rating = %s,
                    remarks = %s,
                    last_analysed = %s
                WHERE product_id = %s
            """, (
                json.dumps(compliance_report, default=str),
                scoring['score'],
                f"Grade: {scoring['grade']} | Violations: {scoring['violation_summary']['total']}",
                datetime.now(),
                product_id
            ))
            connection.commit()
            log(f"[COMPLIANCE] Analysis complete and saved to database")
        except Error as e:
            log(f"[WARNING] Failed to save compliance report to DB: {e}")
            # Continue anyway - we still have the report
        
        cursor.close()
        connection.close()
        
        return compliance_report
    
    except Exception as e:
        log(f"[ERROR] Compliance analysis failed: {e}")
        import traceback
        traceback.print_exc()
        
        if connection:
            try:
                connection.rollback()
                cursor.close()
                connection.close()
            except:
                pass
        
        return {'error': str(e), 'traceback': traceback.format_exc()}

# # ==================== SELLER UPLOAD ANALYSIS ====================
# def analyze_seller_upload_text(images: List[bytes], raw_text: str, category: str = 'amazon') -> Dict[str, Any]:
#     """
#     Analyze seller's product using raw text description (converted from speech)
#     The text will be parsed to extract product information
    
#     Args:
#         images: List of image bytes
#         raw_text: Raw text description from speech-to-text
#         category: Product category (auto-detected if not provided)
    
#     Returns:
#         Instant compliance report with recommendations
#     """
#     if not category:
#         category = 'amazon'
    
#     log(f"\n[SELLER TEXT UPLOAD] Analyzing text-based upload for category: {category}")
    
#     try:
#         # Validate inputs
#         if not images:
#             return {
#                 'error': 'No images provided',
#                 'compliance_score': 0,
#                 'compliance_grade': 'F',
#                 'ready_for_upload': False
#             }
        
#         if not raw_text or not raw_text.strip():
#             return {
#                 'error': 'No product description provided',
#                 'compliance_score': 0,
#                 'compliance_grade': 'F',
#                 'ready_for_upload': False
#             }
        
#         # Parse raw text into structured product data
#         product_data = raw_text
        
#         log(f"[SELLER TEXT UPLOAD] Extracted: title={bool(product_data['title'])}, "
#             f"description={bool(product_data['description'])}, "
#             f"features={len(product_data['feature_bullets'])}")
        
#         # Step 1: OCR and Visual Analysis
#         ocr_results = analyze_images_with_ocr(images, category)
        
#         # Step 2: Text Data Analysis
#         data_analysis = analyze_product_data(product_data, category)
        
#         # Step 3: Calculate Compliance Score
#         scoring = calculate_compliance_score(ocr_results, data_analysis, category)
        
#         # Step 4: Generate Recommendations
#         recommendations = generate_recommendations(
#             scoring['violations'],
#             ocr_results,
#             data_analysis,
#             category
#         )
        
#         # Compile instant feedback report
#         feedback_report = {
#             'category': category,
#             'analysis_date': datetime.now().isoformat(),
#             'compliance_score': scoring['score'],
#             'compliance_grade': scoring['grade'],
#             'violation_summary': scoring['violation_summary'],
#             'high_priority_issues': [v for v in scoring['violations'] if v.get('severity') == 'high'],
#             'low_priority_issues': [v for v in scoring['violations'] if v.get('severity') == 'low'],
#             'image_analysis': {
#                 'quality': ocr_results.get('image_quality', 'unknown'),
#                 'confidence': ocr_results.get('confidence_score', 0.0),
#                 'symbols_found': ocr_results.get('symbols_found', [])
#             },
#             'parsed_product_data': product_data,  # Include parsed data for transparency
#             'recommendations': recommendations,
#             'ready_for_upload': scoring['score'] >= 70 and len([v for v in scoring['violations'] if v.get('severity') == 'high']) == 0,
#             'estimated_approval_chance': 'High' if scoring['score'] >= 85 else 'Medium' if scoring['score'] >= 70 else 'Low'
#         }
        
#         print(f"[SELLER TEXT UPLOAD] SUCCESS: Score: {scoring['score']}/100 | Grade: {scoring['grade']}")
#         print(f"[SELLER TEXT UPLOAD] Ready for upload: {feedback_report['ready_for_upload']}")
        
#         return feedback_report
    
#     except Exception as e:
#         print(f"[ERROR] Seller text upload analysis failed: {e}")
#         import traceback
#         traceback.print_exc()
#         return {
#             'error': str(e),
#             'traceback': traceback.format_exc(),
#             'compliance_score': 0,
#             'compliance_grade': 'F',
#             'ready_for_upload': False
#         }

# ==================== LLM-POWERED WEIGHT & DIMENSION VALIDATION ====================

def validate_seller_declarations(
    seller_weight: str,
    seller_dimensions: str,
    ocr_text: str,
    product_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate seller-declared weight and dimensions against OCR and product data
    
    Args:
        seller_weight: Seller's declared weight (e.g., "250g", "1.5kg")
        seller_dimensions: Seller's declared dimensions (e.g., "15x10x5 cm", "6 x 4 x 2 inch")
        ocr_text: Extracted text from product images
        product_data: Product information from seller's description
    
    Returns:
        Comprehensive validation report with mismatches
    """
    log("[VALIDATION] Starting seller declaration validation...")
    
    # Flatten product data for comprehensive search
    def flatten_dict(d: Any, parent_key: str = '', sep: str = ' > ') -> Dict[str, str]:
        items = {}
        if isinstance(d, dict):
            for k, v in d.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, dict):
                    items.update(flatten_dict(v, new_key, sep=sep))
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, (dict, list)):
                            items.update(flatten_dict(item, f"{new_key}[{i}]", sep=sep))
                        else:
                            items[f"{new_key}[{i}]"] = str(item)
                else:
                    if v is not None:
                        items[new_key] = str(v)
        elif isinstance(d, list):
            for i, item in enumerate(d):
                if isinstance(item, (dict, list)):
                    items.update(flatten_dict(item, f"{parent_key}[{i}]", sep=sep))
                else:
                    items[f"{parent_key}[{i}]"] = str(item)
        else:
            if d is not None:
                items[parent_key] = str(d)
        return items
    
    flattened_data = flatten_dict(product_data)
    full_data_text = "\n".join([f"{k}: {v}" for k, v in flattened_data.items()])
    
    # ==================== LLM VALIDATION PROMPT ====================
    
    validation_prompt = f"""You are an expert product compliance validator.

SELLER'S DECLARATIONS (from frontend form):
- Declared Weight: {seller_weight if seller_weight else "NOT PROVIDED"}
- Declared Dimensions: {seller_dimensions if seller_dimensions else "NOT PROVIDED"}

TASK: Validate these declarations against OCR data and product description.

OCR TEXT (from product images/packaging):
{ocr_text[:3000] if ocr_text else "No OCR text available"}

PRODUCT DATA (from seller's description):
{full_data_text[:3000] if full_data_text else "No product data available"}

VALIDATION RULES:
1. Extract weight from OCR text and product data
2. Extract dimensions from OCR text and product data
3. Compare seller's declarations with what's found in OCR and data
4. Check for consistency across all three sources (seller declaration, OCR, product data)

WEIGHT VALIDATION:
- Look for: kg, g, gm, gram, mg, lb, lbs, oz, ounce
- Variations: "Net Wt: 250g", "Weight: 1.5 kg", "500 grams"
- Accept 5% tolerance (e.g., 250g vs 248g is OK)

DIMENSION VALIDATION:
- Look for: L x W x H format in cm, mm, m, inch, in
- Formats: "15x10x5 cm", "6" x 4" x 2"", "15 cm x 10 cm x 5 cm"
- Accept 5% tolerance per dimension

IMPORTANT:
- Mark as "match" if all three sources agree (within tolerance)
- Mark as "mismatch" if seller declaration differs from OCR or product data
- Mark as "partial_match" if only 2 out of 3 sources agree
- Mark as "insufficient_data" if OCR or product data doesn't have the information
- Provide specific details about what was found where

Return STRICT JSON (no markdown, no code blocks):
{{
  "seller_declared_weight": {{
    "value": 250.0,
    "unit": "g",
    "parsed_from": "250g",
    "confidence": "high"
  }},
  "ocr_weight": {{
    "value": 250.0,
    "unit": "g",
    "raw_text": "Net Wt: 250g",
    "confidence": "high"
  }},
  "data_weight": {{
    "value": 250.0,
    "unit": "grams",
    "raw_text": "weight: 250 grams",
    "confidence": "high"
  }},
  "weight_validation": {{
    "status": "match",
    "seller_vs_ocr": "match",
    "seller_vs_data": "match",
    "ocr_vs_data": "match",
    "details": "All three sources agree on 250g"
  }},
  "seller_declared_dimensions": {{
    "length": 15.0,
    "width": 10.0,
    "height": 5.0,
    "unit": "cm",
    "parsed_from": "15x10x5 cm",
    "confidence": "high"
  }},
  "ocr_dimensions": {{
    "length": 15.0,
    "width": 10.0,
    "height": 5.0,
    "unit": "cm",
    "raw_text": "15 x 10 x 5 cm",
    "confidence": "high"
  }},
  "data_dimensions": {{
    "length": 15.0,
    "width": 10.0,
    "height": 5.0,
    "unit": "cm",
    "raw_text": "dimensions: 15cm x 10cm x 5cm",
    "confidence": "high"
  }},
  "dimension_validation": {{
    "status": "match",
    "seller_vs_ocr": "match",
    "seller_vs_data": "match",
    "ocr_vs_data": "match",
    "details": "All three sources agree on 15x10x5 cm"
  }},
  "critical_mismatches": [],
  "warnings": []
}}

If seller didn't provide declarations, set those fields to null.
If any source is missing data, mark confidence as "none" and status as "insufficient_data".
For mismatches, populate "critical_mismatches" array with detailed explanations.
"""
    
    try:
        # Call LLM for validation
        response = llm.invoke(validation_prompt)
        
        if not response or not hasattr(response, "content") or not response.content:
            log("[VALIDATION] Empty response from LLM")
            return _get_empty_validation_result()
        
        response_text = response.content.strip()
        response_text = _strip_json_fence(response_text)
        
        try:
            validation_result = json.loads(response_text)
        except (json.JSONDecodeError, TypeError) as e:
            log(f"[VALIDATION] JSON parsing failed: {e}")
            log(f"[VALIDATION] Raw response: {response_text[:500]}")
            return _get_empty_validation_result()
        
        log(f"[VALIDATION] SUCCESS: Successfully validated declarations")
        
        # Add normalized comparisons
        validation_result = _add_normalized_comparisons(validation_result)
        
        return validation_result
    
    except Exception as e:
        log(f"[ERROR] Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return _get_empty_validation_result()


def _add_normalized_comparisons(validation_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add normalized weight/dimension comparisons and calculate mismatch severity
    """
    # Weight comparison
    seller_w = validation_result.get('seller_declared_weight')
    ocr_w = validation_result.get('ocr_weight')
    data_w = validation_result.get('data_weight')
    
    mismatches = []
    warnings = []
    
    if seller_w and seller_w.get('confidence') in ['high', 'medium']:
        seller_grams = normalize_weight_to_grams(seller_w['value'], seller_w['unit'])
        
        # Compare with OCR
        if ocr_w and ocr_w.get('confidence') in ['high', 'medium']:
            ocr_grams = normalize_weight_to_grams(ocr_w['value'], ocr_w['unit'])
            if seller_grams and ocr_grams:
                diff_percent = abs(seller_grams - ocr_grams) / seller_grams * 100 if seller_grams > 0 else 100
                if diff_percent > 5:
                    mismatches.append({
                        'type': 'weight',
                        'severity': 'critical',
                        'message': f"Seller declared weight ({seller_w['value']}{seller_w['unit']}) doesn't match package weight ({ocr_w['value']}{ocr_w['unit']}). Difference: {diff_percent:.1f}%",
                        'seller_value': f"{seller_w['value']}{seller_w['unit']}",
                        'ocr_value': f"{ocr_w['value']}{ocr_w['unit']}",
                        'difference_percent': round(diff_percent, 2)
                    })
        
        # Compare with product data
        if data_w and data_w.get('confidence') in ['high', 'medium']:
            data_grams = normalize_weight_to_grams(data_w['value'], data_w['unit'])
            if seller_grams and data_grams:
                diff_percent = abs(seller_grams - data_grams) / seller_grams * 100 if seller_grams > 0 else 100
                if diff_percent > 5:
                    warnings.append({
                        'type': 'weight',
                        'severity': 'medium',
                        'message': f"Seller declared weight ({seller_w['value']}{seller_w['unit']}) doesn't match product description weight ({data_w['value']}{data_w['unit']}). Difference: {diff_percent:.1f}%",
                        'difference_percent': round(diff_percent, 2)
                    })
    
    # Dimension comparison
    seller_d = validation_result.get('seller_declared_dimensions')
    ocr_d = validation_result.get('ocr_dimensions')
    data_d = validation_result.get('data_dimensions')
    
    if seller_d and seller_d.get('confidence') in ['high', 'medium']:
        seller_cm = normalize_dimensions_to_cm(seller_d)
        
        # Compare with OCR
        if ocr_d and ocr_d.get('confidence') in ['high', 'medium']:
            ocr_cm = normalize_dimensions_to_cm(ocr_d)
            if seller_cm and ocr_cm:
                dims = ['length', 'width', 'height']
                dim_mismatches = []
                for dim in dims:
                    seller_val = seller_cm[dim]
                    ocr_val = ocr_cm[dim]
                    if seller_val > 0:
                        diff_percent = abs(seller_val - ocr_val) / seller_val * 100
                        if diff_percent > 5:
                            dim_mismatches.append(f"{dim.capitalize()}: {diff_percent:.1f}% difference")
                
                if dim_mismatches:
                    mismatches.append({
                        'type': 'dimensions',
                        'severity': 'critical',
                        'message': f"Seller declared dimensions don't match package dimensions. {', '.join(dim_mismatches)}",
                        'seller_value': f"{seller_d['length']}x{seller_d['width']}x{seller_d['height']} {seller_d['unit']}",
                        'ocr_value': f"{ocr_d['length']}x{ocr_d['width']}x{ocr_d['height']} {ocr_d['unit']}",
                        'mismatched_dimensions': dim_mismatches
                    })
        
        # Compare with product data
        if data_d and data_d.get('confidence') in ['high', 'medium']:
            data_cm = normalize_dimensions_to_cm(data_d)
            if seller_cm and data_cm:
                dims = ['length', 'width', 'height']
                dim_mismatches = []
                for dim in dims:
                    seller_val = seller_cm[dim]
                    data_val = data_cm[dim]
                    if seller_val > 0:
                        diff_percent = abs(seller_val - data_val) / seller_val * 100
                        if diff_percent > 5:
                            dim_mismatches.append(f"{dim.capitalize()}: {diff_percent:.1f}% difference")
                
                if dim_mismatches:
                    warnings.append({
                        'type': 'dimensions',
                        'severity': 'medium',
                        'message': f"Seller declared dimensions don't match product description. {', '.join(dim_mismatches)}",
                        'mismatched_dimensions': dim_mismatches
                    })
    
    validation_result['critical_mismatches'] = mismatches
    validation_result['warnings'] = warnings
    
    return validation_result


def _get_empty_validation_result() -> Dict[str, Any]:
    """Return empty validation result structure"""
    return {
        'seller_declared_weight': None,
        'ocr_weight': None,
        'data_weight': None,
        'weight_validation': {
            'status': 'insufficient_data',
            'details': 'Unable to validate weight'
        },
        'seller_declared_dimensions': None,
        'ocr_dimensions': None,
        'data_dimensions': None,
        'dimension_validation': {
            'status': 'insufficient_data',
            'details': 'Unable to validate dimensions'
        },
        'critical_mismatches': [],
        'warnings': []
    }


def normalize_weight_to_grams(value: float, unit: str) -> Optional[float]:
    """Convert weight to grams for comparison"""
    if not value or not unit:
        return None
    
    unit = unit.lower().strip()
    conversions = {
        'kg': 1000, 'kilogram': 1000, 'kilograms': 1000, 'kgs': 1000,
        'g': 1, 'gm': 1, 'gram': 1, 'grams': 1, 'gms': 1,
        'mg': 0.001, 'milligram': 0.001, 'milligrams': 0.001,
        'lb': 453.592, 'lbs': 453.592, 'pound': 453.592, 'pounds': 453.592,
        'oz': 28.3495, 'ounce': 28.3495, 'ounces': 28.3495
    }
    
    return value * conversions.get(unit, 1)


def normalize_dimensions_to_cm(dimensions: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Convert dimensions to cm for comparison"""
    if not dimensions or not dimensions.get('unit'):
        return None
    
    unit = dimensions['unit'].lower().strip()
    conversions = {
        'cm': 1, 'centimeter': 1, 'centimeters': 1,
        'mm': 0.1, 'millimeter': 0.1, 'millimeters': 0.1,
        'm': 100, 'meter': 100, 'meters': 100, 'metre': 100, 'metres': 100,
        'inch': 2.54, 'inches': 2.54, 'in': 2.54, '"': 2.54,
        'ft': 30.48, 'foot': 30.48, 'feet': 30.48, "'": 30.48
    }
    
    multiplier = conversions.get(unit, 1)
    
    try:
        return {
            'length': float(dimensions.get('length', 0)) * multiplier,
            'width': float(dimensions.get('width', 0)) * multiplier,
            'height': float(dimensions.get('height', 0)) * multiplier
        }
    except (ValueError, TypeError):
        return None


# ==================== UPDATED analyze_seller_upload_text ====================

def analyze_seller_upload_text(
    images: List[bytes], 
    raw_text: str, 
    category: str = 'amazon',
    actual_weight: str = None,
    actual_dimensions: str = None
) -> Dict[str, Any]:
    """
    Analyze seller's product with seller-declared weight and dimensions
    """
    if not category:
        category = 'amazon'
    
    log(f"\n[SELLER TEXT UPLOAD] Analyzing text-based upload for category: {category}")
    log(f"[SELLER TEXT UPLOAD] Declared weight: {actual_weight}, Declared dimensions: {actual_dimensions}")
    
    try:
        # Validate inputs
        if not images:
            return {'error': 'No images provided', 'compliance_score': 0, 'compliance_grade': 'F', 'ready_for_upload': False}
        
        if not raw_text or not raw_text.strip():
            return {'error': 'No product description provided', 'compliance_score': 0, 'compliance_grade': 'F', 'ready_for_upload': False}
        
        # Parse raw text into structured product data
        product_data = raw_text if isinstance(raw_text, dict) else {'raw_text': raw_text}
        
        # Step 1: OCR and Visual Analysis
        ocr_results = analyze_images_with_ocr(images, category)
        
        # Step 2: Text Data Analysis
        data_analysis = analyze_product_data(product_data, category)
        
        # Step 3: Validate Seller Declarations
        validation_result = validate_seller_declarations(
            actual_weight,
            actual_dimensions,
            ocr_results.get('extracted_text', ''),
            product_data
        )
        
        log(f"[VALIDATION] Weight status: {validation_result['weight_validation']['status']}")
        log(f"[VALIDATION] Dimension status: {validation_result['dimension_validation']['status']}")
        log(f"[VALIDATION] Critical mismatches: {len(validation_result['critical_mismatches'])}")
        
        # Step 4: Calculate Compliance Score
        scoring = calculate_compliance_score(ocr_results, data_analysis, category)
        
        # Apply penalties for mismatches
        for mismatch in validation_result['critical_mismatches']:
            if mismatch['type'] == 'weight':
                penalty = 15.0  # 15% penalty for weight mismatch
                scoring['score'] = max(0, scoring['score'] - penalty)
                scoring['violations'].append({
                    'type': 'critical_mismatch',
                    'severity': 'high',
                    'requirement': 'Weight Declaration Accuracy',
                    'penalty': penalty,
                    'description': mismatch['message'],
                    'seller_declared': mismatch.get('seller_value'),
                    'package_shows': mismatch.get('ocr_value'),
                    'difference': f"{mismatch.get('difference_percent', 0):.1f}%"
                })
            
            elif mismatch['type'] == 'dimensions':
                penalty = 12.0  # 12% penalty for dimension mismatch
                scoring['score'] = max(0, scoring['score'] - penalty)
                scoring['violations'].append({
                    'type': 'critical_mismatch',
                    'severity': 'high',
                    'requirement': 'Dimension Declaration Accuracy',
                    'penalty': penalty,
                    'description': mismatch['message'],
                    'seller_declared': mismatch.get('seller_value'),
                    'package_shows': mismatch.get('ocr_value')
                })
        
        # Recalculate grade
        if scoring['score'] >= 85:
            scoring['grade'] = "A+"
        elif scoring['score'] >= 75:
            scoring['grade'] = "A"
        elif scoring['score'] >= 65:
            scoring['grade'] = "B+"
        elif scoring['score'] >= 55:
            scoring['grade'] = "B"
        elif scoring['score'] >= 45:
            scoring['grade'] = "C+"
        elif scoring['score'] >= 35:
            scoring['grade'] = "C"
        elif scoring['score'] >= 25:
            scoring['grade'] = "D"
        else:
            scoring['grade'] = "F"
        
        # Step 5: Generate Recommendations
        recommendations = generate_recommendations(scoring['violations'], ocr_results, data_analysis, category)
        
        # Add specific recommendations for mismatches
        if validation_result['critical_mismatches']:
            recommendations.insert(0, "🚨 CRITICAL MISMATCHES DETECTED - Product will be REJECTED:")
            for mismatch in validation_result['critical_mismatches']:
                recommendations.insert(1, f"  • {mismatch['message']}")
        
        # Compile feedback report
        feedback_report = {
            'category': category,
            'analysis_date': datetime.now().isoformat(),
            'compliance_score': scoring['score'],
            'compliance_grade': scoring['grade'],
            'violation_summary': scoring['violation_summary'],
            'high_priority_issues': [v for v in scoring['violations'] if v.get('severity') == 'high'],
            'low_priority_issues': [v for v in scoring['violations'] if v.get('severity') == 'low'],
            'validation_results': validation_result,
            'image_analysis': {
                'quality': ocr_results.get('image_quality', 'unknown'),
                'confidence': ocr_results.get('confidence_score', 0.0),
                'symbols_found': ocr_results.get('symbols_found', [])
            },
            'parsed_product_data': product_data,
            'recommendations': recommendations,
            'ready_for_upload': (
                scoring['score'] >= 70 and 
                len([v for v in scoring['violations'] if v.get('severity') == 'high']) == 0 and
                len(validation_result['critical_mismatches']) == 0
            ),
            'estimated_approval_chance': 'High' if scoring['score'] >= 85 else 'Medium' if scoring['score'] >= 70 else 'Low'
        }
        
        print(f"[SELLER TEXT UPLOAD] SUCCESS: Score: {scoring['score']}/100 | Grade: {scoring['grade']}")
        print(f"[SELLER TEXT UPLOAD] Ready for upload: {feedback_report['ready_for_upload']}")
        
        return feedback_report
    
    except Exception as e:
        print(f"[ERROR] Seller text upload analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e), 'traceback': traceback.format_exc(), 'compliance_score': 0, 'compliance_grade': 'F', 'ready_for_upload': False}

# ==================== INTELLIGENT CHATBOT ====================
def create_db_agent():
    """
    Create LangChain SQL Agent with database access
    """
    try:
        # Create SQLAlchemy database URL
        db_url = f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}/{DB_CONFIG['database']}"
        
        # Create SQLDatabase object
        db = SQLDatabase.from_uri(db_url)
        
        # Create toolkit
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)
        
        # Create agent with custom system message
        system_message = """You are an intelligent assistant for an Amazon Product Compliance Platform.

Your capabilities:
1. Answer questions about products stored in the database (Users, Products, Images, SellerActivity tables)
2. Provide insights on compliance ratings, violations, and seller activity
3. Answer questions about Indian e-commerce regulations and Legal Metrology compliance requirements
4. Explain compliance scores and suggest improvements

Guidelines:
- ALWAYS use the SQL tools to query the database when asked about stored products or user data
- For general questions about regulations, use your knowledge
- Be concise and helpful
- If asked about data not in the database, politely explain what data is available
- REFUSE vague or unrelated questions (e.g., celebrity birthdays, sports scores)
- Keep responses focused on e-commerce, products, and compliance

Available tables:
- Users: id, username, role (customer/seller), created_at
- Products: product_id, user_id, asin, title, price, currency, seller_information, product_json, analysis_results, rating, last_analysed
- Images: image_id, product_id, image_data, created_at
- SellerActivity: activity_id, seller_id, customer_id, action, location, latitude, longitude, timestamp

When querying:
- Use proper SQL syntax for MySQL
- Handle NULL values appropriately
- Parse JSON columns carefully (product_json, seller_information, analysis_results)
- Limit large result sets"""
        
        # Create the agent
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

# Global agent instance (created once)
_db_agent = None

def chatbot_agent(user_message: str, conversation_history: List[Dict] = None) -> str:
    """
    Intelligent chatbot that can query database and answer questions
    
    Args:
        user_message: User's question
        conversation_history: Previous conversation (optional)
    
    Returns:
        AI response
    """
    global _db_agent
    
    print(f"[CHATBOT] Received message: {user_message[:100]}...")
    
    # Check for irrelevant questions
    irrelevant_keywords = [
        'celebrity', 'cricket', 'sports', 'movie', 'birthday', 'virat kohli',
        'weather', 'news', 'politics', 'election', 'stock market'
    ]
    
    if any(keyword in user_message.lower() for keyword in irrelevant_keywords):
        return ("I'm specialized in Amazon product compliance and e-commerce regulations. "
                "I can help you with:\n"
                "• Product compliance analysis and ratings\n"
                "• Indian Legal Metrology requirements\n"
                "• Seller and product data from our database\n"
                "• Compliance improvement suggestions\n\n"
                "How can I assist you with product compliance today?")
    
    try:
        # Create agent if not exists
        if _db_agent is None:
            _db_agent = create_db_agent()
            if _db_agent is None:
                # Fallback to simple LLM if agent creation fails
                response = llm.invoke(f"User question: {user_message}\n\nProvide a helpful answer about Amazon product compliance or Indian e-commerce regulations.")
                return response.content
        
        # Use agent to answer
        result = _db_agent.invoke({"input": user_message})
        response_text = result.get('output', 'I apologize, but I encountered an issue processing your request.')
        
        print(f"[CHATBOT] SUCCESS: Response generated ({len(response_text)} chars)")
        return response_text
    
    except Exception as e:
        print(f"[ERROR] Chatbot error: {e}")
        return (f"I apologize, but I encountered an error: {str(e)}\n\n"
                "I can help you with:\n"
                "• Product compliance ratings and analysis\n"
                "• Indian Legal Metrology requirements for different product categories\n"
                "• Seller activity and heatmap data\n"
                "• Compliance improvement recommendations")

# ==================== BATCH ANALYSIS ====================
def batch_analyze_products(product_ids: List[int]) -> Dict[str, Any]:
    """
    Analyze multiple products in batch
    Useful for sellers with multiple listings
    """
    print(f"[BATCH] Analyzing {len(product_ids)} products")
    
    results = []
    summary = {
        'total': len(product_ids),
        'analyzed': 0,
        'failed': 0,
        'grades': {},
        'average_score': 0
    }
    
    for pid in product_ids:
        try:
            report = analyze_compliance(pid)
            if 'error' not in report:
                results.append(report)
                summary['analyzed'] += 1
                grade = report['compliance_grade']
                summary['grades'][grade] = summary['grades'].get(grade, 0) + 1
                summary['average_score'] += report['compliance_score']
            else:
                summary['failed'] += 1
        except Exception as e:
            print(f"[BATCH] Failed to analyze product {pid}: {e}")
            summary['failed'] += 1
    
    if summary['analyzed'] > 0:
        summary['average_score'] /= summary['analyzed']
        summary['average_score'] = round(summary['average_score'], 1)
    
    print(f"[BATCH] SUCCESS: Complete. Analyzed: {summary['analyzed']}, Failed: {summary['failed']}")
    
    return {
        'summary': summary,
        'results': results
    }

# ==================== EXPORT FUNCTIONS ====================
__all__ = [
    'analyze_compliance',
    'analyze_seller_upload',
    'chatbot_agent',
    'batch_analyze_products',
    'LEGAL_METROLOGY_RULES',
    'CATEGORY_SPECIFIC_RULES'
]

if __name__ == '__main__':
    print("[AI COMPLIANCE MODULE] Ready\n")
    
    # ---- DEMO: Try analyzing a product if DB is available ----
    try:
        sample_product_id = 5
        print(f"[DEMO] Running analyze_compliance({sample_product_id})...")
        result = analyze_compliance(sample_product_id)
        print("\n[DEMO RESULT]")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[DEMO] analyze_compliance() could not run: {e}")
    
    # ---- DEMO: Chatbot usage ----
    try:
        print("\n[DEMO] Chatbot test:")
        resp = chatbot_agent("How do I improve product compliance?")
        print(resp)
    except Exception as e:
        print(f"[DEMO] chatbot_agent() failed: {e}")
    
    # ---- DEMO: Batch analysis (IDs 1,2,3 as example) ----
    try:
        print("\n[DEMO] Running batch_analyze_products([6,7,8])...")
        batch = batch_analyze_products([1, 2, 6])
        print(json.dumps(batch, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[DEMO] batch_analyze_products() failed: {e}")
    
    print("\n[AI COMPLIANCE MODULE] Demo complete.")
