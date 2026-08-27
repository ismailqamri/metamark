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

# ==================== INDIAN REGULATORY CRITERIA ====================

REGULATORY_RULES = {
    'food': {
        'critical': [
            {
                'name': 'FSSAI License Number',
                'description': 'Must display valid 14-digit FSSAI license number',
                'weight': -20,
                'regex': r'\b\d{14}\b',
                'keywords': ['FSSAI', 'Lic', 'License']
            },
            {
                'name': 'Expiry/Best Before Date',
                'description': 'Must clearly mention expiry date or best before date',
                'weight': -18,
                'keywords': ['expiry', 'best before', 'use by', 'exp']
            }
        ],
        'major': [
            {
                'name': 'Veg/Non-Veg Symbol',
                'description': 'Should display green dot (veg) or brown dot (non-veg)',
                'weight': -12,
                'keywords': ['vegetarian', 'non-vegetarian', 'veg', 'dot']
            },
            {
                'name': 'Net Quantity',
                'description': 'Must mention net weight/volume',
                'weight': -10,
                'keywords': ['net weight', 'net qty', 'quantity', 'ml', 'gm', 'kg', 'litre']
            },
            {
                'name': 'Nutritional Information',
                'description': 'Should display nutritional facts',
                'weight': -10,
                'keywords': ['nutrition', 'energy', 'protein', 'carbohydrates', 'fat']
            }
        ],
        'minor': [
            {
                'name': 'Ingredients List',
                'description': 'Should list all ingredients',
                'weight': -8,
                'keywords': ['ingredients', 'contains']
            },
            {
                'name': 'Manufacturer Details',
                'description': 'Should display name and address',
                'weight': -6,
                'keywords': ['manufacturer', 'mfg', 'packed by', 'marketed by']
            },
            {
                'name': 'Allergen Information',
                'description': 'Should declare common allergens',
                'weight': -5,
                'keywords': ['allergen', 'contains', 'may contain', 'traces']
            }
        ]
    },
    
    'skincare': {
        'critical': [
            {
                'name': 'Ingredients List',
                'description': 'Must list all ingredients',
                'weight': -20,
                'keywords': ['ingredients', 'composition', 'contains']
            },
            {
                'name': 'Expiry Date',
                'description': 'Must display expiry date or PAO',
                'weight': -18,
                'keywords': ['exp', 'expiry', 'best before', 'pao']
            }
        ],
        'major': [
            {
                'name': 'Manufacturing Date',
                'description': 'Should display manufacturing date',
                'weight': -12,
                'keywords': ['mfg', 'manufactured', 'mfg date', 'dom']
            },
            {
                'name': 'Batch Number',
                'description': 'Should display batch/lot number',
                'weight': -10,
                'keywords': ['batch', 'lot', 'lot no', 'batch no']
            },
            {
                'name': 'Net Quantity',
                'description': 'Must mention net quantity',
                'weight': -8,
                'keywords': ['net', 'quantity', 'weight', 'ml', 'gm', 'volume']
            }
        ],
        'minor': [
            {
                'name': 'External Use Warning',
                'description': 'Should display "For External Use Only"',
                'weight': -6,
                'keywords': ['external use', 'not for internal use', 'topical']
            },
            {
                'name': 'Manufacturer Details',
                'description': 'Should display manufacturer info',
                'weight': -6,
                'keywords': ['manufacturer', 'mfg by', 'made by']
            },
            {
                'name': 'Usage Instructions',
                'description': 'Should provide directions',
                'weight': -4,
                'keywords': ['directions', 'how to use', 'usage', 'apply']
            }
        ]
    },
    
    'electric': {
        'critical': [
            {
                'name': 'BIS/ISI Mark',
                'description': 'Must display BIS certification mark',
                'weight': -22,
                'keywords': ['BIS', 'ISI', 'IS', 'standard mark', 'certification']
            },
            {
                'name': 'Voltage Rating',
                'description': 'Must display voltage rating',
                'weight': -18,
                'keywords': ['voltage', 'V', 'AC', 'DC', '230V', 'volt']
            }
        ],
        'major': [
            {
                'name': 'Power Rating',
                'description': 'Should display power in watts',
                'weight': -12,
                'keywords': ['watt', 'W', 'power', 'kW']
            },
            {
                'name': 'Safety Warnings',
                'description': 'Should display safety instructions',
                'weight': -10,
                'keywords': ['warning', 'caution', 'danger', 'electric shock', 'safety']
            },
            {
                'name': 'Manufacturer Details',
                'description': 'Should display manufacturer info',
                'weight': -10,
                'keywords': ['manufacturer', 'mfg', 'made by', 'produced by']
            }
        ],
        'minor': [
            {
                'name': 'Model Number',
                'description': 'Should display model number',
                'weight': -6,
                'keywords': ['model', 'model no', 'serial', 'SKU']
            },
            {
                'name': 'Warranty Information',
                'description': 'Should mention warranty',
                'weight': -5,
                'keywords': ['warranty', 'guarantee', 'year warranty', 'months warranty']
            },
            {
                'name': 'Country of Origin',
                'description': 'Should mention country of origin',
                'weight': -4,
                'keywords': ['made in', 'product of', 'origin', 'manufactured in']
            }
        ]
    },
    
    'book': {
        'critical': [
            {
                'name': 'ISBN',
                'description': 'Must display ISBN',
                'weight': -15,
                'regex': r'ISBN[:\s]*(?:\d{10}|\d{13})',
                'keywords': ['ISBN']
            },
            {
                'name': 'MRP',
                'description': 'Must display MRP',
                'weight': -15,
                'keywords': ['MRP', 'price', 'Rs', '₹', 'INR']
            }
        ],
        'major': [
            {
                'name': 'Publisher Details',
                'description': 'Should display publisher info',
                'weight': -10,
                'keywords': ['publisher', 'published by', 'publication']
            },
            {
                'name': 'Edition & Year',
                'description': 'Should mention edition and year',
                'weight': -8,
                'keywords': ['edition', 'year', 'published', 'reprint']
            }
        ],
        'minor': [
            {
                'name': 'Copyright Information',
                'description': 'Should display copyright',
                'weight': -5,
                'keywords': ['copyright', '©', 'all rights reserved']
            },
            {
                'name': 'Printer Details',
                'description': 'Should mention printer',
                'weight': -3,
                'keywords': ['printed by', 'printer', 'printed at']
            }
        ]
    },
    
    'amazon': {  # Default/General
        'critical': [
            {
                'name': 'MRP Display',
                'description': 'Must display Maximum Retail Price',
                'weight': -15,
                'keywords': ['MRP', 'price', 'Rs', '₹', 'maximum retail price']
            }
        ],
        'major': [
            {
                'name': 'Manufacturer/Packer Details',
                'description': 'Should display name and address',
                'weight': -10,
                'keywords': ['manufacturer', 'mfg', 'packed by', 'made by', 'importer']
            },
            {
                'name': 'Country of Origin',
                'description': 'Should mention country of origin',
                'weight': -8,
                'keywords': ['made in', 'product of', 'origin', 'manufactured in']
            }
        ],
        'minor': [
            {
                'name': 'Net Quantity',
                'description': 'Should mention quantity/dimensions',
                'weight': -5,
                'keywords': ['net', 'quantity', 'weight', 'dimensions', 'size']
            },
            {
                'name': 'Customer Care',
                'description': 'Should provide contact',
                'weight': -3,
                'keywords': ['customer care', 'contact', 'helpline', 'email', 'phone']
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
    IMPROVED: More aggressive OCR extraction with better prompting
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
            "error": "No images provided",
        }

    rules_map = REGULATORY_RULES
    rules_for_category = rules_map.get(
        category.lower(),
        rules_map.get("amazon", {"critical": [], "major": [], "minor": []}),
    )
    all_rules = (
        rules_for_category["critical"]
        + rules_for_category["major"]
        + rules_for_category["minor"]
    )

    checklist = "\n".join(
        [f"- {rule['name']}: {rule.get('description', '')}" for rule in all_rules]
    )

    # IMPROVED PROMPT - More explicit about comprehensive extraction
    prompt = f"""You are an OCR expert analyzing product packaging for Indian regulatory compliance.

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

IMPORTANT RULES:
1. Mark as "present" ONLY if the requirement is clearly and completely fulfilled
2. Mark as "partial" if information exists but is incomplete, unclear, or low quality
3. Mark as "missing" if you cannot find it anywhere in the images
4. For text extraction, capture EVERYTHING - don't leave out details
5. For addresses, capture the COMPLETE address including street, city, state, pincode
6. For prices, look for "MRP", "Price", "Rs.", "₹" symbols
7. For manufacturer info, look for "Mfd. by", "Packed by", "Marketed by", "Imported by"

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
                        "data": base64.b64encode(blob).decode("utf-8"),
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
                "error": "All images failed to encode",
            }

        # Call Gemini with improved configuration
        generation_config = genai.types.GenerationConfig(
            temperature=0.1,  # Low temperature for consistent extraction
            top_p=0.95,
            top_k=40,
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
                "error": "Empty response from AI model",
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
                "confidence_score": 0.3,
            }

        log(f"[OCR] SUCCESS: Extracted {len(ocr_results.get('extracted_text', ''))} characters")
        log(f"[OCR] Found {len(ocr_results.get('findings', []))} compliance items")
        
        return {
            "extracted_text": ocr_results.get("extracted_text", ""),
            "visual_findings": ocr_results.get("findings", []),
            "symbols_found": ocr_results.get("symbols_found", []),
            "image_quality": ocr_results.get("image_quality", "unknown"),
            "confidence_score": ocr_results.get("confidence_score", 0.5),
            "ocr_success": True,
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
            "error": str(e),
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
    COMPREHENSIVE VERSION: Flattens entire JSON and searches everywhere.
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

    rules_map = REGULATORY_RULES
    rules_for_category = rules_map.get(
        category.lower(),
        rules_map.get("amazon", {"critical": [], "major": [], "minor": []}),
    )
    all_rules = (
        rules_for_category["critical"]
        + rules_for_category["major"]
        + rules_for_category["minor"]
    )

    checklist = "\n".join(
        [
            f"- {rule['name']}: {rule.get('description', '')} "
            f"(Keywords: {', '.join(rule.get('keywords', []))})"
            for rule in all_rules
        ]
    )

    prompt = f"""
You are an expert in Indian product regulatory compliance for {category.upper()} products.

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
- For Country of Origin: Look for "Country of origin", "Made in", "Manufactured in", country names
- For Warranty: Look for "warranty", "guarantee", year/month references
- For Manufacturer: Look for "manufacturer", "made by", "produced by", company addresses
- For Power Rating: Look for "W", "watts", "watt", "power adapter", numbers followed by W
- For Voltage: Look for "V", "volt", "voltage", "input", numbers with V
- For Model Number: Look for "model", "version", "gen", product codes
- For Weight/Dimensions: Look for "kg", "g", "mm", "cm", measurements
- For BIS/ISI: Look for "BIS", "ISI", "certification", "license"

EXAMPLES FROM THIS PRODUCT:
SUCCESS: "Country of origin > text: China" → Country of Origin: status="present", value="China", adequacy="adequate"
SUCCESS: "Warranty and service > text: 1-year limited warranty" → Warranty: status="present", value="1-year limited warranty", adequacy="adequate"  
SUCCESS: "Name and Address of Manufacturer > text: [full address]" → Manufacturer: status="present", adequacy="adequate"
SUCCESS: "Included in the box > text: power adapter (30W)" → Power Rating: status="present", value="30W", adequacy="adequate"

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
                "recommendations": ["Please try analyzing again"],
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
                "recommendations": ["Ensure product description contains all required information"],
            }

        # DEBUG: Print what AI found
        log(f"[DATA ANALYSIS DEBUG] AI returned {len(analysis_results.get('findings', []))} findings:")
        for f in analysis_results.get("findings", [])[:10]:  # Show first 10
            status = f.get("status", "?")
            adequacy = f.get("adequacy", "?")
            value = f.get("extracted_value", "")
            found_in = f.get("found_in", "")
            log(f"  • {f.get('requirement', 'Unknown')}: status={status}, adequacy={adequacy}")
            log(f"    └─ value='{value[:60]}...' from: {found_in[:50]}")

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
            "error": str(e),
        }

# ==================== COMPLIANCE SCORING ====================
from typing import Tuple

def _infer_severity_and_penalty(
    category: str,
    rule: Dict[str, Any],
    ocr_finding: Optional[Dict[str, Any]],
    data_finding: Optional[Dict[str, Any]],
) -> Tuple[str, float]:
    """
    Ask the model to dynamically determine severity and penalty weight.
    """
    base_description = rule.get("description", "")
    requirement_name = rule.get("name", "")
    
    ocr_status = ocr_finding.get("status", "missing") if ocr_finding else "missing"
    data_status = data_finding.get("status", "missing") if data_finding else "missing"
    
    # Check if present in EITHER source
    if ocr_status == "present" or data_status == "present":
        return "minor", 0.0
    
    # Check data adequacy
    if data_finding:
        data_adequacy = data_finding.get("adequacy", "unclear")
        if data_adequacy == "adequate":
            return "minor", 0.0
    
    # Check for extracted values
    ocr_value = ocr_finding.get("extracted_value", "") if ocr_finding else ""
    data_value = data_finding.get("extracted_value", "") if data_finding else ""
    
    excluded_values = ["n/a", "not found", "missing", "none", "not available", "na"]
    if (ocr_value and ocr_value.lower() not in excluded_values) or \
       (data_value and data_value.lower() not in excluded_values):
        is_partial = True
    else:
        is_partial = (ocr_status in ["unclear", "partial"] or data_status in ["partial"])

    prompt = f"""
You are grading regulatory compliance for Indian {category.upper()} products.

Requirement: {requirement_name}
Description: {base_description}

OCR finding: {ocr_status} (value: "{ocr_value}")
Data finding: {data_status} (adequacy: {data_finding.get('adequacy', 'N/A') if data_finding else 'N/A'}, value: "{data_value}")

Decide:
1. Severity: "critical", "major", or "minor"
2. Penalty values (negative numbers):
   - Full penalty if completely missing: -15 to -25 (critical), -8 to -15 (major), -3 to -8 (minor)
   - Partial penalty if partially present: 30-50% of full penalty

Return ONLY valid JSON (no markdown):
{{
  "severity": "critical|major|minor",
  "penalty_if_missing": -20.0,
  "penalty_if_partial": -6.0
}}
"""

    try:
        response = llm.invoke(prompt)
        content = (response.content or "").strip()
        content = _strip_json_fence(content)
        data = json.loads(content)
        
        severity = data.get("severity", "major")
        if severity not in ["critical", "major", "minor"]:
            severity = "major"
        
        penalty_missing = float(data.get("penalty_if_missing", -10.0))
        penalty_partial = float(data.get("penalty_if_partial", penalty_missing * 0.4))
        
        # Return appropriate penalty
        if is_partial:
            return severity, penalty_partial
        else:
            return severity, penalty_missing

    except Exception as e:
        log(f"[SCORING] Dynamic severity/penalty inference failed: {e}")
        # Fallback with adjusted penalties
        if is_partial:
            return "major", -4.0
        else:
            return "major", -10.0


def calculate_compliance_score(
    ocr_results: Dict[str, Any],
    data_analysis: Dict[str, Any],
    category: str,
) -> Dict[str, Any]:
    """
    FIXED VERSION: Comprehensive status checking with multiple fallbacks.
    """
    log(f"[SCORING] Calculating compliance score for category: {category}")
    rules_map = REGULATORY_RULES
    rules_for_category = rules_map.get(
        category.lower(),
        rules_map.get("amazon", {"critical": [], "major": [], "minor": {}}),
    )
    all_rules = (
        rules_for_category["critical"]
        + rules_for_category["major"]
        + rules_for_category["minor"]
    )

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

    # Process each rule
    for rule in all_rules:
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
        
        # Method 3: Has meaningful extracted value (not empty, not "N/A", not "Not found")
        excluded_values = ["n/a", "not found", "missing", "none", "not available", "na", ""]
        if ocr_value and len(ocr_value) > 2 and ocr_value.lower() not in excluded_values:
            is_present = True
        if data_value and len(data_value) > 2 and data_value.lower() not in excluded_values:
            is_present = True
        
        # Method 4: Status is not explicitly "missing"
        if ocr_status not in ["missing", ""] or data_status not in ["missing", ""]:
            # Even if marked as "unclear" or "partial", if there's a value, consider it present
            if (ocr_value and ocr_value.lower() not in excluded_values) or \
               (data_value and data_value.lower() not in excluded_values):
                is_present = True
        
        log(f"[SCORING DEBUG] {requirement_name}:")
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

        # Get severity and penalty
        severity, penalty = _infer_severity_and_penalty(
            category, rule, ocr_finding, data_finding
        )

        # Reduce penalty for partial
        if is_partial:
            penalty = penalty * 0.4
            violation_type = "partial"
        else:
            violation_type = "missing"

        total_score += penalty
        violations.append({
            "type": violation_type,
            "severity": severity,
            "requirement": requirement_name,
            "penalty": penalty,
            "description": rule.get("description", ""),
            "ocr_status": ocr_status,
            "data_status": data_status,
            "data_adequacy": data_adequacy,
        })
        penalized_requirements.add(requirement_name)

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

    critical_violations = [v for v in violations if v["severity"] == "critical"]
    major_violations = [v for v in violations if v["severity"] == "major"]
    minor_violations = [v for v in violations if v["severity"] == "minor"]

    log(
        f"[SCORING] SUCCESS: Final Score: {total_score:.1f}/100 | Grade: {grade}. "
        f"Critical: {len(critical_violations)}, "
        f"Major: {len(major_violations)}, Minor: {len(minor_violations)}"
    )

    return {
        "score": round(total_score, 1),
        "grade": grade,
        "violations": violations,
        "violation_summary": {
            "critical": len(critical_violations),
            "major": len(major_violations),
            "minor": len(minor_violations),
            "total": len(violations),
        },
    }

# ==================== RECOMMENDATIONS GENERATOR ====================

def generate_recommendations(violations: List[Dict], ocr_results: Dict, data_analysis: Dict, category: str) -> List[str]:
    """
    Generate SMARTER recommendations based on violation type
    """
    if not category:
        category = 'amazon'
    
    recommendations = []
    
    # Separate by violation type
    missing_violations = [v for v in violations if v.get('type') == 'missing']
    partial_violations = [v for v in violations if v.get('type') == 'partial']
    
    critical_missing = [v for v in missing_violations if v.get('severity') == 'critical']
    major_missing = [v for v in missing_violations if v.get('severity') == 'major']
    minor_missing = [v for v in missing_violations if v.get('severity') == 'minor']
    
    # Critical actions
    if critical_missing:
        recommendations.append("🚨 CRITICAL ACTIONS REQUIRED:")
        for v in critical_missing:
            recommendations.append(f"   • Add: {v.get('requirement', 'Unknown')}")
    
    # Major improvements
    if major_missing:
        recommendations.append("\nWARNING:️  IMPORTANT IMPROVEMENTS:")
        for v in major_missing:
            recommendations.append(f"   • Include: {v.get('requirement', 'Unknown')}")
    
    # Partial items need completion
    if partial_violations:
        recommendations.append("\n📋 COMPLETE THESE ITEMS:")
        for v in partial_violations:
            recommendations.append(f"   • Improve visibility/clarity: {v.get('requirement', 'Unknown')}")
    
    # Minor suggestions
    if minor_missing and len(recommendations) < 15:  # Don't overwhelm with too many
        recommendations.append("\n💡 ADDITIONAL SUGGESTIONS:")
        for v in minor_missing[:5]:  # Limit to 5
            recommendations.append(f"   • Consider adding: {v.get('requirement', 'Unknown')}")
    
    # Image quality tips
    if len(ocr_results.get('visual_findings', [])) < 3:
        recommendations.append("\n📸 IMAGE TIPS:")
        recommendations.append("   • Upload clear photos of product labels")
        recommendations.append("   • Include front, back, and side label images")
    
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
            'requires_action': len([v for v in scoring['violations'] if v.get('severity') == 'critical']) > 0,
            'log':LOG_BUFFER
        }
        
        # # Update database with compliance results
        # try:
        #     cursor.execute("""
        #         UPDATE Products 
        #         SET analysis_results = %s,
        #             rating = %s,
        #             remarks = %s,
        #             last_analysed = %s
        #         WHERE product_id = %s
        #     """, (
        #         json.dumps(compliance_report),
        #         scoring['score'],
        #         f"Grade: {scoring['grade']} | Violations: {scoring['violation_summary']['total']}",
        #         datetime.now(),
        #         product_id
        #     ))
            
        #     connection.commit()
        #     log(f"[COMPLIANCE] Analysis complete and saved to database")
        # except Error as e:
        #     log(f"[WARNING] Failed to save compliance report to DB: {e}")
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

# ==================== SELLER UPLOAD ANALYSIS ====================

def analyze_seller_upload(images: List[bytes], product_data: Dict[str, Any], category: str = 'amazon') -> Dict[str, Any]:
    """
    Analyze seller's product BEFORE uploading to Amazon
    Provides instant feedback on compliance
    
    Args:
        images: List of image bytes
        product_data: Dictionary with title, description, features, etc.
        category: Product category (auto-detected if not provided)
        
    Returns:
        Instant compliance report with recommendations
    """
    # Fix ERROR 3: Handle None category
    if not category:
        category = 'amazon'
    
    log(f"\n[SELLER UPLOAD CHECK] Analyzing upload for category: {category}")
    
    try:
        # Validate inputs
        if not images:
            return {
                'error': 'No images provided',
                'compliance_score': 0,
                'compliance_grade': 'F',
                'ready_for_upload': False
            }
        
        # Ensure product_data has safe defaults
        safe_product_data = {
            'title': product_data.get('title', '') or '',
            'description': product_data.get('description', '') or '',
            'feature_bullets': product_data.get('feature_bullets', []) or [],
            'product_details': product_data.get('product_details', {}) or {},
            'specifications': product_data.get('specifications', {}) or {},
            'seller_information': product_data.get('seller_information', {}) or {}
        }
        
        # Step 1: OCR and Visual Analysis
        ocr_results = analyze_images_with_ocr(images, category)
        
        # Step 2: Text Data Analysis
        data_analysis = analyze_product_data(safe_product_data, category)
        
        # Step 3: Calculate Compliance Score
        scoring = calculate_compliance_score(ocr_results, data_analysis, category)
        
        # Step 4: Generate Recommendations
        recommendations = generate_recommendations(
            scoring['violations'],
            ocr_results,
            data_analysis,
            category
        )
        
        # Compile instant feedback report
        feedback_report = {
            'category': category,
            'analysis_date': datetime.now().isoformat(),
            'compliance_score': scoring['score'],
            'compliance_grade': scoring['grade'],
            'violation_summary': scoring['violation_summary'],
            'critical_issues': [v for v in scoring['violations'] if v.get('severity') == 'critical'],
            'major_issues': [v for v in scoring['violations'] if v.get('severity') == 'major'],
            'minor_issues': [v for v in scoring['violations'] if v.get('severity') == 'minor'],
            'image_analysis': {
                'quality': ocr_results.get('image_quality', 'unknown'),
                'confidence': ocr_results.get('confidence_score', 0.0),
                'symbols_found': ocr_results.get('symbols_found', [])
            },
            'recommendations': recommendations,
            'ready_for_upload': scoring['score'] >= 70 and len([v for v in scoring['violations'] if v.get('severity') == 'critical']) == 0,
            'estimated_approval_chance': 'High' if scoring['score'] >= 85 else 'Medium' if scoring['score'] >= 70 else 'Low'
        }
        
        print(f"[SELLER UPLOAD CHECK] SUCCESS: Score: {scoring['score']}/100 | Grade: {scoring['grade']}")
        print(f"[SELLER UPLOAD CHECK] Ready for upload: {feedback_report['ready_for_upload']}")
        
        return feedback_report
        
    except Exception as e:
        print(f"[ERROR] Seller upload analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'error': str(e),
            'traceback': traceback.format_exc(),
            'compliance_score': 0,
            'compliance_grade': 'F',
            'ready_for_upload': False
        }

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
3. Answer questions about Indian e-commerce regulations and compliance requirements
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
                "• Indian regulatory requirements\n"
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
                "• Indian regulatory requirements for different product categories\n"
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
    'REGULATORY_RULES'
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
