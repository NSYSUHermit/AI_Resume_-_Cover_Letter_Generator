import streamlit as st
from tabs import base_profile, ai_optimizer, editor_export
from firebase_dashboard import init_firebase, render_dashboard, render_interview_progress
from components.auth import render_auth_sidebar
import toml

# ---------------------------------------------------------
# 初始化與配置
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume Builder Pro", page_icon="🚀", layout="wide")

# 初始化 Session State
if "resume_data" not in st.session_state:
    st.session_state.resume_data = { "heading": {"name": "User"}, "experience": [], "education": [], "skills": {} }
if "base_editor_key" not in st.session_state:
    st.session_state.base_editor_key = 0
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

db = init_firebase()

# --- Sidebar ---
with st.sidebar:
    render_auth_sidebar(db)
    
    st.markdown("---")
    st.header("⚙️ Settings")
    st.text_input("🔑 Gemini API Key", type="password", key="api_key")
    st.selectbox("🧠 AI Model", ["gemini-2.5-flash", "gemini-2.5-pro"], key="ai_model")
    st.selectbox("🏃 Animal", ["🦦", "🦫", "🐕", "🦖"], key="animal_emoji")

# --- Main UI ---
st.title("🚀 AI-Powered Resume Builder Pro")

db = init_firebase()

tab1, tab2, tab3, tab4 = st.tabs([" Base Profile ", " AI Optimizer ", " Editor & Export ", " Job Tracker "])

with tab1:
    base_profile.render_tab()

with tab2:
    ai_optimizer.render_tab()

with tab3:
    editor_export.render_tab()

with tab4:
    if db:
        render_interview_progress(db, st.session_state.get("user_email", "guest"))
        render_dashboard(db, st.session_state.get("user_email", "guest"))
    else:
        st.error("Firebase not connected.")
