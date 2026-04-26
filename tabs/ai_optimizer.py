import streamlit as st
import json
from utils.ai_engine import optimize_resume
from components.ui_elements import get_glass_overlay_html, show_copy_button

def render_tab():
    st.header("🤖 Auto-Optimize Resume based on JD")
    col1, col2 = st.columns(2)
    enable_ats = col1.checkbox("Enable ATS Keyword Analysis", value=True, key="opt_enable_ats")
    check_visa = col2.checkbox("Check Visa/Sponsorship Restrictions", value=True, key="opt_check_visa")
    
    jd_input = st.text_area("📄 Paste the Target Job Description (JD)", height=250, key="opt_jd_input")
    custom_prompt = st.text_area("🗣️ Custom Prompt (Optional)", value=st.session_state.get("custom_prompt", ""), key="opt_custom_prompt")
    
    if st.button("🚀 Start AI Optimization", type="primary", use_container_width=True):
        if not jd_input:
            st.warning("Please paste the JD content first!")
        elif not st.session_state.get("api_key"):
            st.error("Please set your API Key in the sidebar.")
        else:
            overlay = st.empty()
            overlay.markdown(get_glass_overlay_html("AI is crafting your resume...", st.session_state.get('animal_emoji', '🐕'), "#8a2be2"), unsafe_allow_html=True)
            
            success, result = optimize_resume(
                jd_input, custom_prompt, enable_ats, check_visa, 
                st.session_state.resume_data, 
                st.session_state.api_key, 
                st.session_state.ai_model
            )
            
            overlay.empty()
            
            if success:
                if result.get("visa_blocked"):
                    st.error(f"⛔ Visa Check Failed: {result.get('reason')}")
                else:
                    st.session_state.optimized_resume_data = result.get("optimized_resume")
                    st.session_state.changelog = result.get("changelog", "")
                    st.session_state.ats_metrics = result.get("keyword_analysis")
                    st.success("Optimization completed! Check the following tabs.")
            else:
                st.error(result)
