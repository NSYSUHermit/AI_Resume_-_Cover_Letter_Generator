import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# ==========================================
# 1. 初始化與連接 Firebase
# ==========================================
def init_firebase():
    """
    Initialize Firebase Admin SDK.
    """
    if not firebase_admin._apps:
        try:
            cert_dict = dict(st.secrets["firebase_service_account"])
            cred = credentials.Certificate(cert_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"❌ Firebase initialization failed: {e}")
            return None
    
    return firestore.client()

# ==========================================
# 1.5 Authentication
# ==========================================
def register_user(db, email: str, password: str):
    """Register a new user with hashed password"""
    try:
        doc_ref = db.collection('user_auth').document(email)
        if doc_ref.get().exists:
            return False, "This Email is already registered!"
        
        hashed_pwd = generate_password_hash(password)
        doc_ref.set({"password_hash": hashed_pwd, "created_at": firestore.SERVER_TIMESTAMP})
        return True, "Registration successful, please log in!"
    except Exception as e:
        return False, f"Registration failed: {e}"

def authenticate_user(db, email: str, password: str):
    """Authenticate user login"""
    try:
        doc = db.collection('user_auth').document(email).get()
        if not doc.exists:
            return False, "Account not found, please register first."
        
        user_data = doc.to_dict()
        if check_password_hash(user_data.get("password_hash", ""), password):
            return True, "Login successful!"
        return False, "Incorrect password."
    except Exception as e:
        return False, f"Login verification failed: {e}"

def save_user_profile(db, email: str, resume_data: dict, custom_prompt: str, api_key: str):
    """Save base resume, custom prompt, and API key to Firestore"""
    try:
        doc_ref = db.collection('users').document(email).collection('profile').document('base_profile')
        data = {
            "base_resume": resume_data,
            "custom_prompt": custom_prompt,
            "api_key": api_key,
            "last_updated": firestore.SERVER_TIMESTAMP
        }
        doc_ref.set(data)
        return True, "✅ Profile synced to cloud successfully!"
    except Exception as e:
        st.error(f"❌ Error saving profile: {e}")
        return False, f"Error saving profile: {e}"

def load_user_profile(db, email: str):
    """Load base resume, custom prompt, and API key from Firestore"""
    try:
        doc_ref = db.collection('users').document(email).collection('profile').document('base_profile')
        doc = doc_ref.get()
        if doc.exists:
            profile_data = doc.to_dict()
            return profile_data.get("base_resume"), profile_data.get("custom_prompt"), profile_data.get("api_key")
        else:
            return None, None, None
    except Exception as e:
        st.error(f"❌ Error loading profile: {e}")
        return None, None, None

# ==========================================
# 2. Save Application Record
# ==========================================
def save_application(db, email: str, company_name: str, resume_json: dict):
    """
    Save application tracking record to Firestore.
    """
    try:
        doc_ref = db.collection('users').document(email).collection('applications').document()
        
        data = {
            "company_name": company_name,
            "applied_date": firestore.SERVER_TIMESTAMP,
            "status": "Applied",
            "resume_json": resume_json,
            "interview_date": None,
            "rejected_date": None,
            "notes": ""
        }
        
        doc_ref.set(data)
        return True
    except Exception as e:
        st.error(f"❌ Error saving application record: {e}")
        return False

# ==========================================
# 3. & 4. Dashboard Logic
# ==========================================
def update_application_status(db, email: str, doc_id: str, new_status: str, notes: str):
    """
    Update status and notes, recording timestamps automatically.
    """
    try:
        doc_ref = db.collection('users').document(email).collection('applications').document(doc_id)
        update_data = {"status": new_status, "notes": notes}
        
        if new_status == "Interviewing":
            update_data["interview_date"] = firestore.SERVER_TIMESTAMP
        elif new_status == "Rejected":
            update_data["rejected_date"] = firestore.SERVER_TIMESTAMP
            
        doc_ref.update(update_data)
        return True
    except Exception as e:
        st.error(f"❌ Error updating application: {e}")
        return False

def render_interview_progress(db, email: str):
    """
    Render Interview Progress and Conversion Rate with timeframe filtering.
    """
    st.subheader("📈 Interview Progress & Conversion")
    
    try:
        apps_ref = db.collection('users').document(email).collection('applications')
        docs = apps_ref.stream()
        
        records = []
        for doc in docs:
            app = doc.to_dict()
            applied_date = app.get("applied_date")
            if applied_date:
                dt_date = applied_date.date() if hasattr(applied_date, 'date') else None
                if dt_date:
                    records.append({
                        "Company": app.get("company_name", "Unknown"),
                        "Status": app.get("status", "Applied"),
                        "Date": dt_date
                    })
        
        if not records:
            st.info("No application records yet. Start applying to build your data! 🚀")
            return
            
        all_dates = [r["Date"] for r in records]
        min_date = min(all_dates)
        max_date = max(all_dates)
        
        st.write("##### 📅 Timeframe Filter")
        col1, col2 = st.columns([1, 2])
        with col1:
            date_range = st.date_input(
                "Select Date Range:", 
                value=(min_date, max_date), 
                min_value=min_date, 
                max_value=max_date
            )
        
        if len(date_range) == 2:
            start_date, end_date = date_range
            filtered_records = [r for r in records if start_date <= r["Date"] <= end_date]
        else:
            filtered_records = records
        
        total_applied = len(filtered_records)
        interviews = sum(1 for r in filtered_records if r["Status"] == "Interviewing")
        rejections = sum(1 for r in filtered_records if r["Status"] == "Rejected")
        
        conversion_rate = (interviews / total_applied * 100) if total_applied > 0 else 0.0
        
        st.markdown("---")
        st.markdown("### 📊 Conversion Overview")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Applied", total_applied)
        c2.metric("Interviews", interviews)
        c3.metric("Rejections", rejections)
        c4.metric("Conversion Rate", f"{conversion_rate:.1f}%")
        
        st.markdown("---")
        st.markdown("### 🏢 Filtered Companies")
        if filtered_records:
            sorted_records = sorted(filtered_records, key=lambda x: x["Date"], reverse=True)
            st.dataframe(sorted_records, use_container_width=True, hide_index=True)
        else:
            st.write("No records found for this period.")
            
    except Exception as e:
        st.error(f"❌ Failed to load analysis data: {e}")

def render_dashboard(db, email: str):
    """
    Fetch and render job applications on the dashboard.
    """
    st.subheader("📊 Your Job Applications")
    
    try:
        apps_ref = db.collection('users').document(email).collection('applications')
        query = apps_ref.order_by('applied_date', direction=firestore.Query.DESCENDING)
        docs = query.stream()
        
        has_records = False
        for doc in docs:
            has_records = True
            app_data = doc.to_dict()
            doc_id = doc.id
            
            company = app_data.get("company_name", "Unknown")
            status = app_data.get("status", "Applied")
            
            applied_date = app_data.get("applied_date")
            date_str = applied_date.strftime("%Y-%m-%d %H:%M") if applied_date else "N/A"
            
            status_emoji = {"Applied": "📤", "Interviewing": "💬", "Rejected": "💔"}.get(status, "📄")
            
            with st.expander(f"{status_emoji} {company} - {status} ({date_str})"):
                st.write(f"**Applied Date:** {date_str}")
                
                if app_data.get("interview_date"):
                    st.write(f"**Interview Date:** {app_data['interview_date'].strftime('%Y-%m-%d %H:%M')}")
                if app_data.get("rejected_date"):
                    st.write(f"**Rejected Date:** {app_data['rejected_date'].strftime('%Y-%m-%d %H:%M')}")
                
                current_notes = app_data.get("notes", "")
                new_notes = st.text_area("Notes:", value=current_notes, key=f"notes_{doc_id}", height=68)
                
                st.divider()
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    options = ["Applied", "Interviewing", "Rejected"]
                    current_idx = options.index(status) if status in options else 0
                    new_status = st.selectbox("Update Status:", options, index=current_idx, key=f"select_{doc_id}")
                
                with col2:
                    st.write("")
                    if st.button("Update", key=f"btn_{doc_id}", use_container_width=True):
                        if new_status != status or new_notes != current_notes:
                            if update_application_status(db, email, doc_id, new_status, new_notes):
                                st.success("✅ Application updated!")
                                st.rerun()
        if not has_records:
            st.info("No job applications yet. Go apply for your first job! 🚀")
            
    except Exception as e:
        st.error(f"❌ Failed to load dashboard: {e}")