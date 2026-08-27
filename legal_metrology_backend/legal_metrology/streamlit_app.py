#!/usr/bin/env python3

"""
Streamlit Frontend for Amazon Product Scraper
Integrates with Flask Backend API - Updated Version
Includes: AI Compliance, Chatbot, Seller Upload Check, and Batch Analysis
"""

import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime
import json

# ==================== CONFIGURATION ====================
API_BASE_URL = "http://localhost:5000/api"

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'session_cookies' not in st.session_state:
    st.session_state.session_cookies = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# ==================== API HELPER FUNCTIONS ====================
def api_request(endpoint, method='GET', data=None, files=None, timeout=60):
    """Make API request with session handling"""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        if method == 'GET':
            response = requests.get(url, cookies=st.session_state.session_cookies, timeout=timeout)
        elif files:
            # Multipart form data for file uploads
            response = requests.post(url, data=data, files=files, cookies=st.session_state.session_cookies, timeout=timeout)
        else:
            response = requests.post(url, json=data, cookies=st.session_state.session_cookies, timeout=timeout)

        # Update session cookies
        if response.cookies:
            if st.session_state.session_cookies is None:
                st.session_state.session_cookies = {}
            st.session_state.session_cookies.update(response.cookies.get_dict())

        return response
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to backend server. Make sure Flask is running on port 5000.")
        return None
    except requests.exceptions.Timeout:
        st.error("❌ Request timed out. The operation may take longer for some products.")
        return None

# ==================== AUTHENTICATION PAGES ====================
def login_page():
    """Login page UI"""
    st.title("🔐 Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login", use_container_width=True)

        if submit:
            if username and password:
                response = api_request('/login', 'POST', {
                    'username': username,
                    'password': password
                })

                if response and response.status_code == 200:
                    data = response.json()
                    st.session_state.logged_in = True
                    st.session_state.user = data['user']
                    st.success(f"✅ Welcome back, {data['user']['username']}!")
                    st.rerun()
                elif response:
                    st.error(f"❌ {response.json().get('error', 'Login failed')}")
            else:
                st.warning("Please enter both username and password")

def signup_page():
    """Signup page UI"""
    st.title("📝 Create Account")

    with st.form("signup_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        role = st.selectbox("Account Type", ["customer", "seller"])

        st.info("💡 **Customer**: Can scrape and view products\n**Seller**: Can also view analytics, heatmaps, and use compliance tools")

        submit = st.form_submit_button("Create Account", use_container_width=True)

        if submit:
            if not username or not password:
                st.warning("Please fill in all fields")
            elif password != confirm_password:
                st.error("Passwords do not match")
            elif len(password) < 6:
                st.warning("Password must be at least 6 characters")
            else:
                response = api_request('/signup', 'POST', {
                    'username': username,
                    'password': password,
                    'role': role
                })

                if response and response.status_code == 201:
                    st.success("✅ Account created successfully! Please login.")
                elif response:
                    st.error(f"❌ {response.json().get('error', 'Signup failed')}")

def logout():
    """Handle logout"""
    api_request('/logout', 'POST')
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.session_cookies = None
    st.session_state.chat_history = []
    st.rerun()

# ==================== MAIN APPLICATION PAGES ====================
def scrape_page():
    """Product scraping page with auto compliance analysis"""
    st.title("🔍 Scrape Amazon Product")
    st.markdown("Enter an Amazon product URL to extract product information using AI-powered scraping.")

    with st.form("scrape_form"):
        url = st.text_input(
            "Amazon Product URL",
            placeholder="https://www.amazon.in/dp/XXXXXXXXXX"
        )
        auto_analyze = st.checkbox("🔬 Auto-analyze compliance after scraping", value=True)
        submit = st.form_submit_button("🚀 Scrape Product", use_container_width=True)

        if submit:
            if not url:
                st.warning("Please enter a product URL")
            elif 'amazon' not in url.lower():
                st.error("Please enter a valid Amazon URL")
            else:
                with st.spinner("🔄 AI is analyzing and scraping the product... This may take a moment."):
                    response = api_request('/scrape', 'POST', {
                        'url': url,
                        'auto_analyze': auto_analyze
                    }, timeout=120)

                    if response and response.status_code == 200:
                        data = response.json()
                        st.success(f"✅ {data['message']}")

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Product ID", data['product_id'])
                        with col2:
                            st.metric("ASIN", data['asin'])
                        with col3:
                            st.metric("Images Stored", data['images_stored'])

                        st.info(f"📦 **Title:** {data.get('title', 'N/A')}")

                        if data.get('is_update'):
                            st.info("ℹ️ This product was updated (already existed in database)")

                        # Activity logging info
                        activity = data.get('activity_logged', 'none')
                        if activity == 'customer_scrape':
                            st.success("📊 Your view has been logged for seller analytics")
                        elif activity == 'seller_own_scrape':
                            st.info("📊 Activity logged as owner scrape")
                        elif activity == 'seller_viewing_competitor':
                            st.info("📊 Activity logged as competitor view")

                        # Show compliance analysis if available
                        compliance_data = data.get('compliance_analysis')
                        if compliance_data:
                            st.divider()
                            st.subheader("🔬 Compliance Analysis")

                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                score = compliance_data.get('score', 'N/A')
                                st.metric("Score", f"{score}/100")
                            with col2:
                                st.metric("Grade", compliance_data.get('grade', 'N/A'))
                            with col3:
                                is_compliant = compliance_data.get('is_compliant', False)
                                st.metric("Status", "✅ Compliant" if is_compliant else "WARNING:️ Issues Found")
                            with col4:
                                st.metric("Violations", compliance_data.get('violations_count', 0))

                            if compliance_data.get('requires_action'):
                                st.warning("WARNING:️ This product requires attention. View details in My Products.")

                    elif response:
                        st.error(f"❌ {response.json().get('error', 'Scraping failed')}")

def products_page():
    """View scraped products with compliance status"""
    st.title("📦 My Products")

    response = api_request('/products')

    if response and response.status_code == 200:
        products = response.json().get('products', [])

        if not products:
            st.info("No products found. Start by scraping some Amazon products!")
            return

        st.markdown(f"**Total Products:** {len(products)}")

        # Filter options
        col1, col2 = st.columns(2)
        with col1:
            search = st.text_input("🔍 Search products", placeholder="Search by title or ASIN")
        with col2:
            sort_by = st.selectbox("Sort by", ["Latest", "Price (High to Low)", "Price (Low to High)"])

        # Filter products
        filtered_products = products
        if search:
            filtered_products = [p for p in products if search.lower() in (p.get('title', '') or '').lower() or search.lower() in (p.get('asin', '') or '').lower()]

        for product in filtered_products:
            with st.expander(f"📦 {(product.get('title') or 'Untitled')[:60]}...", expanded=False):
                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    st.markdown(f"**ASIN:** `{product.get('asin')}`")
                    st.markdown(f"**Price:** {product.get('currency', '')} {product.get('price', 'N/A')}")
                    if product.get('rating'):
                        st.markdown(f"**Rating:** ⭐ {product.get('rating')}")
                    st.markdown(f"**[View on Amazon]({product.get('url')})**")

                with col2:
                    # Show compliance status if available
                    if product.get('remarks'):
                        st.markdown(f"**Remarks:** {product.get('remarks')}")
                    if product.get('last_analysed'):
                        st.caption(f"Analyzed: {product.get('last_analysed')}")

                with col3:
                    if st.button("View Details", key=f"view_{product['product_id']}"):
                        st.session_state.selected_product_id = product['product_id']
                        st.rerun()

                    if st.button("🔬 Analyze", key=f"analyze_{product['product_id']}"):
                        with st.spinner("Analyzing..."):
                            analyze_response = api_request(f"/compliance/analyze/{product['product_id']}", 'POST')
                            if analyze_response and analyze_response.status_code == 200:
                                st.success("✅ Analysis complete!")
                                st.rerun()
                            elif analyze_response:
                                st.error(f"❌ {analyze_response.json().get('error', 'Analysis failed')}")
    else:
        st.error("Failed to load products")

def product_detail_page(product_id):
    """View detailed product information with compliance report"""
    st.title("📋 Product Details")

    if st.button("← Back to Products"):
        if 'selected_product_id' in st.session_state:
            del st.session_state.selected_product_id
        st.rerun()

    response = api_request(f'/product/{product_id}')

    if response and response.status_code == 200:
        product = response.json().get('product', {})

        st.header(product.get('title', 'Product'))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Price", f"{product.get('currency', '')} {product.get('price', 'N/A')}")
        with col2:
            st.metric("ASIN", product.get('asin', 'N/A'))
        with col3:
            st.metric("Images", product.get('image_count', 0))
        with col4:
            if product.get('rating'):
                st.metric("Rating", product.get('rating'))

        st.markdown(f"**[View on Amazon]({product.get('url')})**")

        # Compliance Report Section
        compliance_report = product.get('compliance_report')
        if compliance_report:
            st.divider()
            st.subheader("🔬 Compliance Report")

            col1, col2, col3 = st.columns(3)
            with col1:
                score = compliance_report.get('compliance_score', 'N/A')
                st.metric("Compliance Score", f"{score}/100")
            with col2:
                st.metric("Grade", compliance_report.get('compliance_grade', 'N/A'))
            with col3:
                is_compliant = compliance_report.get('is_compliant', False)
                st.metric("Status", "✅ Compliant" if is_compliant else "WARNING:️ Needs Review")

            # Violation Summary
            violations = compliance_report.get('violation_summary', {})
            if violations:
                with st.expander("WARNING:️ Violation Summary", expanded=True):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Critical", violations.get('critical', 0))
                    with col2:
                        st.metric("Major", violations.get('major', 0))
                    with col3:
                        st.metric("Minor", violations.get('minor', 0))

            # Detailed Issues
            issues = compliance_report.get('issues', [])
            if issues:
                with st.expander("📋 Detailed Issues"):
                    for issue in issues:
                        severity = issue.get('severity', 'info')
                        icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}.get(severity, "ℹ️")
                        st.markdown(f"{icon} **{issue.get('category', 'General')}**: {issue.get('description', 'N/A')}")
                        if issue.get('recommendation'):
                            st.caption(f"   💡 {issue.get('recommendation')}")

            # Recommendations
            recommendations = compliance_report.get('recommendations', [])
            if recommendations:
                with st.expander("💡 Recommendations"):
                    for rec in recommendations:
                        st.markdown(f"• {rec}")

        # Product Information
        json_data = product.get('product_json', {})
        if json_data:
            st.divider()
            st.subheader("Product Information")

            if json_data.get('description'):
                with st.expander("📝 Description", expanded=True):
                    st.write(json_data['description'])

            if json_data.get('feature_bullets'):
                with st.expander("✨ Features"):
                    for feature in json_data['feature_bullets']:
                        st.markdown(f"• {feature}")

            if json_data.get('specifications'):
                with st.expander("📊 Specifications"):
                    specs = json_data['specifications']
                    if isinstance(specs, dict):
                        for key, value in specs.items():
                            st.markdown(f"**{key}:** {value}")
                    else:
                        st.write(specs)

            if json_data.get('technical_details'):
                with st.expander("🔧 Technical Details"):
                    tech = json_data['technical_details']
                    if isinstance(tech, dict):
                        for key, value in tech.items():
                            st.markdown(f"**{key}:** {value}")
                    else:
                        st.write(tech)

            if json_data.get('seller_information'):
                with st.expander("🏪 Seller Information"):
                    seller = json_data['seller_information']
                    if isinstance(seller, dict):
                        for key, value in seller.items():
                            st.markdown(f"**{key}:** {value}")
                    else:
                        st.write(seller)

            if json_data.get('important_information'):
                with st.expander("WARNING:️ Important Information"):
                    st.write(json_data['important_information'])

        # Re-analyze button
        st.divider()
        if st.button("🔄 Re-analyze Compliance", use_container_width=True):
            with st.spinner("Running compliance analysis..."):
                analyze_response = api_request(f"/compliance/analyze/{product_id}", 'POST')
                if analyze_response and analyze_response.status_code == 200:
                    st.success("✅ Analysis complete! Refreshing...")
                    st.rerun()
                elif analyze_response:
                    st.error(f"❌ {analyze_response.json().get('error', 'Analysis failed')}")

    else:
        st.error("Product not found")

def seller_upload_check_page():
    """Pre-upload compliance check for sellers"""
    st.title("📤 Pre-Upload Compliance Check")
    st.markdown("Check your product listing for compliance issues **before** uploading to Amazon.")

    if st.session_state.user.get('role') != 'seller':
        st.warning("This feature is only available for seller accounts.")
        return

    with st.form("upload_check_form"):
        st.subheader("Product Information")

        title = st.text_input("Product Title *", placeholder="Enter your product title")
        description = st.text_area("Product Description *", placeholder="Enter detailed product description", height=150)

        features = st.text_area("Features (one per line)", placeholder="Feature 1\nFeature 2\nFeature 3", height=100)

        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox("Product Category", ["amazon", "book", "food", "skincare", "electric"])
        with col2:
            price = st.text_input("Price", placeholder="999.00")

        st.subheader("Product Images")
        uploaded_files = st.file_uploader(
            "Upload product images (at least 1 required) *",
            type=['jpg', 'jpeg', 'png', 'webp'],
            accept_multiple_files=True
        )

        if uploaded_files:
            cols = st.columns(min(len(uploaded_files), 5))
            for idx, file in enumerate(uploaded_files[:5]):
                with cols[idx]:
                    st.image(file, caption=f"Image {idx+1}", use_container_width=True)

        st.subheader("Additional Details (Optional)")
        specifications = st.text_area("Specifications (JSON format)", placeholder='{"Weight": "500g", "Dimensions": "10x5x3 cm"}')
        details = st.text_area("Product Details (JSON format)", placeholder='{"Brand": "MyBrand", "Material": "Cotton"}')

        submit = st.form_submit_button("🔬 Check Compliance", use_container_width=True)

        if submit:
            if not title or not description:
                st.error("Please fill in required fields (Title and Description)")
            elif not uploaded_files:
                st.error("Please upload at least one product image")
            else:
                with st.spinner("🔄 Analyzing your product listing..."):
                    # Prepare form data
                    form_data = {
                        'title': title,
                        'description': description,
                        'category': category,
                        'features': json.dumps(features.split('\n') if features else []),
                        'specifications': specifications if specifications else '{}',
                        'details': details if details else '{}'
                    }

                    # Prepare files
                    files = [('images', (f.name, f.getvalue(), f.type)) for f in uploaded_files]

                    response = api_request('/seller/check-upload', 'POST', data=form_data, files=files, timeout=120)

                    if response and response.status_code == 200:
                        feedback = response.json().get('feedback', {})

                        st.success("✅ Analysis Complete!")
                        st.divider()

                        # Display feedback
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            score = feedback.get('overall_score', 'N/A')
                            st.metric("Overall Score", f"{score}/100")
                        with col2:
                            st.metric("Ready to Upload", "✅ Yes" if feedback.get('ready_to_upload') else "❌ No")
                        with col3:
                            st.metric("Issues Found", feedback.get('issues_count', 0))

                        # Image Analysis
                        if feedback.get('image_analysis'):
                            with st.expander("📷 Image Analysis", expanded=True):
                                img_analysis = feedback['image_analysis']
                                for key, value in img_analysis.items():
                                    st.markdown(f"**{key}:** {value}")

                        # Content Analysis
                        if feedback.get('content_analysis'):
                            with st.expander("📝 Content Analysis", expanded=True):
                                content = feedback['content_analysis']
                                for key, value in content.items():
                                    st.markdown(f"**{key}:** {value}")

                        # Issues
                        if feedback.get('issues'):
                            with st.expander("WARNING:️ Issues to Fix", expanded=True):
                                for issue in feedback['issues']:
                                    severity_icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}.get(issue.get('severity', ''), "ℹ️")
                                    st.markdown(f"{severity_icon} {issue.get('description', '')}")
                                    if issue.get('fix'):
                                        st.caption(f"   💡 Fix: {issue.get('fix')}")

                        # Recommendations
                        if feedback.get('recommendations'):
                            with st.expander("💡 Recommendations"):
                                for rec in feedback['recommendations']:
                                    st.markdown(f"• {rec}")
                    elif response:
                        st.error(f"❌ {response.json().get('error', 'Analysis failed')}")

def batch_analysis_page():
    """Batch compliance analysis for sellers"""
    st.title("📊 Batch Compliance Analysis")
    st.markdown("Analyze multiple products at once for compliance issues.")

    if st.session_state.user.get('role') != 'seller':
        st.warning("This feature is only available for seller accounts.")
        return

    # Get user's products
    response = api_request('/products')

    if response and response.status_code == 200:
        products = response.json().get('products', [])

        if not products:
            st.info("No products found. Start by scraping some Amazon products!")
            return

        st.markdown(f"Select products to analyze (found {len(products)} products):")

        # Create selection
        selected_products = []

        col1, col2 = st.columns([3, 1])
        with col1:
            select_all = st.checkbox("Select All")

        for product in products:
            is_selected = st.checkbox(
                f"{(product.get('title') or 'Untitled')[:50]}... (ASIN: {product.get('asin')})",
                value=select_all,
                key=f"batch_{product['product_id']}"
            )
            if is_selected:
                selected_products.append(product['product_id'])

        st.divider()
        st.markdown(f"**Selected:** {len(selected_products)} products")

        if st.button("🔬 Run Batch Analysis", use_container_width=True, disabled=len(selected_products) == 0):
            with st.spinner(f"Analyzing {len(selected_products)} products... This may take a while."):
                response = api_request('/compliance/batch', 'POST', {'product_ids': selected_products}, timeout=300)

                if response and response.status_code == 200:
                    results = response.json().get('results', {})

                    st.success(f"✅ Batch analysis complete!")
                    st.divider()

                    # Summary
                    successful = results.get('successful', [])
                    failed = results.get('failed', [])

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Analyzed", len(successful) + len(failed))
                    with col2:
                        st.metric("Successful", len(successful))
                    with col3:
                        st.metric("Failed", len(failed))

                    # Results table
                    if successful:
                        st.subheader("Results")
                        df = pd.DataFrame(successful)
                        if not df.empty:
                            display_cols = [c for c in ['product_id', 'title', 'score', 'grade', 'is_compliant', 'violations'] if c in df.columns]
                            st.dataframe(df[display_cols] if display_cols else df, use_container_width=True, hide_index=True)

                    if failed:
                        with st.expander("❌ Failed Analyses"):
                            for f in failed:
                                st.markdown(f"• Product {f.get('product_id')}: {f.get('error', 'Unknown error')}")
                elif response:
                    st.error(f"❌ {response.json().get('error', 'Batch analysis failed')}")
    else:
        st.error("Failed to load products")

def chatbot_page():
    """AI Chatbot for compliance questions"""
    st.title("💬 Compliance Assistant")
    st.markdown("Ask questions about Amazon product compliance, listing guidelines, and best practices.")

    # Chat history display
    chat_container = st.container()

    with chat_container:
        for message in st.session_state.chat_history:
            if message['role'] == 'user':
                st.chat_message("user").markdown(message['content'])
            else:
                st.chat_message("assistant").markdown(message['content'])

    # Chat input
    user_input = st.chat_input("Ask a question about compliance...")

    if user_input:
        # Add user message to history
        st.session_state.chat_history.append({'role': 'user', 'content': user_input})

        # Get response from backend
        with st.spinner("Thinking..."):
            response = api_request('/chat', 'POST', {'message': user_input})

            if response and response.status_code == 200:
                bot_response = response.json().get('message', 'Sorry, I could not process that.')
                st.session_state.chat_history.append({'role': 'assistant', 'content': bot_response})
            else:
                error_msg = "Sorry, I encountered an error. Please try again."
                st.session_state.chat_history.append({'role': 'assistant', 'content': error_msg})

        st.rerun()

    # Clear chat button
    if st.session_state.chat_history:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()

def dashboard_page():
    """Personalized dashboard for current user"""
    st.title("📊 My Dashboard")
    st.markdown("Personalized scraping and compliance insights for your account.")

    response = api_request('/dashboard', 'GET')

    if not response:
        st.error("Failed to load dashboard data")
        return

    if response.status_code != 200:
        try:
            err = response.json().get('error', 'Failed to load dashboard data')
        except Exception:
            err = 'Failed to load dashboard data'
        st.error(err)
        return

    data = response.json()

    # Optional: show raw for debugging
    # st.write("RAW DASHBOARD DATA:", data)

    # Top summary from stats
    stats = data.get('stats', {})
    user = data.get('user', {})

    if not stats and not data.get('recent_scrapes') and not data.get('insights'):
        st.info("No dashboard data available yet. Scrape some products to see insights here.")
        return

    if stats:
        st.subheader("Overview")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Scraped", stats.get('total_scraped', 0))
        with col2:
            st.metric("Analyzed Products", stats.get('analyzed', 0))
        with col3:
            last_scrape = stats.get('last_scrape') or "N/A"
            st.metric("Last Scrape", last_scrape)

    # Recent scrapes list
    recent_scrapes = data.get('recent_scrapes', [])
    if recent_scrapes:
        st.subheader("Recent Scrapes")
        df = pd.DataFrame(recent_scrapes)
        # Normalize column names
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
        display_cols = [c for c in ['product_id', 'title', 'rating', 'created_at'] if c in df.columns]
        st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
        )

    # Insights (if backend starts returning some)
    insights = data.get('insights', [])
    if insights:
        st.subheader("Insights")
        for insight in insights:
            st.markdown(f"• {insight}")

    if user:
        st.caption(f"User: {user.get('username', '')} · Role: {user.get('role', '')}")



def seller_activity_page():
    """Seller activity logs"""
    st.title("📊 Activity Logs")
    st.markdown("View scraping activity related to your products.")

    if st.session_state.user.get('role') != 'seller':
        st.warning("Activity logs are only available for seller accounts.")
        return

    response = api_request('/seller/activity')

    if response and response.status_code == 200:
        activities = response.json().get('activities', [])

        if not activities:
            st.info("No activity recorded yet.")
            return

        st.markdown(f"**Total Activities:** {len(activities)}")

        df = pd.DataFrame(activities)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M')

        # Show all available useful cols
        candidate_cols = [
            'customer_username',
            'action',
            'location',
            'timestamp'
        ]

        display_cols = [c for c in candidate_cols if c in df.columns]

        st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "customer_username": "Customer",
                "action": "Action",
                "location": "Location",
                "timestamp": "Time",
            }
        )
    elif response and response.status_code == 403:
        st.error("You are not allowed to view this activity.")
    else:
        st.error("Failed to load activity data")

def heatmap_page():
    """Heatmap-style summary for current user (seller or customer)"""
    st.title("🗺️ My Heatmap")
    st.markdown("See where scraping activity related to you is happening, based on seller AI location insights.")

    response = api_request('/heatmap')

    if not response:
        st.error("Failed to load heatmap data")
        return

    if response.status_code != 200:
        try:
            err = response.json().get('error', 'Failed to load heatmap data')
        except Exception:
            err = 'Failed to load heatmap data'
        st.error(err)
        return

    data = response.json()
    user_role = data.get('user_role')
    heatmap_data = data.get('heatmap_data', [])

    if not heatmap_data:
        st.info("No geographic activity data available yet.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Locations", data.get('total_locations', 0))
    with col2:
        st.metric("Total Scrapes", data.get('total_scrapes', 0))

    # Convert to DataFrame
    df = pd.DataFrame(heatmap_data)

    # Normalize / pretty columns
    if 'last_scrape' in df.columns:
        df['last_scrape'] = pd.to_datetime(df['last_scrape']).dt.strftime('%Y-%m-%d %H:%M')

    if user_role == 'seller':
        # Expected columns from backend:
        # location, scrape_count, last_scrape, unique_customers, product_title, asin
        display_cols = [c for c in [
            'location',
            'scrape_count',
            'unique_customers',
            'product_title',
            'asin',
            'last_scrape',
        ] if c in df.columns]
        column_config = {
            "location": "Location",
            "scrape_count": "Views",
            "unique_customers": "Unique customers",
            "product_title": "Product",
            "asin": "ASIN",
            "last_scrape": "Last Activity",
        }
    else:
        # Expected columns:
        # location, scrape_count, last_scrape, seller_name, activity_type
        display_cols = [c for c in [
            'location',
            'scrape_count',
            'seller_name',
            'activity_type',
            'last_scrape',
        ] if c in df.columns]
        column_config = {
            "location": "Location",
            "scrape_count": "Views",
            "seller_name": "Seller",
            "activity_type": "Type",
            "last_scrape": "Last Activity",
        }

    st.subheader("Location Details")
    st.dataframe(
        df[display_cols] if display_cols else df,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )


def global_heatmap_page():
    """Global heatmap-style summary for all activity on the platform"""
    st.title("🌍 Global Heatmap")
    st.markdown("See scraping activity across all users on the platform, grouped by AI-detected seller locations.")

    response = api_request('/global-heatmap')

    if not response:
        st.error("Failed to load global heatmap data")
        return

    if response.status_code != 200:
        try:
            err = response.json().get('error', 'Failed to load global heatmap data')
        except Exception:
            err = 'Failed to load global heatmap data'
        st.error(err)
        return

    data = response.json()
    global_data = data.get('global_heatmap_data', [])

    if not global_data:
        st.info("No global geographic data available yet.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Locations", data.get('total_locations', 0))
    with col2:
        st.metric("Total Scrapes", data.get('total_scrapes', 0))

    df = pd.DataFrame(global_data)

    if 'last_activity' in df.columns:
        df['last_activity'] = pd.to_datetime(df['last_activity']).dt.strftime('%Y-%m-%d %H:%M')

    # Expected columns:
    # location, total_scrapes, unique_customers, products_from_sellers, last_activity
    display_cols = [c for c in [
        'location',
        'total_scrapes',
        'unique_customers',
        'products_from_sellers',
        'last_activity',
    ] if c in df.columns]

    st.subheader("Global Location Details")
    st.dataframe(
        df[display_cols] if display_cols else df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "location": "Location",
            "total_scrapes": "Total scrapes",
            "unique_customers": "Unique customers",
            "products_from_sellers": "Sellers",
            "last_activity": "Last Activity",
        },
    )


# ==================== MAIN APP ====================
def main():
    st.set_page_config(
        page_title="Amazon Product Scraper",
        page_icon="🛒",
        layout="wide"
    )

    # Custom CSS
    st.markdown("""
    <style>
        .stMetric {
            background-color: #f0f2f6;
            padding: 10px;
            border-radius: 5px;
        }
        .stExpander {
            background-color: #ffffff;
            border-radius: 5px;
        }
    </style>
    """, unsafe_allow_html=True)

    if not st.session_state.logged_in:
        tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign Up"])

        with tab1:
            login_page()
        with tab2:
            signup_page()
    else:
        user_role = st.session_state.user.get('role', 'customer')

        with st.sidebar:
            st.title("🛒 Amazon Scraper")
            st.markdown(f"**User:** {st.session_state.user['username']}")
            st.markdown(f"**Role:** {st.session_state.user['role'].title()}")
            st.divider()

            # Navigation based on role
            if user_role == 'seller':
                nav_options = [
                    "📊 Dashboard",
                    "🔍 Scrape Product",
                    "📦 My Products",
                    "📤 Pre-Upload Check",
                    "📊 Batch Analysis",
                    "💬 Compliance Chat",
                    "📈 Activity Logs",
                    "🗺️ My Heatmap",
                    "🌍 Global Heatmap",
                ]

            else:
                nav_options = [
                    "📊 Dashboard",
                    "🔍 Scrape Product",
                    "📦 My Products",
                    "💬 Compliance Chat",
                    "🗺️ My Heatmap",
                    "🌍 Global Heatmap",
                ]


            page = st.radio(
                "Navigation",
                nav_options,
                label_visibility="collapsed"
            )

            st.divider()

            if st.button("🚪 Logout", use_container_width=True):
                logout()

        # Page routing
        if 'selected_product_id' in st.session_state:
            product_detail_page(st.session_state.selected_product_id)
        elif page == "🔍 Scrape Product":
            scrape_page()
        elif page == "📊 Dashboard":
            dashboard_page()
        elif page == "📦 My Products":
            products_page()
        elif page == "📤 Pre-Upload Check":
            seller_upload_check_page()
        elif page == "📊 Batch Analysis":
            batch_analysis_page()
        elif page == "💬 Compliance Chat":
            chatbot_page()
        elif page == "📈 Activity Logs":
            seller_activity_page()
        elif page == "🗺️ My Heatmap":
            heatmap_page()
        elif page == "🌍 Global Heatmap":
            global_heatmap_page()

if __name__ == "__main__":
    main()
