import streamlit as st
import streamlit.components.v1 as components 
import firebase_admin
import base64
import json
import plotly.graph_objects as go
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from ui_feedback import run_ai_call
from theme import TOKENS, FONT_STACK
import ai

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
            st.error(f"Firebase initialization failed: {e}")
            return None
    
    return firestore.client()

# ==========================================
# 1.5 Authentication
# ==========================================
def register_user(db, email: str, password: str):
    """Register a new user with hashed password"""
    try:
        if db is None:
            return False, "Firebase is not initialized."
        email = (email or "").strip()
        if not email or not password:
            return False, "Email and password are required."
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
        if db is None:
            return False, "Firebase is not initialized."
        email = (email or "").strip()
        if not email or not password:
            return False, "Email and password are required."
        doc = db.collection('user_auth').document(email).get()
        if not doc.exists:
            return False, "Account not found, please register first."
        
        user_data = doc.to_dict()
        if check_password_hash(user_data.get("password_hash", ""), password):
            return True, "Login successful!"
        return False, "Incorrect password."
    except Exception as e:
        return False, f"Login verification failed: {e}"

def save_user_profile(db, email: str, resume_data: dict, custom_prompt: str, api_key: str = ""):
    """Save base resume, custom prompt, and API key to Firestore."""
    try:
        doc_ref = db.collection('users').document(email).collection('profile').document('base_profile')
        data = {
            "base_resume": resume_data,
            "custom_prompt": custom_prompt,
            "last_updated": firestore.SERVER_TIMESTAMP
        }
        if api_key:
            data["api_key"] = api_key
        doc_ref.set(data, merge=True)
        return True, "Profile synced to cloud successfully."
    except Exception as e:
        st.error(f"Error saving profile: {e}")
        return False, f"Error saving profile: {e}"

def load_user_profile(db, email: str):
    """Load base resume, custom prompt, and API key from Firestore."""
    try:
        doc_ref = db.collection('users').document(email).collection('profile').document('base_profile')
        doc = doc_ref.get()
        if doc.exists:
            profile_data = doc.to_dict()
            return profile_data.get("base_resume"), profile_data.get("custom_prompt"), profile_data.get("api_key")
        else:
            return None, None, None
    except Exception as e:
        st.error(f"Error loading profile: {e}")
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
            "offered_date": None,
            "rejected_date": None,
            "notes": ""
        }
        
        doc_ref.set(data)
        st.session_state.force_refresh_apps = True
        return True
    except Exception as e:
        st.error(f"Error saving application record: {e}")
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
        st.error(f"Error deleting application: {e}")
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
        elif new_status == "Offered":
            update_data["offered_date"] = firestore.SERVER_TIMESTAMP
        elif new_status == "Rejected":
            update_data["rejected_date"] = firestore.SERVER_TIMESTAMP
            
        doc_ref.update(update_data)
        st.session_state.force_refresh_apps = True
        return True
    except Exception as e:
        st.error(f"Error updating application: {e}")
        return False

def fetch_applications(db, email):
    """Fetch applications once and cache them in session_state to prevent 429 Quota Exceeded.

    The cache is keyed by account: without that, signing out and signing back in
    as someone else served the previous user's records from session state.
    """
    if st.session_state.get("app_records_email") != email:
        st.session_state.force_refresh_apps = True
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
            st.session_state.app_records_email = email
            st.session_state.force_refresh_apps = False
        except Exception as e:
            st.error(f"Error fetching applications: {e}")
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
                    index=4,
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
            offers = sum(1 for r in filtered_records if r["Status"] == "Offered")
            rejections = sum(1 for r in filtered_records if r["Status"] == "Rejected")
            
            # 累積計算漏斗層級，假設拿到 Offer 或正在面試都算進入了「面試階段」
            total_interviewed = interviews + offers
            offer_rate = (offers / total_applied * 100) if total_applied > 0 else 0.0
            
            with col_metrics:
                st.caption("Conversion Metrics")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Applied", total_applied)
                c2.metric("Interviewing", interviews)
                c3.metric("Offered", offers)
                c4.metric("Rejected", rejections)
                c5.metric("Offer Rate", f"{offer_rate:.1f}%")
                
        if total_applied > 0:
            # 使用 Plotly 繪製轉換漏斗圖
            fig = go.Figure(go.Funnel(
                y=["Applied", "Interviewed", "Offered"],
                x=[total_applied, total_interviewed, offers],
                textinfo="value+percent initial",
                marker={"color": ["#3b82f6", "#f59e0b", "#10b981"]}
            ))
            fig.update_layout(
                margin=dict(l=20, r=20, t=30, b=20), 
                height=300, 
                paper_bgcolor="rgba(0,0,0,0)", 
                plot_bgcolor="rgba(0,0,0,0)",
                title="Application Conversion Funnel"
            )
            st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Failed to load analysis data: {e}")

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

        if not app_records:
            st.info("No job applications found yet.")
            return

        def get_record_date(record):
            applied_date = record.get("applied_date")
            return applied_date.date() if hasattr(applied_date, "date") else None

        def get_sort_timestamp(record):
            applied_date = record.get("applied_date")
            if hasattr(applied_date, "timestamp"):
                return applied_date.timestamp()
            return 0

        dated_records = [get_record_date(record) for record in app_records]
        dated_records = [record_date for record_date in dated_records if record_date]
        min_record_date = min(dated_records) if dated_records else None
        max_record_date = max(dated_records) if dated_records else None
        today = datetime.now().date()

        with st.container(border=True):
            search_col, timeframe_col, sort_col = st.columns([2.2, 1.25, 1])
            with search_col:
                search_value = st.text_input(
                    "Search Company",
                    key="pipeline_company_search",
                    placeholder="Search company name...",                )
            with timeframe_col:
                list_time_filter = st.selectbox(
                    "List Timeframe",
                    ["All Time", "Last 30 Days", "Last 7 Days", "Custom Range"],
                    key="pipeline_list_time_filter",                )
            with sort_col:
                sort_order = st.selectbox(
                    "Sort",
                    ["Newest first", "Oldest first"],
                    key="pipeline_sort_order",                )

            list_start_date, list_end_date = None, None
            if list_time_filter == "Last 30 Days":
                list_start_date, list_end_date = today - timedelta(days=30), today
            elif list_time_filter == "Last 7 Days":
                list_start_date, list_end_date = today - timedelta(days=7), today
            elif list_time_filter == "Custom Range" and min_record_date and max_record_date:
                default_start = max(min_record_date, max_record_date - timedelta(days=30))
                custom_range = st.date_input(
                    "Custom List Range",
                    value=(default_start, max_record_date),
                    min_value=min_record_date,
                    max_value=max(max_record_date, today),
                    key="pipeline_custom_date_range",                )
                if len(custom_range) == 2:
                    list_start_date, list_end_date = custom_range

        valid_records = []
        for app_data in app_records:
            record_date = get_record_date(app_data)
            if list_start_date and list_end_date and record_date:
                if not (list_start_date <= record_date <= list_end_date):
                    continue
            valid_records.append(app_data)

        search_query = (search_value or "").strip().lower()
        if search_query:
            valid_records = [
                record for record in valid_records
                if search_query in (record.get("company_name", "") or "").lower()
            ]

        valid_records = sorted(
            valid_records,
            key=get_sort_timestamp,
            reverse=(sort_order == "Newest first"),
        )

        if not valid_records:
            st.info("No matching applications found.")
            return

        # 分類 Pipeline 狀態
        applied_records = [r for r in valid_records if r.get("status") == "Applied"]
        interviewing_records = [r for r in valid_records if r.get("status") == "Interviewing"]
        offered_records = [r for r in valid_records if r.get("status") == "Offered"]
        rejected_records = [r for r in valid_records if r.get("status") == "Rejected"]
        
        stage_records = {
            "all": valid_records,
            "applied": applied_records,
            "interviewing": interviewing_records,
            "offered": offered_records,
            "rejected": rejected_records,
        }
        stage_labels = {
            "all": f"All Records ({len(valid_records)})",
            "applied": f"Applied ({len(applied_records)})",
            "interviewing": f"Interviewing ({len(interviewing_records)})",
            "offered": f"Offered ({len(offered_records)})",
            "rejected": f"Rejected ({len(rejected_records)})",
        }
        selected_stage = st.radio(
            "Pipeline Stage",
            list(stage_records.keys()),
            key="pipeline_stage_filter",
            horizontal=True,
            label_visibility="collapsed",
            format_func=lambda stage: stage_labels[stage],
        )
        selected_records = stage_records[selected_stage]

        batch_size = 20
        visible_key = f"pipeline_visible_count_{selected_stage}"
        feed_signature = json.dumps(
            {
                "stage": selected_stage,
                "search": search_query,
                "timeframe": list_time_filter,
                "start": str(list_start_date),
                "end": str(list_end_date),
                "sort": sort_order,
                "total": len(selected_records),
            },
            sort_keys=True,
        )
        if st.session_state.get("pipeline_feed_signature") != feed_signature:
            st.session_state.pipeline_feed_signature = feed_signature
            st.session_state[visible_key] = batch_size

        visible_count = min(st.session_state.get(visible_key, batch_size), len(selected_records))
        visible_records = selected_records[:visible_count]
        st.caption(f"Showing {visible_count} of {len(selected_records)} matching records.")
        
        @st.fragment
        def render_record(app_data, tab_name):
            """One tracker row, isolated so typing a note or changing a status
            reruns only this record instead of redrawing all 20."""
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
                    if app_data.get("offered_date"):
                        st.markdown(f"**Offered:** `{get_local_time_str(app_data['offered_date'])}`")
                    if app_data.get("rejected_date"):
                        st.markdown(f"**Rejected:** `{get_local_time_str(app_data['rejected_date'])}`")
                        
                    st.write("")
                    col_view, col_copy = st.columns(2)
                    with col_view:
                        if st.button("View Data", key=f"view_{tab_name}_{doc_id}", use_container_width=True):
                            st.session_state.active_tracker_detail = doc_id

                    with col_copy:
                        if st.session_state.get("active_tracker_detail") == doc_id:
                            if st.button("Hide Data", key=f"hide_{tab_name}_{doc_id}", use_container_width=True):
                                del st.session_state.active_tracker_detail
                                st.rerun()
                        else:
                            st.caption("Open View Data to copy JSON.")

                    if st.session_state.get("active_tracker_detail") == doc_id:
                        with st.container(border=True):
                            st.markdown("##### Saved Application Data")
                            st.markdown("**Job Description:**")
                            st.info(app_data.get("jd_text", "No JD saved."))
                            resume_json = app_data.get("resume_json", {})
                            resume_json_str = json.dumps(resume_json, ensure_ascii=False, indent=4)
                            b64_resume = base64.b64encode(resume_json_str.encode("utf-8")).decode("utf-8")
                            js_code = f"""try{{var b=window.atob("{b64_resume}");var len=b.length;var bytes=new Uint8Array(len);for(var i=0;i<len;i++){{bytes[i]=b.charCodeAt(i);}}var text=new TextDecoder("utf-8").decode(bytes);var btn=this;var cb=function(t){{if(navigator.clipboard&&window.isSecureContext){{return navigator.clipboard.writeText(t);}}else{{var ta=document.createElement("textarea");ta.value=t;ta.style.position="absolute";ta.style.left="-9999px";document.body.appendChild(ta);ta.select();document.execCommand("copy");ta.remove();return Promise.resolve();}}}};cb(text).then(function(){{btn.innerText="Copied";btn.style.borderColor="{TOKENS['success']}";btn.style.color="{TOKENS['success']}";btn.style.backgroundColor="#ecfdf5";setTimeout(function(){{btn.innerText="Copy JSON";btn.style.borderColor="{TOKENS['border']}";btn.style.color="{TOKENS['text']}";btn.style.backgroundColor="{TOKENS['surface']}";}},2000);}});}}catch(e){{console.error(e);this.innerText="Error";}}"""
                            html_copy_json = f"""
                            <body style="margin:0; padding:0; background:transparent;">
                                <button id="copyJsonBtn_{doc_id}" onclick='{js_code}' style="
                                    width:100%; height:38px; border-radius:8px;
                                    background:{TOKENS['surface']}; color:{TOKENS['text']}; border:1px solid {TOKENS['border']};
                                    cursor:pointer; font-weight:650; font-size: 14px;
                                    font-family: {FONT_STACK};
                                    display: flex; align-items: center; justify-content: center;
                                    box-shadow:0 1px 2px rgba(15,23,42,0.06);
                                    transition:background-color 180ms ease-in-out,border-color 180ms ease-in-out,box-shadow 180ms ease-in-out,color 180ms ease-in-out;">
                                    Copy JSON
                                </button>
                            </body>
                            """
                            components.html(html_copy_json, height=45)
                            st.markdown("**Saved Resume JSON:**")
                            st.json(resume_json)
                            
                with c_actions:
                    current_notes = app_data.get("notes", "")
                    new_notes = st.text_area("Notes", value=current_notes, key=f"notes_{tab_name}_{doc_id}", height=100, label_visibility="collapsed", placeholder="Add your interview notes or follow-up reminders here...")
                        
                    # 操作按鈕列
                    col_stat, col_upd, col_prep, col_del = st.columns([4, 2, 2, 2])
                    with col_stat:
                        options = ["Applied", "Interviewing", "Offered", "Rejected"]
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
                        btn_prep = st.button("Prep", key=f"prep_{tab_name}_{doc_id}", use_container_width=True, help="Predict interview questions for this specific role")
                        btn_radar = st.button("Radar", key=f"radar_{tab_name}_{doc_id}", use_container_width=True, help="Analyze skill gap for this specific role")
                            
                        if btn_prep:
                            questions = run_ai_call(
                                "Preparing interview questions",
                                lambda: ai.predict_interview_questions(
                                    app_data.get("jd_text", ""),
                                    app_data.get("resume_json", {}),
                                    st.session_state.get("api_key", ""),
                                ),
                                success=lambda r: r is not None,
                            )
                            if questions:
                                st.session_state[f"prep_result_{doc_id}"] = questions
                                if f"radar_result_{doc_id}" in st.session_state: del st.session_state[f"radar_result_{doc_id}"]
                            else:
                                st.error("Failed to generate questions. Check API key.")
                            
                        if btn_radar:
                            gap_data = run_ai_call(
                                "Analyzing skill match",
                                lambda: ai.analyze_skill_gap(
                                    app_data.get("jd_text", ""),
                                    app_data.get("resume_json", {}),
                                    st.session_state.get("api_key", ""),
                                ),
                                success=lambda r: r is not None,
                            )
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
                            st.markdown("##### Predicted Interview Questions")
                            t_col, b_col = st.columns(2)
                            with t_col:
                                st.markdown("**Technical Questions**")
                                for q in q_data.get("technical", []): st.caption(f"- {q}")
                            with b_col:
                                st.markdown("**Behavioral (STAR)**")
                                for q in q_data.get("behavioral", []): st.caption(f"- {q}")
                            if st.button("Close", key=f"close_prep_{doc_id}"):
                                del st.session_state[f"prep_result_{doc_id}"]
                                st.rerun()

                    # 如果有雷達圖結果
                    if f"radar_result_{doc_id}" in st.session_state:
                        gap_data = st.session_state[f"radar_result_{doc_id}"]
                        with st.container(border=True):
                            st.markdown("##### Skill Gap Analysis")
                            import plotly.graph_objects as go
                            fig = go.Figure()
                            fig.add_trace(go.Scatterpolar(r=gap_data['candidate_scores'], theta=gap_data['categories'], fill='toself', name='Proficiency'))
                            fig.add_trace(go.Scatterpolar(r=gap_data['requirement_scores'], theta=gap_data['categories'], fill='toself', name='Requirement'))
                            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True, margin=dict(l=40, r=40, t=40, b=40), height=300)
                            st.plotly_chart(fig, use_container_width=True)
                            if st.button("Close", key=f"close_radar_{doc_id}"):
                                del st.session_state[f"radar_result_{doc_id}"]
                                st.rerun()

        def render_record_list(record_list, tab_name):
            if not record_list:
                st.caption("No applications in this stage.")
                return
            for app_data in record_list:
                render_record(app_data, tab_name)

        with st.container(height=720):
            render_record_list(visible_records, selected_stage)

        remaining_records = len(selected_records) - visible_count
        if remaining_records > 0:
            load_count = min(batch_size, remaining_records)
            load_col_left, load_col_mid, load_col_right = st.columns([1, 1.2, 1])
            with load_col_mid:
                if st.button(
                    f"Load {load_count} more",
                    key=f"load_more_{selected_stage}",
                    use_container_width=True,                ):
                    st.session_state[visible_key] = min(len(selected_records), visible_count + batch_size)
                    st.rerun()
        else:
            st.caption("All matching records are loaded.")
            
    except Exception as e:
        st.error(f"Failed to load dashboard: {e}")
