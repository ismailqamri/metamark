#!/usr/bin/env python3
"""
RAG (Retrieval-Augmented Generation) Enhancement for Compliance System
Reduces hallucinations by grounding AI responses in verified regulatory documents
"""

import os
import json
import pickle
from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np

# Vector store and embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain.chains import RetrievalQA
from langchain_google_genai import ChatGoogleGenerativeAI

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from langchain_core._api.deprecation import LangChainDeprecationWarning
warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)

from dotenv import load_dotenv

load_dotenv()

# ==================== CONFIGURATION ====================

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
VECTOR_STORE_PATH = "./vector_stores/legal_metrology_db"
KNOWLEDGE_BASE_PATH = "./knowledge_base"

# Initialize embeddings and LLM
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GOOGLE_API_KEY
)

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.1,  # Lower temperature for more factual responses
    convert_system_message_to_human=True
)

# ==================== LEGAL METROLOGY KNOWLEDGE BASE ====================

LEGAL_METROLOGY_DOCS = {
    "rule_6_declarations": """
    Legal Metrology (Packaged Commodities) Rules, 2011 - Rule 6: Declarations on Packages
    
    Every package shall bear the following declarations:
    
    (a) Name and address of the manufacturer, or where the manufacturer is not the packer, the name and address of the manufacturer and packer, or where the commodity is imported, the name and address of the importer.
    
    (b) Common or generic name of the commodity packed.
    
    (c) Net quantity in terms of standard unit of weight or measure in accordance with the provisions of rule 13.
    
    (d) Month and year in which the commodity is manufactured or pre-packaged or imported.
    
    (da) "Best Before" or "Use By Date" in case of a commodity whose deterioration is likely to take place within a period of thirty days.
    
    (e) Maximum retail price at which the commodity in packaged form may be sold to the ultimate consumer, including all taxes, freight, transport charges, commission payable to dealers, and all charges towards advertisement, delivery, packing, forwarding and the like, indicated as "Maximum Retail Price Rs. _____ (incl. of all taxes)".
    
    (f) Dimensions (length, breadth, and height) in case of packages containing commodities like bed-sheets, towels, etc.
    
    (g) Unit sale price in terms of rupees per kilogram, litre, meter, piece or number as the case may be (mandatory from 01.04.2022).
    
    (2) Customer care details: Name, telephone number, and e-mail address for consumer complaints.
    
    (4A) Barcode, GTIN, or QR code may be used for additional information including declarations.
    
    (8) In case of food products: Green dot for vegetarian products, brown or red dot for non-vegetarian products on the top of principal display panel.
    """,
    
    "rule_7_principal_display_panel": """
    Legal Metrology (Packaged Commodities) Rules, 2011 - Rule 7: Principal Display Panel
    
    All declarations specified in rule 6 shall be made on the principal display panel or on any other panel which is clearly visible and easily accessible to the consumer.
    
    The principal display panel means that part of the label on a package which is intended or is likely to be displayed, presented, shown or examined by the consumer under normal and customary conditions of display for retail sale.
    
    Declarations must be:
    - In Hindi (Devanagari script) or English language
    - Clearly legible and conspicuous
    - In contrasting color to the background
    - Not hidden, obscured, or interrupted by other printed or graphic matter
    """,
    
    "rule_9_language_requirements": """
    Legal Metrology (Packaged Commodities) Rules, 2011 - Rule 9: Language
    
    Every declaration on a package shall be in Hindi in Devanagari script or in English:
    
    Provided that where any declaration is in Hindi in Devanagari script, the same shall also be in English:
    
    Provided further that where the packages are intended for sale in any area where Hindi in Devanagari script or English is not generally used, the said declaration may be in the language of that area in addition to the said Hindi in Devanagari script or English.
    """,
    
    "rule_13_net_quantity": """
    Legal Metrology (Packaged Commodities) Rules, 2011 - Rule 13: Net Quantity Declaration
    
    The net quantity of the commodity in a package shall be declared in accordance with the Standard Units of Weights and Measures as notified under section 15 of the Act:
    
    Weight Units:
    - Milligram (mg), Gram (g), Kilogram (kg)
    
    Volume Units:
    - Millilitre (ml), Litre (L or l)
    
    Length Units:
    - Millimetre (mm), Centimetre (cm), Metre (m)
    
    Area Units:
    - Square centimetre (sq cm), Square metre (sq m)
    
    Number or Piece:
    - May be declared by number or piece
    
    The net quantity shall be declared in the manner such that the numerals are in the same line horizontally and are in bold, conspicuous and in contrasting color.
    
    Imperial units (like ounces, pounds, inches) are NOT permitted.
    """,
    
    "rule_18_mrp_compliance": """
    Legal Metrology (Packaged Commodities) Rules, 2011 - Rule 18: Maximum Retail Price
    
    No person shall sell or offer for sale or distribute any packaged commodity at a price exceeding the retail sale price declared on the package.
    
    The MRP must include:
    1. The words "Maximum Retail Price" or "MRP"
    2. The actual price in Indian Rupees
    3. The phrase "incl. of all taxes" or "inclusive of all taxes"
    
    Format: "MRP Rs. XX.XX (incl. of all taxes)" or "Maximum Retail Price Rs. XX.XX inclusive of all taxes"
    
    The MRP shall be prominently displayed and shall not be obliterated, removed, or altered.
    """,
    
    "fssai_requirements": """
    FSSAI (Food Safety and Standards Authority of India) Requirements for Food Products:
    
    1. FSSAI License Number: 14-digit license number mandatory for all food businesses
    
    2. Nutritional Information: Energy value, protein, carbohydrates, fat per 100g/100ml
    
    3. Ingredients List: All ingredients in descending order by weight/volume
    
    4. Allergen Declaration: Must declare common allergens (peanuts, tree nuts, milk, eggs, fish, shellfish, soy, wheat, sesame)
    
    5. Veg/Non-Veg Symbol:
       - Green dot inside green square for vegetarian
       - Brown/red dot inside brown/red square for non-vegetarian
       - Must be on top of principal display panel
    
    6. Best Before/Use By Date: Mandatory for perishable foods
    
    7. Storage Instructions: Required for foods requiring specific storage
    
    8. Claims: Any nutritional or health claims must be as per FSSAI regulations
    """,
    
    "bis_certification": """
    BIS (Bureau of Indian Standards) Certification for Electrical/Electronic Products:
    
    Mandatory BIS certification (ISI Mark) required for:
    - Electrical appliances and accessories
    - Electronics and IT equipment
    - LPG cylinders and valves
    - Cement and steel products
    - Automotive components
    
    The BIS certification mark (ISI Mark) must be:
    1. Clearly visible on the product and/or packaging
    2. Include license number
    3. Include the relevant IS standard number
    
    Format: ISI Mark + License Number + IS Standard Number
    
    For electrical products, voltage rating (e.g., 230V AC) is mandatory.
    Power rating in Watts (W) or Kilowatts (kW) should be displayed.
    """,
    
    "cosmetics_drugs_rules": """
    Drugs and Cosmetics Rules, 1945 - Requirements for Cosmetics and Skincare:
    
    1. Manufacturer License Number: Required for cosmetics manufacturers
    
    2. Ingredients List: Complete list of ingredients (INCI names preferred)
    
    3. Manufacturing Date: Month and year of manufacture
    
    4. Expiry Date or PAO (Period After Opening):
       - Expiry date for products with shelf life < 30 months
       - PAO symbol (open jar with number of months) for products with shelf life > 30 months
    
    5. Batch Number: For traceability
    
    6. Net Quantity: In metric units (ml, g, kg)
    
    7. MRP: With "incl. of all taxes"
    
    8. Usage Warnings:
       - "For External Use Only" for topical products
       - Specific warnings if required (e.g., patch test, keep away from eyes)
    
    9. Import Details: If imported, name and address of importer
    
    10. Veg/Non-Veg Symbol: If product contains animal-derived ingredients
    """,
    
    "ecommerce_guidelines": """
    E-Commerce Guidelines for Product Listings (India):
    
    1. Country of Origin: Mandatory declaration for all products sold online (Govt. notification 2020)
    
    2. Product Description: Must be accurate and not misleading
    
    3. Images: Must represent actual product, not misleading
    
    4. Customer Care: Contact details must be clearly provided
    
    5. Return/Refund Policy: Must be clearly stated
    
    6. Warranty Information: If applicable, warranty terms must be clear
    
    7. Seller Details: Name and address of seller must be available
    
    8. Generic Name: Common or generic name of product must be visible
    
    9. All Legal Metrology declarations must be clearly visible in product images or description
    """,
    
    "common_violations": """
    Common Legal Metrology Violations and Penalties:
    
    1. MISSING "incl. of all taxes" with MRP
       - Violation: Not including mandatory phrase
       - Penalty: Can attract fines and product seizure
    
    2. Using Imperial Units (oz, lb, inch)
       - Violation: Only metric units permitted in India
       - Penalty: Non-compliance with Rule 13
    
    3. Incomplete Manufacturer Address
       - Violation: Must include complete address with PIN code
       - Penalty: Violation of Rule 6(a)
    
    4. Missing Manufacturing Date
       - Violation: Month and year mandatory
       - Penalty: Violation of Rule 6(d)
    
    5. Declarations Not on Principal Display Panel
       - Violation: Critical information hidden or on back only
       - Penalty: Violation of Rule 7
    
    6. Illegible or Too Small Font
       - Violation: Font size requirements not met
       - Penalty: Makes declarations ineffective
    
    7. Selling Above MRP
       - Violation: Exceeding declared MRP
       - Penalty: Fine up to Rs. 25,000 or imprisonment
    
    8. Missing FSSAI License (Food Products)
       - Violation: Operating without valid license
       - Penalty: High fines, closure of business
    
    9. Missing BIS Mark (Notified Products)
       - Violation: Selling without mandatory certification
       - Penalty: Product ban, fines
    """,
    
    "qr_code_regulations": """
    QR Code Usage in Product Packaging (Legal Metrology):
    
    Rule 6(4A) - QR Code and Digital Information:
    
    1. QR codes or barcodes MAY be used for additional information
    
    2. However, CRITICAL declarations must STILL be printed on the package:
       - MRP (with "incl. of all taxes")
       - Net quantity
       - Manufacturer name and address
       - Manufacturing date
    
    3. QR codes can contain:
       - Detailed product information
       - Nutritional information (supplementary)
       - Batch/lot traceability
       - Warranty registration
       - Usage instructions
       - Consumer grievance redressal portal
    
    4. QR codes CANNOT replace mandatory printed declarations
    
    5. If using QR for supplementary info, physical package must still have all Rule 6 declarations clearly printed
    
    Important: Even if QR code contains all information, physical printing of mandatory declarations is required under current Legal Metrology Rules.
    """
}

# ==================== VECTOR STORE MANAGEMENT ====================

class LegalMetrologyRAG:
    """RAG system for Legal Metrology compliance queries"""
    
    def __init__(self):
        self.vector_store = None
        self.retriever = None
        self.qa_chain = None
        self._initialize_vector_store()
    
    def _initialize_vector_store(self):
        """Initialize or load vector store"""
        try:
            # Try to load existing vector store
            if os.path.exists(VECTOR_STORE_PATH):
                print("[RAG] Loading existing vector store...")
                self.vector_store = FAISS.load_local(
                    VECTOR_STORE_PATH, 
                    embeddings,
                    allow_dangerous_deserialization=True
                )
                print("[RAG] SUCCESS: Vector store loaded")
            else:
                print("[RAG] Creating new vector store from knowledge base...")
                self._create_vector_store()
            
            # Create retriever
            self.retriever = self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 5}  # Retrieve top 5 most relevant chunks
            )
            
            # Create QA chain
            self._create_qa_chain()
            
        except Exception as e:
            print(f"[ERROR] Failed to initialize RAG system: {e}")
            import traceback
            traceback.print_exc()
    
    def _create_vector_store(self):
        """Create vector store from Legal Metrology documents"""
        try:
            # Create documents from knowledge base
            documents = []
            for doc_id, content in LEGAL_METROLOGY_DOCS.items():
                documents.append(Document(
                    page_content=content,
                    metadata={"source": doc_id, "type": "legal_regulation"}
                ))
            
            # Split documents into chunks
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
            
            split_docs = text_splitter.split_documents(documents)
            print(f"[RAG] Created {len(split_docs)} document chunks")
            
            # Create vector store
            self.vector_store = FAISS.from_documents(split_docs, embeddings)
            
            # Save vector store
            os.makedirs(os.path.dirname(VECTOR_STORE_PATH), exist_ok=True)
            self.vector_store.save_local(VECTOR_STORE_PATH)
            print(f"[RAG] SUCCESS: Vector store saved to {VECTOR_STORE_PATH}")
            
        except Exception as e:
            print(f"[ERROR] Failed to create vector store: {e}")
            raise
    
    def _create_qa_chain(self):
        """Create QA chain with retriever"""
        try:
            from langchain.chains import RetrievalQA
            from langchain_core.prompts import PromptTemplate
            
            prompt_template = """You are an expert on Indian Legal Metrology (Packaged Commodities) Rules, 2011.

Use the following pieces of context from the legal regulations to answer the question accurately.
If you don't know the answer based on the context, say "I don't have enough information in the Legal Metrology regulations to answer this."

DO NOT make up information. Only use what's in the context provided.

Context:
{context}

Question: {question}

Accurate Answer based on Legal Metrology Rules:"""

            PROMPT = PromptTemplate(
                template=prompt_template, 
                input_variables=["context", "question"]
            )
            
            self.qa_chain = RetrievalQA.from_chain_type(
                llm=llm,
                chain_type="stuff",
                retriever=self.retriever,
                return_source_documents=True,
                chain_type_kwargs={"prompt": PROMPT}
            )
            
            print("[RAG] SUCCESS: QA chain created")
            
        except Exception as e:
            print(f"[ERROR] Failed to create QA chain: {e}")
            raise
    
    def query(self, question: str) -> Dict[str, Any]:
        """Query the RAG system with grounded responses"""
        try:
            if not self.qa_chain:
                return {
                    "answer": "RAG system not initialized",
                    "sources": [],
                    "confidence": 0.0
                }
            
            # Get answer with sources
            result = self.qa_chain.invoke({"query": question})
            
            # Extract source documents
            sources = []
            for doc in result.get("source_documents", []):
                sources.append({
                    "content": doc.page_content[:200] + "...",
                    "source": doc.metadata.get("source", "unknown")
                })
            
            return {
                "answer": result["result"],
                "sources": sources,
                "confidence": self._estimate_confidence(result)
            }
            
        except Exception as e:
            print(f"[ERROR] RAG query failed: {e}")
            return {
                "answer": f"Error processing query: {str(e)}",
                "sources": [],
                "confidence": 0.0
            }
    
    def _estimate_confidence(self, result: Dict) -> float:
        """Estimate confidence based on retrieved documents"""
        source_docs = result.get("source_documents", [])
        if not source_docs:
            return 0.3
        
        # Higher confidence if multiple relevant sources found
        num_sources = len(source_docs)
        if num_sources >= 3:
            return 0.95
        elif num_sources >= 2:
            return 0.85
        else:
            return 0.75
    
    def get_relevant_rules(self, compliance_type: str) -> List[str]:
        """Get relevant rules for specific compliance checks"""
        try:
            query_map = {
                "mrp": "What are the rules for MRP declaration on packages?",
                "net_quantity": "What are the net quantity declaration requirements?",
                "manufacturer": "What are the manufacturer/packer address requirements?",
                "dates": "What are the manufacturing and expiry date requirements?",
                "fssai": "What are the FSSAI requirements for food products?",
                "bis": "What are the BIS certification requirements?",
                "qr_code": "Can QR codes be used for declarations?"
            }
            
            query = query_map.get(compliance_type.lower(), f"What are the requirements for {compliance_type}?")
            result = self.query(query)
            
            return [result["answer"]]
            
        except Exception as e:
            print(f"[ERROR] Failed to get relevant rules: {e}")
            return []

# ==================== ENHANCED COMPLIANCE FUNCTIONS WITH RAG ====================

# Global RAG instance
_rag_system = None

def get_rag_system() -> LegalMetrologyRAG:
    """Get or create RAG system singleton"""
    global _rag_system
    if _rag_system is None:
        _rag_system = LegalMetrologyRAG()
    return _rag_system

def rag_enhanced_ocr_analysis(image_blobs: List[bytes], category: str, ocr_results: Dict) -> Dict[str, Any]:
    """Enhance OCR analysis with RAG-retrieved regulations"""
    try:
        rag = get_rag_system()
        
        # Get relevant regulations for this category
        category_query = f"What are the mandatory labeling requirements for {category} products in India under Legal Metrology Rules?"
        regulations = rag.query(category_query)
        
        # Enhance OCR findings with regulatory context
        enhanced_findings = []
        for finding in ocr_results.get('visual_findings', []):
            requirement = finding.get('requirement', '')
            
            # Get specific rule for this requirement
            rule_query = f"What does Legal Metrology Rule say about {requirement}?"
            rule_info = rag.query(rule_query)
            
            finding['regulatory_reference'] = rule_info['answer'][:300]
            finding['confidence'] = rule_info['confidence']
            enhanced_findings.append(finding)
        
        return {
            **ocr_results,
            'visual_findings': enhanced_findings,
            'regulatory_context': regulations['answer'],
            'rag_enhanced': True
        }
        
    except Exception as e:
        print(f"[WARNING] RAG enhancement failed: {e}")
        return ocr_results

def rag_enhanced_recommendations(violations: List[Dict], category: str, qr_present: bool = False) -> List[str]:
    """Generate recommendations grounded in actual regulations"""
    try:
        rag = get_rag_system()
        recommendations = []
        
        # Declaration-type keywords (ignored if QR exists)
        declaration_keywords = [
            'MRP', 'Net Quantity', 'Manufacturer', 'Address', 'Batch', 'Expiry',
            'Best Before', 'Manufacturing Date', 'Customer Care', 'Ingredients',
            'Nutritional', 'Country of Origin', 'Unit Sale Price'
        ]
        
        # Filter violations if QR is present
        filtered_violations = violations
        if qr_present:
            filtered_violations = [
                v for v in violations
                if not any(k.lower() in v.get('requirement', '').lower() for k in declaration_keywords)
            ]
        
        # Group violations by severity
        critical_violations = [v for v in filtered_violations if v.get('severity') == 'critical']
        major_violations = [v for v in filtered_violations if v.get('severity') == 'major']
        
        # Get detailed regulatory guidance for critical violations
        if critical_violations:
            recommendations.append("\n📚 REGULATORY COMPLIANCE DETAILS:")
            
            for violation in critical_violations[:3]:  # Limit to top 3 for readability
                requirement = violation.get('requirement', '')
                
                # Get exact regulation
                rule_query = f"What is the exact Legal Metrology Rule requirement for {requirement}?"
                rule_info = rag.query(rule_query)
                
                if rule_info['confidence'] > 0.7:
                    recommendations.append(f"\n  • {requirement}:")
                    recommendations.append(f"    {rule_info['answer'][:250]}...")
        
        # Get category-specific compliance guidance
        if filtered_violations:
            guidance_query = f"What are the key compliance requirements for {category} products under Legal Metrology Rules?"
            guidance = rag.query(guidance_query)
            
            if guidance['confidence'] > 0.7:
                recommendations.append(f"\n📖 CATEGORY-SPECIFIC GUIDANCE ({category.upper()}):")
                recommendations.append(f"  {guidance['answer'][:300]}...")
        
        # Add penalty information for serious violations
        if critical_violations or major_violations:
            penalty_query = "What are the penalties for Legal Metrology violations in India?"
            penalty_info = rag.query(penalty_query)
            
            if penalty_info['confidence'] > 0.7:
                recommendations.append(f"\n⚖️ NON-COMPLIANCE CONSEQUENCES:")
                recommendations.append(f"  {penalty_info['answer'][:200]}...")
        
        return recommendations
        
    except Exception as e:
        print(f"[WARNING] RAG-enhanced recommendations failed: {e}")
        import traceback
        traceback.print_exc()
        return []

def rag_chatbot(user_message: str) -> Dict[str, Any]:
    """RAG-enhanced chatbot that grounds responses in regulations"""
    try:
        rag = get_rag_system()
        
        # Check if query is about regulations
        regulatory_keywords = ['rule', 'regulation', 'legal', 'requirement', 'mandatory', 'law', 'compliance']
        is_regulatory = any(kw in user_message.lower() for kw in regulatory_keywords)
        
        if is_regulatory:
            # Use RAG for regulatory questions
            result = rag.query(user_message)
            
            response = {
                'answer': result['answer'],
                'sources': result['sources'],
                'confidence': result['confidence'],
                'grounded': True,
                'type': 'regulatory_query'
            }
        else:
            # Use standard LLM for general questions but with regulatory context
            context_query = "What are the key Legal Metrology compliance requirements?"
            context = rag.query(context_query)
            
            enhanced_prompt = f"""Context from Legal Metrology Regulations:
{context['answer']}

User Question: {user_message}

Provide an accurate answer. If the question requires regulatory information, reference the context above."""

            llm_response = llm.invoke(enhanced_prompt)
            
            response = {
                'answer': llm_response.content,
                'sources': context['sources'],
                'confidence': 0.8,
                'grounded': False,
                'type': 'general_query'
            }
        
        return response
        
    except Exception as e:
        print(f"[ERROR] RAG chatbot failed: {e}")
        return {
            'answer': f"Error: {str(e)}",
            'sources': [],
            'confidence': 0.0,
            'grounded': False
        }

# ==================== EXPORT ====================

__all__ = [
    'LegalMetrologyRAG',
    'get_rag_system',
    'rag_enhanced_ocr_analysis',
    'rag_enhanced_recommendations',
    'rag_chatbot',
    'LEGAL_METROLOGY_DOCS'
]

if __name__ == '__main__':
    print("[RAG SYSTEM] Initializing...")
    
    # Test RAG system
    rag = get_rag_system()
    
    # Test queries
    test_queries = [
        "What are the MRP declaration requirements?",
        "Is QR code allowed for declarations?",
        "What are the net quantity rules?",
        "What is the penalty for missing FSSAI license?"
    ]
    
    print("\n=== RAG SYSTEM TEST ===")
    for query in test_queries:
        print(f"\nQuery: {query}")
        result = rag.query(query)
        print(f"Answer: {result['answer'][:200]}...")
        print(f"Confidence: {result['confidence']}")
        print(f"Sources: {len(result['sources'])}")
    
    print("\n[RAG SYSTEM] SUCCESS: Ready")
