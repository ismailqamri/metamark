#!/usr/bin/env python3
"""
User-Context Aware Chatbot
Provides personalized insights based on the logged-in user's data
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import mysql.connector
from mysql.connector import Error

from langchain_google_genai import ChatGoogleGenerativeAI

from langchain_community.agent_toolkits import create_sql_agent
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.prompts import ChatPromptTemplate


from dotenv import load_dotenv
load_dotenv()

# Configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Initialize LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.3,
    convert_system_message_to_human=True
)

# ==================== USER CONTEXT MANAGER ====================

class UserContextManager:
    """
    Manages user-specific context for personalized AI responses
    """
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.user_profile = None
        self.user_stats = None
        self._load_user_context()
    
    def _load_user_context(self):
        """Load user profile and statistics from database"""
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor(dictionary=True)
            
            # Get user profile
            cursor.execute("""
                SELECT id, username, role, created_at 
                FROM Users 
                WHERE id = %s
            """, (self.user_id,))
            self.user_profile = cursor.fetchone()
            
            if not self.user_profile:
                return
            
            # Get user statistics
            if self.user_profile['role'] == 'seller':
                # Seller-specific stats
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_products,
                        COUNT(CASE WHEN rating >= 7.0 THEN 1 END) as compliant_products,
                        COUNT(CASE WHEN rating < 7.0 THEN 1 END) as non_compliant_products,
                        AVG(rating) as avg_compliance_score,
                        MAX(last_analysed) as last_analysis_date
                    FROM Products 
                    WHERE user_id = %s
                """, (self.user_id,))
                stats = cursor.fetchone()
                
                # Get activity stats
                cursor.execute("""
                    SELECT COUNT(*) as total_activities
                    FROM SellerActivity 
                    WHERE seller_id = %s
                """, (self.user_id,))
                activity = cursor.fetchone()
                
                self.user_stats = {
                    **stats,
                    'total_activities': activity['total_activities'] if activity else 0
                }
            else:
                # Customer-specific stats
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_scraped,
                        MAX(created_at) as last_scrape_date
                    FROM Products 
                    WHERE user_id = %s
                """, (self.user_id,))
                stats = cursor.fetchone()
                
                # Get activity stats
                cursor.execute("""
                    SELECT COUNT(*) as total_activities
                    FROM SellerActivity 
                    WHERE customer_id = %s
                """, (self.user_id,))
                activity = cursor.fetchone()
                
                self.user_stats = {
                    **stats,
                    'total_activities': activity['total_activities'] if activity else 0
                }
            
            cursor.close()
            connection.close()
            
        except Error as e:
            print(f"[ERROR] Failed to load user context: {e}")
    
    def get_context_summary(self) -> str:
        """Generate a summary of user context for AI"""
        if not self.user_profile:
            return "User context unavailable."
        
        summary = f"""
=== CURRENT USER CONTEXT ===
User ID: {self.user_id}
Username: {self.user_profile['username']}
Role: {self.user_profile['role'].upper()}
Member Since: {self.user_profile['created_at']}

"""
        
        if self.user_profile['role'] == 'seller':
            summary += f"""SELLER STATISTICS:
- Total Products Listed: {self.user_stats.get('total_products', 0)}
- Compliant Products (Rating ≥ 70): {self.user_stats.get('compliant_products', 0)}
- Non-Compliant Products (Rating < 70): {self.user_stats.get('non_compliant_products', 0)}
- Average Compliance Score: {self.user_stats.get('avg_compliance_score', 0):.1f}/10
- Last Analysis: {self.user_stats.get('last_analysis_date', 'Never')}
- Total Activities Logged: {self.user_stats.get('total_activities', 0)}
"""
        else:
            summary += f"""CUSTOMER STATISTICS:
- Total Products Scraped: {self.user_stats.get('total_scraped', 0)}
- Last Scrape: {self.user_stats.get('last_scrape_date', 'Never')}
- Total Activities Logged: {self.user_stats.get('total_activities', 0)}
"""
        
        return summary

# ==================== USER-AWARE CHATBOT ====================

def create_user_aware_agent(user_id: int):
    """
    Create a SQL agent with user-specific context
    """
    try:
        # Load user context
        context_manager = UserContextManager(user_id)
        context_summary = context_manager.get_context_summary()
        user_role = context_manager.user_profile['role'] if context_manager.user_profile else 'customer'
        
        # Create SQLAlchemy database URL
        from urllib.parse import quote_plus

        password = quote_plus(DB_CONFIG['password'])
        db_url = f"mysql+mysqlconnector://{DB_CONFIG['user']}:{password}@{DB_CONFIG['host']}/{DB_CONFIG['database']}"
        db = SQLDatabase.from_uri(db_url)
        
        # Create toolkit
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)
        
        # Create user-aware system message
        system_message = f"""You are an intelligent assistant for an Amazon Product Compliance Platform.

{context_summary}

=== YOUR ROLE ===
You are helping the CURRENT USER (User ID: {user_id}) with their data and compliance needs.

=== STRICT PRIVACY RULES ===
1. **ONLY show data belonging to User ID {user_id}**
2. **ALWAYS filter queries with: WHERE user_id = {user_id}** (for Products table)
3. **NEVER show data from other users**
4. For SellerActivity table:
   - If user is a seller: filter by seller_id = {user_id}
   - If user is a customer: give access to entire seller_information column JSON only 

=== YOUR CAPABILITIES ===
1. Answer questions about the user's products and compliance status
2. Provide personalized insights and recommendations
3. Query the database to fetch user-specific data and seller data
4. Explain compliance scores and violations
5. Compare user's performance over time
6. Suggest improvements for specific products

=== AVAILABLE TABLES ===
- Users: id, username, role, created_at
- Products: product_id, user_id, asin, title, price, currency, seller_information, product_json, analysis_results, rating (0-10 scale, where 7.0+ is compliant), remarks, last_analysed
- Images: image_id, product_id, image_data, created_at
- SellerActivity: activity_id, seller_id, customer_id, action, seller_information, timestamp

=== QUERY GUIDELINES ===
- **CRITICAL**: Always include `WHERE user_id = {user_id}` for Products table
- Parse JSON columns carefully (product_json, analysis_results, seller_information)
- Rating is on 0-10 scale: ≥7.0 = compliant, <7.0 = needs improvement
- Handle NULL values appropriately
- Limit large result sets
- Be conversational and helpful

=== SELLER QUERY GUIDELINES ===
Always answer using the database. Never give generic advice about Amazon or e-commerce.

Treat all seller-related questions as one of the following categories:

Safe or trusted sellers

Best sellers

Seller reputation

Seller activity

Sellers by location

Seller comparison

Seller information for a specific product

Risky or low-rated sellers

Safest or best sellers:
Use data from the products table and selleractivity table.
Query example:
Select seller_information, avg(rating) as avg_rating, count(*) as product_count
From products
Where user_id = {user_id}
Group by seller_information
Order by avg_rating desc
Limit 5;

Seller reputation:
Extract information from the seller_information JSON.
Use fields like seller name, seller_type, reputation, location, description.

Seller activity:
Query selleractivity to see how often a seller appears.
Example:
Select seller_information, count(*) as interactions
From selleractivity
Group by seller_information
Order by interactions desc;

Sellers by location:
Use location, latitude, longitude from selleractivity.
Example:
Select seller_information, location, latitude, longitude
From selleractivity
Where location like '%keyword%';

Seller for a specific product:
Example:
Select seller_information
From products
Where asin = 'ASIN_VALUE' and user_id = {user_id};

Compare sellers:
Use multiple filters on seller_information JSON.
Example:
Select seller_information, avg(rating) as avg_rating, count(*) as product_count
From products
Where JSON_EXTRACT(seller_information, '$.name') in ('SellerA','SellerB')
And user_id = {user_id}
Group by seller_information;

Risky sellers:
Low-rated or low-activity sellers.
Example (low rating):
Select seller_information, avg(rating) as avg_rating
From products
Where user_id = {user_id}
Group by seller_information
Having avg_rating < 5;

Never show sellers that are not present in the database.

Always summarize results clearly:

seller name

average rating

activity count

reputation info (from JSON)

whether the seller is an official brand store

location if available

If no matching seller is found, reply:
“No matching seller found in your database.”

===SELLER AND PRODUCT QUERRIES ===

When a user asks for the best seller for any product category (example: "chips", "biscuits",
"snacks", "laptop", "shoes", etc.), follow these rules:

1. DO NOT search only by the keyword in the title.
2. Instead, analyze every product title using AI classification and decide:
      "Is this product a type of the requested category?"
   For example: Chips category includes words like:
      chips, potato chips, nachos, wafers, snacks, masala snack, tortilla chips,
      crunchy snacks, salted snacks, etc.

3. For all products classified as belonging to that category:
      - Extract seller_information
      - Extract rating
      - Compute average rating per seller
      - Select the top seller (highest avg rating)

4. If at least one product matches the category:
      Return:
         - Seller Name
         - Average Rating
         - Example products that matched
         - Why they were classified as chips

5. If no products match the category:
      DO NOT say "not found".
      Instead reply:
          "No products classified as chips found in your data. Here are your top sellers overall."

6. NEVER rely only on literal string matching.
   ALWAYS use AI classification of product titles.


=== SAMPLE QUERIES USER MIGHT ASK ===
- "Show me my products"
- "What's my compliance score?"
- "Which of my products need improvement?"
- "How many compliant products do I have?"
- "Show me products I scraped recently"
- "What are my worst-performing products?"
- "Who are the most safe sellers I can buy from?" 
- "Who are the safest sellers to buy from?"

=== RESPONSE STYLE ===
- Be friendly and conversational
- Use the user's name when appropriate
- Provide actionable insights
- If data is empty, guide them on what to do next
- Format numbers and dates nicely
- Highlight important information

Remember: You're a personalized assistant for User ID {user_id} ONLY!"""

        # Create the agent
        agent = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            agent_type="openai-functions",
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=5,
            prefix=system_message
        )
        
        return agent, context_manager
        
    except Exception as e:
        print(f"[ERROR] Failed to create user-aware agent: {e}")
        return None, None

# ==================== MAIN CHATBOT FUNCTION ====================

def user_chatbot(user_id: int, user_message: str, conversation_history: List[Dict] = None) -> Dict[str, Any]:
    """
    User-context aware chatbot that only shows data for the current user
    
    Args:
        user_id: Current logged-in user's ID
        user_message: User's question
        conversation_history: Previous conversation (optional)
        
    Returns:
        {
            'response': AI response text,
            'user_context': User profile and stats,
            'query_executed': Whether database was queried,
            'error': Error message if any
        }
    """
    print(f"\n[USER CHATBOT] User {user_id} asked: {user_message[:100]}...")
    
    try:
        # Create user-aware agent
        agent, context_manager = create_user_aware_agent(user_id)
        
        if not agent or not context_manager:
            return {
                'response': "I'm having trouble accessing your data right now. Please try again.",
                'user_context': None,
                'query_executed': False,
                'error': 'Agent creation failed'
            }
        
        # Check if user profile exists
        if not context_manager.user_profile:
            return {
                'response': f"I couldn't find your user profile (User ID: {user_id}). Please make sure you're logged in correctly.",
                'user_context': None,
                'query_executed': False,
                'error': 'User not found'
            }
        
        # Enhanced message with user context hint
        enhanced_message = f"""User question: {user_message}

Remember: Only show data for User ID {user_id}. Always filter with WHERE user_id = {user_id} for Products table."""
        
        # Get response from agent
        result = agent.invoke({"input": enhanced_message})
        
        response_text = result.get('output', 'I apologize, but I encountered an issue processing your request.')
        
        print(f"[USER CHATBOT] SUCCESS: Response generated ({len(response_text)} chars)")
        
        return {
            'response': response_text,
            'user_context': {
                'username': context_manager.user_profile['username'],
                'role': context_manager.user_profile['role'],
                'stats': context_manager.user_stats
            },
            'query_executed': True,
            'error': None
        }
        
    except Exception as e:
        print(f"[ERROR] User chatbot error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'response': f"I encountered an error: {str(e)}. Please try rephrasing your question.",
            'user_context': None,
            'query_executed': False,
            'error': str(e)
        }

# ==================== QUICK INSIGHTS ====================

def get_user_dashboard(user_id: int) -> Dict[str, Any]:
    """
    Generate quick dashboard insights for the user
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Get user info
        cursor.execute("SELECT username, role FROM Users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return {'error': 'User not found'}
        
        dashboard = {
            'user': user,
            'insights': []
        }
        
        if user['role'] == 'seller':
            # Seller dashboard
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_products,
                    AVG(rating) as avg_score,
                    COUNT(CASE WHEN rating >= 7.0 THEN 1 END) as compliant,
                    COUNT(CASE WHEN rating < 7.0 AND rating IS NOT NULL THEN 1 END) as needs_work,
                    COUNT(CASE WHEN rating IS NULL THEN 1 END) as not_analyzed
                FROM Products 
                WHERE user_id = %s
            """, (user_id,))
            stats = cursor.fetchone()
            
            dashboard['stats'] = stats
            
            # Get top performing products
            cursor.execute("""
                SELECT product_id, title, rating, remarks
                FROM Products 
                WHERE user_id = %s AND rating IS NOT NULL
                ORDER BY rating DESC
                LIMIT 3
            """, (user_id,))
            dashboard['top_products'] = cursor.fetchall()
            
            # Get products needing attention
            cursor.execute("""
                SELECT product_id, title, rating, remarks
                FROM Products 
                WHERE user_id = %s AND rating < 7.0
                ORDER BY rating ASC
                LIMIT 3
            """, (user_id,))
            dashboard['needs_attention'] = cursor.fetchall()
            
            # Generate insights
            if stats['total_products'] == 0:
                dashboard['insights'].append("You haven't added any products yet. Start by scraping your Amazon listings!")
            elif stats['avg_score'] and stats['avg_score'] >= 7.0:
                dashboard['insights'].append(f"Great job! Your average compliance score is {stats['avg_score']*10:.1f}/100")
            elif stats['needs_work'] > 0:
                dashboard['insights'].append(f"You have {stats['needs_work']} products that need compliance improvements")
            
            if stats['not_analyzed'] > 0:
                dashboard['insights'].append(f"{stats['not_analyzed']} products haven't been analyzed yet")
        
        else:
            # Customer dashboard
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_scraped,
                    COUNT(CASE WHEN rating IS NOT NULL THEN 1 END) as analyzed,
                    MAX(created_at) as last_scrape
                FROM Products 
                WHERE user_id = %s
            """, (user_id,))
            stats = cursor.fetchone()
            
            dashboard['stats'] = stats
            
            # Get recent scrapes
            cursor.execute("""
                SELECT product_id, title, rating, created_at
                FROM Products 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 5
            """, (user_id,))
            dashboard['recent_scrapes'] = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return dashboard
        
    except Exception as e:
        print(f"[ERROR] Dashboard generation failed: {e}")
        return {'error': str(e)}

# ==================== EXPORT ====================

__all__ = [
    'user_chatbot',
    'get_user_dashboard',
    'UserContextManager'
]

if __name__ == '__main__':
    print("[USER-CONTEXT CHATBOT] Testing...")
    
    # Test with a user ID
    test_user_id = 3
    
    # Test dashboard
    print("\n=== DASHBOARD TEST ===")
    dashboard = get_user_dashboard(test_user_id)
    print(json.dumps(dashboard, indent=2, default=str))
    
    # Test chatbot
    print("\n=== CHATBOT TEST ===")
    response = user_chatbot(test_user_id, "Show me my products and their compliance scores")
    print(f"\nResponse: {response['response']}")
