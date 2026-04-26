import streamlit as st
import json
import base64
import streamlit.components.v1 as components
from utils.ai_engine import optimize_resume, load_prompts
from components.ui_elements import get_glass_overlay_html

def render_tab():
    st.header("🤖 Auto-Optimize Resume based on JD")
    col1, col2 = st.columns(2)
    enable_ats = col1.checkbox("Enable ATS Keyword Analysis", value=True, key="opt_enable_ats")
    check_visa = col2.checkbox("Check Visa/Sponsorship Restrictions", value=True, key="opt_check_visa")
    
    jd_input = st.text_area("📄 Paste the Target Job Description (JD)", height=250, key="opt_jd_input")
    
    # 修正 Key，確保與 Session State 統一
    custom_prompt = st.text_area(
        "🗣️ Custom Prompt (Optional)", 
        value=st.session_state.get("custom_prompt", ""), 
        key="custom_prompt" 
    )
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        run_ai = st.button("🚀 Start AI Optimization", type="primary", use_container_width=True)
    
    with col_btn2:
        # --- 補回你原本漂亮的 Copy Prompt 按鈕 ---
        if jd_input:
            prompts = load_prompts()
            opt_cfg = prompts['optimization']
            visa_instr = opt_cfg['visa_check_step'] if check_visa else "- Step 1: Disabled."
            ats_example = '"keyword_analysis": {...},' if enable_ats else ""
            
            full_prompt = opt_cfg['optimization_rules'].format(
                custom_prompt=custom_prompt,
                visa_check_instruction=visa_instr,
                jd_text=jd_input,
                resume_json=json.dumps(st.session_state.resume_data, ensure_ascii=False),
                ats_example=ats_example
            )
            
            b64_text = base64.b64encode(full_prompt.encode('utf-8')).decode('utf-8')
            html_code = f"""
            <button id="copyBtn" style="width:100%; height:40px; border-radius:8px; cursor:pointer; background-color:transparent; border:1px solid #444; color:white;">
                📋 Copy Prompt for Other AIs
            </button>
            <script>
            document.getElementById('copyBtn').onclick = function() {{
                const text = decodeURIComponent(escape(window.atob('{b64_text}')));
                navigator.clipboard.writeText(text).then(() => {{
                    this.innerText = '✅ Copied!';
                    this.style.color = '#00cc66';
                    setTimeout(() => {{ this.innerText = '📋 Copy Prompt for Other AIs'; this.style.color = 'white'; }}, 2000);
                }});
            }}
            </script>
            """
            components.html(html_code, height=45)
        else:
            st.button("📋 Copy Prompt for Other AIs", disabled=True, use_container_width=True)
    
    if run_ai:
        if not jd_input:
            st.warning("Please paste the JD content first!")
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
                    st.success("Optimization completed!")
            else:
                st.error(result)
