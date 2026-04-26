import streamlit as st
import json
import streamlit_ace as st_ace
from datetime import datetime
from utils.ai_engine import parse_pdf_resume
from components.ui_elements import get_glass_overlay_html

@st.fragment
def render_json_editor():
    """使用 Fragment 包裝編輯器，避免全頁面重新整理"""
    json_str = json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False)
    edited_json = st_ace.st_ace(
        value=json_str,
        language="json",
        theme="dracula",
        height=500,
        key=f"base_resume_editor_{st.session_state.base_editor_key}",
        font_size=14,
        tab_size=2,
        show_gutter=True,
        auto_update=False,
    )
    
    if st.button("💾 Save JSON Changes", type="primary"):
        try:
            st.session_state.resume_data = json.loads(edited_json)
            st.session_state.base_resume_saved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.success("JSON data saved successfully!")
        except Exception as e:
            st.error(f"JSON format error: {e}")

def render_tab():
    st.header("👤 Edit Your Base Profile")
    st.info("This is your **Base Template**. AI will always use this as the ground truth.")
    
    with st.container(border=True):
        st.subheader("📥 Auto-Fill from PDF")
        uploaded_pdf = st.file_uploader("Upload your current PDF resume", type=["pdf"])
        if st.button("✨ Auto-Fill JSON from PDF", type="primary", use_container_width=True):
            if uploaded_pdf:
                overlay = st.empty()
                overlay.markdown(get_glass_overlay_html("Extracting data...", st.session_state.get('animal_emoji', '🐕'), "#8a2be2"), unsafe_allow_html=True)
                
                success, msg, parsed_json = parse_pdf_resume(
                    uploaded_pdf.getvalue(), 
                    st.session_state.get("api_key", ""),
                    st.session_state.get("ai_model", "gemini-2.5-flash")
                )
                
                overlay.empty()
                if success:
                    st.session_state.resume_data = parsed_json
                    st.session_state.base_editor_key += 1
                    st.rerun()
                else:
                    st.error(msg)
    
    render_json_editor()
