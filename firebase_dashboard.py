import streamlit as st
import streamlit.components.v1 as components 
import firebase_admin
import base64
import hashlib
import json
import logging
import re
import plotly.graph_objects as go
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from theme import TOKENS, FONT_STACK
from workspace import resume_is_empty
import docx_export
import pdf_export

# ==========================================
# 0. Pure helpers (unit-tested in tests/test_tracker_analytics.py)
# ==========================================
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Registration is open (no email verification), so it is throttled instead:
# a global daily cap keeps a script from filling Firestore, and a per-IP cap
# keeps one person from doing it slowly. IPs are stored hashed.
MAX_REGISTRATIONS_PER_DAY = 50
MAX_REGISTRATIONS_PER_IP_PER_DAY = 3
MIN_PASSWORD_LENGTH = 8
REGISTRATION_LIMITS_COLLECTION = "registration_limits"

# One message for "no such account" and "wrong password", so the login form
# cannot be used to find out which emails are registered.
LOGIN_FAILED_MESSAGE = "Email or password is incorrect."

# Shown to users in place of raw exception text. Details go to the server log
# (visible in Streamlit Cloud's "Manage app"), never to the page: Firestore
# errors can carry the project id, collection paths and document ids.
GENERIC_DB_ERROR = "Something went wrong talking to the database. Please try again."

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_credentials(email, password):
    """Error message for a registration attempt, or None when acceptable."""
    email = (email or "").strip()
    if not email or not password:
        return "Email and password are required."
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return "Enter a valid email address."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def registration_allowed(total_today, ip_today):
    """Whether one more sign-up fits under today's caps."""
    if total_today >= MAX_REGISTRATIONS_PER_DAY:
        return False, "Sign-ups are paused for today. Please try again tomorrow."
    if ip_today >= MAX_REGISTRATIONS_PER_IP_PER_DAY:
        return False, "Too many accounts created from this network today."
    return True, None


def ip_bucket(ip_address):
    """Hashed, truncated key for the per-IP counter - enough to rate-limit,
    not enough to reconstruct the address. None (no IP available, e.g. a
    proxy that strips it) shares one bucket."""
    return hashlib.sha256((ip_address or "unknown").encode("utf-8")).hexdigest()[:16]


def funnel_counts(records):
    """(applied, interviewed, offered) for the conversion funnel.

    Status is single-valued, so "Interviewed" cannot be read off it: a record
    that went Interviewing → Rejected is Rejected now but was still an
    interview. Count a record as interviewed when it ever reached that stage
    (interview_date set) or is at a stage that implies it (Interviewing,
    Offered - an offer without a logged interview still took one).
    """
    applied = len(records)
    interviewed = sum(
        1 for r in records
        if r.get("interview_date") or r.get("status") in ("Interviewing", "Offered")
    )
    offered = sum(1 for r in records if r.get("status") == "Offered")
    return applied, interviewed, offered


def browser_timezone(tz_name, tz_offset_minutes):
    """A tzinfo for the viewer's browser, from st.context.

    `tz_name` is an IANA name ("Asia/Taipei"); `tz_offset_minutes` is JS
    getTimezoneOffset(): minutes to ADD to local time to reach UTC, so UTC+8
    arrives as -480. Either may be None (AppTest, or a very old browser);
    the fallback is UTC rather than a guessed region.
    """
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    if tz_offset_minutes is not None:
        return timezone(-timedelta(minutes=tz_offset_minutes))
    return timezone.utc


def format_local_time(dt_utc, tz):
    """"2026-10-06 15:52" in `tz`, or "N/A". Naive datetimes are taken as UTC,
    which is what Firestore hands back after a SERVER_TIMESTAMP write."""
    if not dt_utc:
        return "N/A"
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def login_lockout_remaining(user_data, now):
    """Minutes left on an account lockout, or 0 when it may try again."""
    locked_until = user_data.get("locked_until")
    if not locked_until:
        return 0
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    remaining = (locked_until - now).total_seconds()
    return max(0, int(remaining // 60) + (1 if remaining % 60 else 0))


def login_failure_update(user_data, now):
    """Firestore update after a wrong password: bump the counter, and on the
    MAX_LOGIN_ATTEMPTS-th miss lock the account for LOCKOUT_MINUTES."""
    attempts = int(user_data.get("failed_attempts") or 0) + 1
    if attempts >= MAX_LOGIN_ATTEMPTS:
        return {"failed_attempts": 0, "locked_until": now + timedelta(minutes=LOCKOUT_MINUTES)}
    return {"failed_attempts": attempts, "locked_until": None}

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
        except Exception:
            logger.exception("Firebase initialization failed")
            st.error(GENERIC_DB_ERROR)
            return None
    
    return firestore.client()

# ==========================================
# 1.5 Authentication
# ==========================================
def register_user(db, email: str, password: str, client_ip=None):
    """Register a new user with hashed password, under the daily caps.

    `client_ip` is st.context.ip_address at the call site (passed in rather
    than read here so this stays testable without a script run context).
    """
    try:
        if db is None:
            return False, "Firebase is not initialized."
        email = (email or "").strip()
        problem = validate_credentials(email, password)
        if problem:
            return False, problem

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bucket = ip_bucket(client_ip)
        limits_ref = db.collection(REGISTRATION_LIMITS_COLLECTION).document(today)
        limits_doc = limits_ref.get()
        limits = limits_doc.to_dict() if limits_doc.exists else {}
        ok, msg = registration_allowed(
            int(limits.get("total") or 0),
            int((limits.get("ips") or {}).get(bucket) or 0),
        )
        if not ok:
            return False, msg

        doc_ref = db.collection('user_auth').document(email)
        if doc_ref.get().exists:
            # Deliberately not "already registered": without email
            # verification that would confirm the address has an account.
            return False, "Could not create an account with this email. If you already have one, log in instead."

        hashed_pwd = generate_password_hash(password)
        doc_ref.set({"password_hash": hashed_pwd, "created_at": firestore.SERVER_TIMESTAMP})
        limits_ref.set(
            {"total": firestore.Increment(1), "ips": {bucket: firestore.Increment(1)}},
            merge=True,
        )
        return True, "Registration successful, please log in!"
    except Exception:
        logger.exception("register_user failed")
        return False, GENERIC_DB_ERROR

def authenticate_user(db, email: str, password: str):
    """Authenticate user login"""
    try:
        if db is None:
            return False, "Firebase is not initialized."
        email = (email or "").strip()
        if not email or not password:
            return False, "Email and password are required."
        doc_ref = db.collection('user_auth').document(email)
        doc = doc_ref.get()
        if not doc.exists:
            return False, LOGIN_FAILED_MESSAGE
        
        user_data = doc.to_dict()
        now = datetime.now(timezone.utc)
        # Per-account lockout after repeated wrong passwords. Checked before
        # the hash so a locked account gives the same answer to a right and a
        # wrong guess. Trade-off: someone who knows the email can lock its
        # owner out for LOCKOUT_MINUTES; accepted over leaving guessing free.
        minutes_left = login_lockout_remaining(user_data, now)
        if minutes_left:
            return False, f"Too many failed attempts. Try again in {minutes_left} min."
        if check_password_hash(user_data.get("password_hash", ""), password):
            if user_data.get("failed_attempts") or user_data.get("locked_until"):
                doc_ref.update({"failed_attempts": 0, "locked_until": None})
            return True, "Login successful!"
        update = login_failure_update(user_data, now)
        doc_ref.update(update)
        if update.get("locked_until"):
            return False, f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} min."
        return False, LOGIN_FAILED_MESSAGE
    except Exception:
        logger.exception("authenticate_user failed")
        return False, GENERIC_DB_ERROR

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
    except Exception:
        logger.exception("Error saving profile")
        return False, GENERIC_DB_ERROR

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
    except Exception:
        logger.exception("Error loading profile")
        st.error(GENERIC_DB_ERROR)
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
    except Exception:
        logger.exception("Error saving application record")
        st.error(GENERIC_DB_ERROR)
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
    except Exception:
        logger.exception("Error deleting application")
        st.error(GENERIC_DB_ERROR)
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
    except Exception:
        logger.exception("Error updating application")
        st.error(GENERIC_DB_ERROR)
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
        except Exception:
            logger.exception("Error fetching applications")
            st.error(GENERIC_DB_ERROR)
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
                        "status": app.get("status", "Applied"),
                        "interview_date": app.get("interview_date"),
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
            
            total_applied, total_interviewed, offers = funnel_counts(filtered_records)
            interviews = sum(1 for r in filtered_records if r["status"] == "Interviewing")
            rejections = sum(1 for r in filtered_records if r["status"] == "Rejected")
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
        
    except Exception:
        logger.exception("Failed to load analysis data")
        st.error(GENERIC_DB_ERROR)

# Per-status colour for the row's status text, via Streamlit's built-in
# markdown colours so it tracks the theme instead of hard-coding hex here.
STATUS_COLORS = {
    "Applied": "blue",
    "Interviewing": "orange",
    "Offered": "green",
    "Rejected": "red",
}

def tracker_resume_pdf(resume_json, template_label):
    """PDF of a saved resume: same compiler and template mapping as the
    Generator's export, default full section order - a tracker row records
    what was sent, it is not a place to redesign it. None on failure; the
    compiler has already shown the error (or LATEX_MISSING_MESSAGE)."""
    return pdf_export.generate_preview_pdf_bytes(
        resume_json, pdf_export.template_file_for(template_label), list(pdf_export.BLOCK_ORDER_OPTIONS),
    )


def tracker_resume_docx(resume_json):
    """Word copy of a saved resume, or None if the data is too sparse."""
    try:
        if resume_is_empty(resume_json):
            return None
        return docx_export.build_resume_docx(resume_json, list(pdf_export.BLOCK_ORDER_OPTIONS))
    except Exception:
        return None


def render_application_dialog(db, email, app_data, local_time):
    """Open the preview dialog for one saved application, titled with the
    company name.

    st.dialog() fixes its title at decoration time, so the decorator is
    applied here, per call, instead of at import. Streamlit keys the
    underlying fragment on module + function name + element path, none of
    which change between calls, so this is as stable as a static decorator.

    Dialogs are fragments: widgets inside rerun only the dialog and keep it
    open, while an app-scope st.rerun() (after Update / Delete) closes it.
    It is therefore only ever called from the Preview button's `if` branch -
    calling it unconditionally would reopen it after every dismissal.
    """
    title = (app_data.get("company_name") or "").strip() or "Application"
    st.dialog(title, width="large")(_application_dialog_body)(db, email, app_data, local_time)


def _application_dialog_body(db, email, app_data, local_time):
    """Preview + download + edit for one saved application."""
    doc_id = app_data["id"]
    company = app_data.get("company_name") or "Unknown"
    status = app_data.get("status", "Applied")
    resume_json = app_data.get("resume_json") or {}
    role = (resume_json.get("target_role") or "").strip()

    facts = []
    if role:
        facts.append(role)
    facts.append(f":{STATUS_COLORS.get(status, 'gray')}[{status}]")
    facts.append(f"Applied {local_time(app_data.get('applied_date'))}")
    for label, field in (("Interview", "interview_date"), ("Offered", "offered_date"), ("Rejected", "rejected_date")):
        if app_data.get(field):
            facts.append(f"{label} {local_time(app_data[field])}")
    st.caption(" · ".join(facts))

    # --- export row --------------------------------------------------------
    tmpl_col, pdf_col, docx_col = st.columns([2, 1.2, 1.2])
    with tmpl_col:
        template_label = st.selectbox(
            "Template", ["Tech", "Business"],
            key=f"dlg_tmpl_{doc_id}", label_visibility="collapsed",
        )

    # Bounded per-session cache keyed by record + template. lualatex takes
    # seconds; reopening the same record must be instant. A failed compile
    # (None) is deliberately not cached, so a transient failure is retried
    # next time instead of sticking - same reasoning as base_preview_pdf()
    # in app.py.
    cache = st.session_state.setdefault("tracker_pdf_cache", {})
    cache_key = f"{doc_id}:{template_label}"
    if cache_key in cache:
        pdf_bytes = cache[cache_key]
    else:
        with st.spinner("Compiling PDF..."):
            pdf_bytes = tracker_resume_pdf(resume_json, template_label)
        if pdf_bytes:
            if len(cache) >= 8:
                del cache[next(iter(cache))]
            cache[cache_key] = pdf_bytes

    docx_bytes = tracker_resume_docx(resume_json)
    file_stem = _export_stem(resume_json)

    with pdf_col:
        if pdf_bytes:
            st.download_button(
                "Download PDF", pdf_bytes, f"{file_stem}_Resume.pdf",
                icon=":material/download:", key=f"dlg_pdf_{doc_id}", use_container_width=True,
            )
    with docx_col:
        if docx_bytes:
            st.download_button(
                "Download Word", docx_bytes, f"{file_stem}_Resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                icon=":material/description:", key=f"dlg_docx_{doc_id}", use_container_width=True,
            )

    # --- preview -----------------------------------------------------------
    if pdf_bytes:
        pdf_export.render_pdf_js(pdf_bytes, height=520)
    # A failed compile already reported itself via st.error inside pdf_export.

    # --- raw data ----------------------------------------------------------
    with st.expander("Saved job description & resume JSON"):
        st.markdown("**Job Description**")
        st.info(app_data.get("jd_text") or "No JD saved.")
        _render_copy_json_button(doc_id, resume_json)
        st.json(resume_json)

    # --- edit --------------------------------------------------------------
    st.divider()
    current_notes = app_data.get("notes", "") or ""
    new_notes = st.text_area(
        "Notes", value=current_notes, key=f"dlg_notes_{doc_id}", height=100,
        placeholder="Interview notes, follow-up reminders...",
    )
    options = ["Applied", "Interviewing", "Offered", "Rejected"]
    current_idx = options.index(status) if status in options else 0
    stat_col, upd_col, del_col = st.columns([2, 1.2, 1.2])
    with stat_col:
        new_status = st.selectbox(
            "Status", options, index=current_idx,
            key=f"dlg_status_{doc_id}", label_visibility="collapsed",
        )
    with upd_col:
        if st.button("Update", key=f"dlg_update_{doc_id}", type="primary", use_container_width=True):
            if new_status != status or new_notes != current_notes:
                if update_application_status(db, email, doc_id, new_status, new_notes):
                    st.session_state.pending_toast = "Application updated."
                    st.rerun()
            else:
                st.toast("No changes detected.")
    confirm_key = f"dlg_confirm_delete_{doc_id}"
    with del_col:
        if st.button("Delete", key=f"dlg_delete_{doc_id}", use_container_width=True):
            st.session_state[confirm_key] = True

    # Two-step delete: Firestore has no undo, so the first click only asks.
    if st.session_state.get(confirm_key):
        st.warning(f"Delete the {company} record? This cannot be undone.")
        yes_col, no_col = st.columns(2)
        with yes_col:
            if st.button("Yes, delete", key=f"dlg_delete_confirm_{doc_id}", type="primary", use_container_width=True):
                del st.session_state[confirm_key]
                if delete_application(db, email, doc_id):
                    st.session_state.pending_toast = "Record deleted."
                    st.rerun()
        with no_col:
            if st.button("Cancel", key=f"dlg_delete_cancel_{doc_id}", use_container_width=True):
                del st.session_state[confirm_key]
                st.rerun(scope="fragment")


def _export_stem(resume_json):
    """"Acme_Backend_Engineer" - mirrors app.export_file_name()'s naming so a
    file downloaded from the tracker sits next to the one downloaded at
    export time under the same name."""
    def part(value, fallback):
        text = str(value or fallback).strip().replace(" ", "_")
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
        return cleaned.strip("_") or fallback
    company = (resume_json.get("target_company") or "").strip()
    role = (resume_json.get("target_role") or "").strip()
    if company or role:
        return f"{part(company, 'Company')}_{part(role, 'Role')}"
    return part((resume_json.get("heading") or {}).get("name"), "Resume")


def _render_copy_json_button(doc_id, resume_json):
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


def render_dashboard(db, email: str):
    """
    Fetch and render job applications on the dashboard.
    """
    st.subheader("Application Pipeline")

    # Times are shown in the viewer's own browser timezone; no manual offset.
    viewer_tz = browser_timezone(st.context.timezone, st.context.timezone_offset)

    def get_local_time_str(dt_utc):
        return format_local_time(dt_utc, viewer_tz)

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
        
        def render_record(app_data, tab_name):
            """One tracker row: who, where it stands, and a Preview button.
            Everything editable lives in render_application_dialog(), so the
            row itself has no widgets that need fragment isolation."""
            doc_id = app_data['id']
            company = app_data.get("company_name") or "Unknown"
            status = app_data.get("status", "Applied")
            date_str = get_local_time_str(app_data.get("applied_date"))
            role = ((app_data.get("resume_json") or {}).get("target_role") or "").strip()

            with st.container(border=True):
                c_main, c_meta, c_btn = st.columns([3, 2, 1.2], vertical_alignment="center")
                with c_main:
                    st.markdown(f"**{company}**")
                    st.caption(role or "Role not recorded")
                with c_meta:
                    st.markdown(f":{STATUS_COLORS.get(status, 'gray')}[{status}]")
                    st.caption(f"Applied {date_str}")
                with c_btn:
                    if st.button(
                        "Preview", key=f"preview_{tab_name}_{doc_id}",
                        icon=":material/visibility:", use_container_width=True,
                        help="Preview and download the resume sent to this company",
                    ):
                        render_application_dialog(db, email, app_data, get_local_time_str)

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
            
    except Exception:
        logger.exception("Failed to load dashboard")
        st.error(GENERIC_DB_ERROR)
