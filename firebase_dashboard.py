import streamlit as st
import firebase_admin
import numpy as np
import json
import plotly.graph_objects as go
import google.generativeai as genai
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

# ==========================================
# 0. AI Helpers (Predict Interview & Skill Gap)
# ==========================================
def predict_interview_questions(jd_text, resume_data):
    """Predict potential interview questions based on JD and Resume."""
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            return None
            
        genai.configure(api_key=api_key)
        model_name = st.session_state.get("ai_model", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        You are a senior interviewer. Based on the following Job Description (JD) and the candidate's Resume, 
        predict 5 technical questions and 3 behavioral questions that are most likely to be asked.
        Focus on the candidate's specific experiences and how they relate to the JD requirements.
        Return ONLY valid JSON.
        
        Format:
        {{
            "technical": ["Question 1", "Question 2", ...],
            "behavioral": ["Question 1", "Question 2", ...]
        }}
        
        [JD]: {jd_text}
        [Resume]: {json.dumps(resume_data)}
        """
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        return json.loads(response.text)
    except Exception:
        return None

def analyze_skill_gap(jd_text, resume_data):
    """Analyze skill gap and return data for radar chart."""
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            return None
            
        genai.configure(api_key=api_key)
        model_name = st.session_state.get("ai_model", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        Analyze the match between the candidate's Resume and the Job Description (JD).
        Extract 5 key categories (e.g., Programming, Cloud, Soft Skills, Tools, Domain Knowledge).
        For each category, provide a score (0-100) for the candidate's proficiency and the job's requirement level.
        Return ONLY valid JSON.
        
        Format:
        {{
            "categories": ["Category 1", "Category 2", ...],
            "candidate_scores": [80, 70, ...],
            "requirement_scores": [90, 80, ...]
        }}
        
        [JD]: {jd_text}
        [Resume]: {json.dumps(resume_data)}
        """
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        return json.loads(response.text)
    except Exception:
        return None

# ==========================================
# 1. 初始化與連接 Firebase
# ==========================================
@st.cache_resource
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
def save_application(db, email: str, company_name: str, resume_json: dict, jd_text: str = ""):
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
            "jd_text": jd_text,
            "interview_date": None,
            "rejected_date": None,
            "notes": ""
        }
        
        doc_ref.set(data)
        st.session_state.force_refresh_apps = True
        return True
    except Exception as e:
        st.error(f"❌ Error saving application record: {e}")
        return False

# ==========================================
# 3. & 4. Dashboard Logic
# ==========================================
def delete_application(db, email: str, doc_id: str):
    """Delete an application tracking record from Firestore."""
    try:
        db.collection('users').document(email).collection('applications').document(doc_id).delete()
        st.session_state.force_refresh_apps = True
        return True
    except Exception as e:
        st.error(f"❌ Error deleting application: {e}")
        return False

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
        st.session_state.force_refresh_apps = True
        return True
    except Exception as e:
        st.error(f"❌ Error updating application: {e}")
        return False

def fetch_applications(db, email):
    """Fetch applications once and cache them in session_state to prevent 429 Quota Exceeded."""
    if "app_records" not in st.session_state or st.session_state.get("force_refresh_apps", True):
        try:
            apps_ref = db.collection('users').document(email).collection('applications')
            query = apps_ref.order_by('applied_date', direction=firestore.Query.DESCENDING)
            docs = query.stream()
            
            records = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                records.append(data)
            
            st.session_state.app_records = records
            st.session_state.force_refresh_apps = False
        except Exception as e:
            st.error(f"❌ Error fetching applications: {e}")
            return []
    return st.session_state.app_records

def render_interview_progress(db, email: str):
    """
    Render Interview Progress and Conversion Rate with timeframe filtering.
    """
    try:
        app_records = fetch_applications(db, email)
        
        records = []
        for app in app_records:
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
            st.info("No application records yet. Start applying to build your data.")
            return
            
        all_dates = [r["Date"] for r in records]
        min_date = min(all_dates)
        max_date = max(all_dates)
        today = datetime.now().date()
        
        with st.container(border=True):
            st.markdown("### Performance Overview")
            col_filter, col_metrics = st.columns([1, 3])
            
            with col_filter:
                st.caption("Timeframe Filter")
                time_filter = st.selectbox(
                    "Timeframe",
                    ["Last 24 Hours", "Last 3 Days", "Last 7 Days", "Last 30 Days", "All Time", "Custom Range"],
                    index=0,
                    label_visibility="collapsed"
                )
                
                if time_filter == "Last 24 Hours":
                    start_date, end_date = today - timedelta(days=1), today
                elif time_filter == "Last 3 Days":
                    start_date, end_date = today - timedelta(days=3), today
                elif time_filter == "Last 7 Days":
                    start_date, end_date = today - timedelta(days=7), today
                elif time_filter == "Last 30 Days":
                    start_date, end_date = today - timedelta(days=30), today
                elif time_filter == "All Time":
                    start_date, end_date = min_date, max(max_date, today)
                else:
                    default_start = max(min_date, max_date - timedelta(days=1))
                    date_range = st.date_input(
                        "Select Date Range:", 
                        value=(default_start, max_date), 
                        min_value=min_date, 
                        max_value=max(max_date, today),
                        key="dashboard_date_range",
                        label_visibility="collapsed"
                    )
                    if len(date_range) == 2:
                        start_date, end_date = date_range
                    else:
                        start_date, end_date = min_date, max_date
                
                st.session_state.dashboard_active_date_range = (start_date, end_date)
            
            filtered_records = [r for r in records if start_date <= r["Date"] <= end_date]
            
            total_applied = len(filtered_records)
            interviews = sum(1 for r in filtered_records if r["Status"] == "Interviewing")
            rejections = sum(1 for r in filtered_records if r["Status"] == "Rejected")
            
            conversion_rate = (interviews / total_applied * 100) if total_applied > 0 else 0.0
            
            with col_metrics:
                st.caption("Conversion Metrics")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Applied", total_applied)
                c2.metric("Interviewing", interviews)
                c3.metric("Rejected", rejections)
                c4.metric("Conversion Rate", f"{conversion_rate:.1f}%")
                
        if total_applied > 0:
            st.progress(min(conversion_rate / 100.0, 1.0), text=f"Conversion Rate: {conversion_rate:.1f}%")
        
    except Exception as e:
        st.error(f"❌ Failed to load analysis data: {e}")

def render_dashboard(db, email: str):
    """
    Fetch and render job applications on the dashboard.
    """
    col_title, col_tz = st.columns([3, 1])
    with col_title:
        st.subheader("Application Pipeline")
    with col_tz:
        tz_offset = st.number_input("Timezone Offset (UTC)", min_value=-12.0, max_value=14.0, value=8.0, step=0.5)

    def get_local_time_str(dt_utc):
        if not dt_utc: return "N/A"
        local_dt = dt_utc + timedelta(hours=tz_offset)
        return local_dt.strftime("%Y-%m-%d %H:%M")

    try:
        app_records = fetch_applications(db, email)
        
        date_range = st.session_state.get("dashboard_active_date_range")
        start_date, end_date = None, None
        if date_range and len(date_range) == 2:
            start_date, end_date = date_range
            
        valid_records = []
        for app_data in app_records:
            applied_date = app_data.get("applied_date")
            
            if start_date and end_date and applied_date:
                dt_date = applied_date.date() if hasattr(applied_date, 'date') else None
                if dt_date and not (start_date <= dt_date <= end_date):
                    continue
                    
            valid_records.append(app_data)
            
        if not valid_records:
            st.info("No job applications found in this timeframe.")
            return
            
        # 分類 Pipeline 狀態
        applied_records = [r for r in valid_records if r.get("status") == "Applied"]
        interviewing_records = [r for r in valid_records if r.get("status") == "Interviewing"]
        rejected_records = [r for r in valid_records if r.get("status") == "Rejected"]
        
        # 建立 Pipeline 分頁
        tab_all, tab_applied, tab_interviewing, tab_rejected = st.tabs([
            f"All Records ({len(valid_records)})", 
            f"Applied ({len(applied_records)})", 
            f"Interviewing ({len(interviewing_records)})", 
            f"Rejected ({len(rejected_records)})"
        ])
        
        def render_record_list(record_list, tab_name):
            if not record_list:
                st.caption("No applications in this stage.")
                return
                
            for app_data in record_list:
                doc_id = app_data['id']
                company = app_data.get("company_name", "Unknown")
                status = app_data.get("status", "Applied")
                date_str = get_local_time_str(app_data.get("applied_date"))
                
                with st.expander(f"{company} — {status} ({date_str})", expanded=False):
                    # 現代化佈局: 左側為資訊, 右側為快捷操作區塊
                    c_info, c_actions = st.columns([1, 1])
                    
                    with c_info:
                        st.markdown(f"**Applied:** `{date_str}`")
                        if app_data.get("interview_date"):
                            st.markdown(f"**Interview:** `{get_local_time_str(app_data['interview_date'])}`")
                        if app_data.get("rejected_date"):
                            st.markdown(f"**Rejected:** `{get_local_time_str(app_data['rejected_date'])}`")
                        
                        st.write("")
                        with st.popover("View Documents & JD", use_container_width=True):
                            st.markdown("**Job Description:**")
                            st.info(app_data.get("jd_text", "No JD saved for this application."))
                            st.markdown("**Saved Resume JSON:**")
                            st.json(app_data.get("resume_json", {}))
                            
                    with c_actions:
                        current_notes = app_data.get("notes", "")
                        new_notes = st.text_area("Notes", value=current_notes, key=f"notes_{tab_name}_{doc_id}", height=100, label_visibility="collapsed", placeholder="Add your interview notes or follow-up reminders here...")
                        
                        # 操作按鈕列
                        col_stat, col_upd, col_prep, col_del = st.columns([4, 2, 2, 2])
                        with col_stat:
                            options = ["Applied", "Interviewing", "Rejected"]
                            current_idx = options.index(status) if status in options else 0
                            new_status = st.selectbox("Status", options, index=current_idx, key=f"select_{tab_name}_{doc_id}", label_visibility="collapsed")
                        with col_upd:
                            if st.button("Update", key=f"btn_{tab_name}_{doc_id}", use_container_width=True, type="primary"):
                                if new_status != status or new_notes != current_notes:
                                    if update_application_status(db, email, doc_id, new_status, new_notes):
                                        st.toast("Application updated successfully.")
                                        st.rerun()
                                else:
                                    st.toast("No changes detected.")
                        
                        with col_prep:
                            # --- 補回你原本強大的面試準備按鈕 ---
                            btn_prep = st.button("🧠 Prep", key=f"prep_{tab_name}_{doc_id}", use_container_width=True, help="Predict interview questions for this specific role")
                            btn_radar = st.button("📊 Radar", key=f"radar_{tab_name}_{doc_id}", use_container_width=True, help="Analyze skill gap for this specific role")
                            
                            if btn_prep:
                                with st.spinner("AI is analyzing JD and Resume..."):
                                    questions = predict_interview_questions(app_data.get("jd_text", ""), app_data.get("resume_json", {}))
                                    if questions:
                                        st.session_state[f"prep_result_{doc_id}"] = questions
                                        if f"radar_result_{doc_id}" in st.session_state: del st.session_state[f"radar_result_{doc_id}"]
                                    else:
                                        st.error("Failed to generate questions. Check API key.")
                            
                            if btn_radar:
                                with st.spinner("Analyzing skill match..."):
                                    gap_data = analyze_skill_gap(app_data.get("jd_text", ""), app_data.get("resume_json", {}))
                                    if gap_data:
                                        st.session_state[f"radar_result_{doc_id}"] = gap_data
                                        if f"prep_result_{doc_id}" in st.session_state: del st.session_state[f"prep_result_{doc_id}"]
                                    else:
                                        st.error("Failed to generate radar data.")
                        
                        with col_del:
                            if st.button("Del", key=f"del_{tab_name}_{doc_id}", use_container_width=True):
                                if delete_application(db, email, doc_id):
                                    st.toast("Record deleted.")
                                    st.rerun()
                        
                        # 如果有預測結果，顯示在下方
                        if f"prep_result_{doc_id}" in st.session_state:
                            q_data = st.session_state[f"prep_result_{doc_id}"]
                            with st.container(border=True):
                                st.markdown("##### 🎯 Predicted Interview Questions")
                                t_col, b_col = st.columns(2)
                                with t_col:
                                    st.markdown("**💻 Tech Questions**")
                                    for q in q_data.get("technical", []): st.caption(f"- {q}")
                                with b_col:
                                    st.markdown("**🤝 Behavioral (STAR)**")
                                    for q in q_data.get("behavioral", []): st.caption(f"- {q}")
                                if st.button("Close", key=f"close_prep_{doc_id}"):
                                    del st.session_state[f"prep_result_{doc_id}"]
                                    st.rerun()

                        # 如果有雷達圖結果
                        if f"radar_result_{doc_id}" in st.session_state:
                            gap_data = st.session_state[f"radar_result_{doc_id}"]
                            with st.container(border=True):
                                st.markdown("##### 🕸️ Skill Gap Analysis")
                                import plotly.graph_objects as go
                                fig = go.Figure()
                                fig.add_trace(go.Scatterpolar(r=gap_data['candidate_scores'], theta=gap_data['categories'], fill='toself', name='Proficiency'))
                                fig.add_trace(go.Scatterpolar(r=gap_data['requirement_scores'], theta=gap_data['categories'], fill='toself', name='Requirement'))
                                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True, margin=dict(l=40, r=40, t=40, b=40), height=300)
                                st.plotly_chart(fig, use_container_width=True)
                                if st.button("Close", key=f"close_radar_{doc_id}"):
                                    del st.session_state[f"radar_result_{doc_id}"]
                                    st.rerun()
                                    
        with tab_all: render_record_list(valid_records, "all")
        with tab_applied: render_record_list(applied_records, "applied")
        with tab_interviewing: render_record_list(interviewing_records, "interviewing")
        with tab_rejected: render_record_list(rejected_records, "rejected")
            
    except Exception as e:
        st.error(f"❌ Failed to load dashboard: {e}")