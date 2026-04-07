import streamlit as st
import google.generativeai as genai
import jinja2
import subprocess
import os
import json
import tempfile
import shutil
import base64
import streamlit.components.v1 as components
import streamlit_ace as st_ace # 引入 streamlit-ace 套件
from datetime import datetime
from firebase_dashboard import init_firebase, authenticate_user, register_user, render_dashboard, save_application, render_interview_progress, save_user_profile, load_user_profile

# ---------------------------------------------------------
# 初始化 Session State (JSON 資料結構)
# ---------------------------------------------------------
if "resume_data" not in st.session_state:
    st.session_state.resume_data = {
        "heading": {
            "name": "John Doe",
            "email": "johndoe@example.com",
            "phone": "+1-234-567-8900",
            "website": "github.com/johndoe",
            "linkedin": "linkedin.com/in/johndoe"
        },
        "cover_letter":"I am writing to express my strong interest in the AI Engineer position at Google. I can rapidly master the intricacies of semiconductor equipment, contributing significantly to your team’s success.",
        "target_company":"Google",
        "target_role":"AI Engineer",
        "about me more": "I have independently handled end-to-end development, from low-level model optimization and backend microservice architecture to frontend user interfaces...",
        "summary": "Software Engineer with 3 years of experience specializing in scalable backend architectures and AI-driven systems...",
        "education": [
            {
                "degree": "Master of Science in Computer Science",
                "time_period": "Aug 2021 - May 2023",
                "school": "State University",
                "school_location": "New York, NY"
            }
        ],
        "experience": [
            {
                "role": "Software Engineer",
                "team": "Backend Core Team",
                "company": "Tech Corp",
                "company_location": "San Francisco, CA",
                "time_duration": "Jun 2023 - Present",
                "details": [
                    {
                        "title": "Microservices Architecture",
                        "description": "Architected a high-performance backend using Python and FastAPI to orchestrate automated workflows, improving efficiency by 40%."
                    }
                ]
            }
        ],
        "projects": [
            {
                "name": "E-Commerce Platform",
                "time": "Jan 2023 - May 2023",
                "description": "Led a team of 4 to develop a full-stack e-commerce web application using React and Django."
            }
        ],
        "patents": [],
        "skills": {
            "set1": {
                "title": "Backend & Architecture",
                "items": ["Python (FastAPI, Django)", "RESTful API Design", "Docker", "AWS"]
            }
        }
    }

if "ai_report" not in st.session_state:
    st.session_state.ai_report = ""

if "optimized_resume_data" not in st.session_state:
    st.session_state.optimized_resume_data = None

if "base_resume_saved_time" not in st.session_state:
    st.session_state.base_resume_saved_time = None
if "optimized_resume_saved_time" not in st.session_state:
    st.session_state.optimized_resume_saved_time = None
if "base_editor_key" not in st.session_state:
    st.session_state.base_editor_key = 0
if "opt_editor_key" not in st.session_state:
    st.session_state.opt_editor_key = 0
if "ats_metrics" not in st.session_state:
    st.session_state.ats_metrics = None
if "changelog" not in st.session_state:
    st.session_state.changelog = ""
if "custom_prompt" not in st.session_state:
    st.session_state.custom_prompt = "Make the experiences sound more aggressive and impactful. Focus on system optimization and microservices keywords."
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""
if "preview_pdf_bytes" not in st.session_state:
    st.session_state.preview_pdf_bytes = None
if "resume_preview_bytes" not in st.session_state:
    st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state:
    st.session_state.cover_letter_preview_bytes = None
if "cover_letter_filename" not in st.session_state:
    st.session_state.cover_letter_filename = "cover_letter.pdf"
if 'resume_dl_data' not in st.session_state:
    st.session_state.resume_dl_data = None
if 'cl_dl_data' not in st.session_state:
    st.session_state.cl_dl_data = None

# ---------------------------------------------------------
# AI 核心邏輯 (ATS 關鍵字分析與履歷優化)
# ---------------------------------------------------------
def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            return False, "⚠️ Error: Please set your GEMINI API KEY in the sidebar first."
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        report_md = ""

        # 🛑 Phase 1: Visa Sponsorship Check
        if check_visa:
            visa_prompt = f"""
            Strictly review the following Job Description (JD). Check for either of these conditions:
            1. Explicitly requires "U.S. Citizen" or "Green Card / Permanent Resident".
            2. Explicitly states "No visa sponsorship" or "Unable to sponsor".
            Return ONLY valid JSON: {{"blocked": true/false, "reason": "..."}}
            [JD]: {jd_text}
            """
            visa_res = model.generate_content(visa_prompt)
            visa_json = json.loads(visa_res.text.replace('```json', '').replace('```', '').strip())
            
            if visa_json.get("blocked"):
                report_md += f"### ⛔ Visa Sponsorship Check Failed\n**Reason:** {visa_json.get('reason')}\n\n💡 Suggestion: Due to visa restrictions, AI has stopped the optimization. Save your time for the next company!"
                return False, report_md
            else:
                report_md += "✅ **Visa check passed! No explicit sponsorship barriers found.**\n\n---\n"

        # 🚀 Phase 2: ATS Keyword & Resume Optimization
        ats_instruction = ""
        ats_example = ""
        if enable_ats:
            ats_instruction = """
            - "keyword_analysis": Contains "jd_keywords", "original_hits", "optimized_hits", "newly_added", "missing_keywords" (all array of strings)."""
            ats_example = """
            "keyword_analysis": {"jd_keywords": ["AWS", "Python"], "original_hits": ["Python"], "optimized_hits": ["Python", "AWS"], "newly_added": ["AWS"], "missing_keywords": []},"""

        final_prompt = f"""
        {custom_prompt}

        [Target JD]: {jd_text}
        [Original Resume JSON]: {json.dumps(st.session_state.resume_data, ensure_ascii=False)}

        🔥 STRICT RULES - MUST FOLLOW OR FAIL:
        1. Cover Letter:
            - Write a complete cover letter based on the JD and place it in the "cover_letter" field.
            - ALWAYS end with "Best regards," followed by a newline and the applicant's first name.
        2. Extraction: Extract the target company and role from the JD and put them into "target_company" and "target_role" fields.

        🔥 [Advanced ATS Keyword Injection Rules]:
        1. Horizontal Shift: If JD requires GCP and the candidate has AWS, rewrite as "AWS/GCP" in skills or summary. Do not hallucinate unrelated skills.
        2. Concept Replacement: Cleverly replace synonyms in experience descriptions to hit ATS keywords.
        3. ⚠️ Consistency Rule: Keywords in `newly_added` MUST strictly appear in `optimized_resume`.

        ⚠️ [Output Format Limitation]: Return ONLY valid JSON, no markdown ticks like ```json.
        {{
            "changelog": "Brief explanation of modifications...",{ats_example}
            "optimized_resume": {{...Updated full resume JSON structure...}}
        }}
        """
        
        response = model.generate_content(final_prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        
        try:
            ai_result = json.loads(raw_text)
        except json.JSONDecodeError as json_err:
            return False, f"⚠️ AI output malformed JSON. Please try again!\n\n**System Error:** {json_err}\n\n**Raw Output Fragment:**\n```json\n{raw_text[:800]}\n```"

        modified_resume_data = ai_result.get("optimized_resume", {})
        if not modified_resume_data:
            return False, "⚠️ Parsing Error: Could not find the optimized resume data."
            
        st.session_state.optimized_resume_data = modified_resume_data

        st.session_state.opt_editor_key += 1
        st.session_state.optimized_resume_saved_time = None
        
        st.session_state.ats_metrics = None
        st.session_state.changelog = ai_result.get('changelog', '')

        # 生成 Markdown 報告
        if enable_ats and "keyword_analysis" in ai_result:
            kw = ai_result["keyword_analysis"]
            tot = len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", []))
            orig_c = len(kw.get("original_hits", []))
            opt_c = len(kw.get("optimized_hits", []))
            orig_pct = int((orig_c / tot) * 100) if tot > 0 else 0
            opt_pct = int((opt_c / tot) * 100) if tot > 0 else 0
            
            st.session_state.ats_metrics = {
                "total": tot,
                "original_count": orig_c,
                "optimized_count": opt_c,
                "original_pct": orig_pct,
                "optimized_pct": opt_pct,
                "optimized_hits": kw.get("optimized_hits", []),
                "newly_added": kw.get("newly_added", []),
                "missing_keywords": kw.get("missing_keywords", [])
            }
        
        return True, report_md
    except Exception as e:
        return False, f"⚠️ AI execution error: {e}"

# ---------------------------------------------------------
# PDF 生成與預覽邏輯 (全部使用獨立的暫存目錄避免名稱衝突)
# ---------------------------------------------------------
def generate_preview_pdf_bytes(data, template_name="main.tex", custom_tex_bytes=None):
    try:
        data_str = json.dumps(data, ensure_ascii=False)
        data_str = data_str.replace('**', '')
        clean_data = json.loads(data_str)

        with tempfile.TemporaryDirectory() as temp_dir:
            if custom_tex_bytes:
                template_name = "custom_main.tex"
                with open(os.path.join(temp_dir, template_name), "wb") as f:
                    f.write(custom_tex_bytes)
            else:
                shutil.copy(template_name, temp_dir)
            
            temp_json_path = os.path.join(temp_dir, "ml_resume.json")
            with open(temp_json_path, "w", encoding="utf-8") as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=4)
                
            process = subprocess.run(
                ['lualatex', '-interaction=nonstopmode', template_name],
                cwd=temp_dir,
                capture_output=True
            )
            
            pdf_path = os.path.join(temp_dir, template_name.replace('.tex', '.pdf'))
            if process.returncode == 0 and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    return f.read(), None
            else:
                return None, process.stdout.decode('utf-8', errors='ignore')
    except Exception as e:
        return None, str(e)

def generate_cover_letter_pdf_bytes(resume_data):
    try:
        company = resume_data.get('target_company', 'Company').replace(' ', '_').replace('/', '_')
        role = resume_data.get('target_role', 'Role').replace(' ', '_').replace('/', '_')
        pdf_filename = f"{company}_{role}_coverletter.pdf"

        cl_content = resume_data.get('cover_letter', '')
        if not cl_content:
            return None, None, "No cover letter content found."
            
        clean_cl_content = cl_content.replace('**', '')

        def escape_tex(text):
            text = text.replace('\\', '\\textbackslash{}')
            chars_to_escape = ['&', '%', '$', '#', '_', '{', '}']
            for c in chars_to_escape:
                text = text.replace(c, '\\' + c)
            text = text.replace('~', '\\textasciitilde{}')
            text = text.replace('^', '\\textasciicircum{}')
            return text
            
        escaped_content = escape_tex(clean_cl_content)

        latex_template = r"""
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{fontspec}
\usepackage{setspace}
\usepackage{parskip}
\onehalfspacing
\begin{document}
""" + escaped_content.replace("\n", "\n\n") + r"""
\end{document}
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_filename = "cover_letter.tex"
            tex_path = os.path.join(temp_dir, tex_filename)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_template)

            process = subprocess.run(
                ['lualatex', '-interaction=nonstopmode', tex_filename],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            gen_pdf_path = os.path.join(temp_dir, tex_filename.replace('.tex', '.pdf'))
            if process.returncode == 0 and os.path.exists(gen_pdf_path):
                with open(gen_pdf_path, "rb") as f:
                    return f.read(), pdf_filename, None
            else:
                return None, None, process.stdout + "\n" + process.stderr
    except Exception as e:
        return None, None, str(e)

def render_pdf_js(pdf_bytes, height=650):
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
        <style>
            body {{ margin: 0; padding: 0; background-color: transparent; display: flex; flex-direction: column; align-items: center; }}
            canvas {{ margin-bottom: 10px; box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.15); width: 100%; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <div id="pdf-container" style="width: 100%;"></div>
        <script>
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            
            var binaryString = window.atob('{base64_pdf}');
            var binaryLen = binaryString.length;
            var bytes = new Uint8Array(binaryLen);
            for (var i = 0; i < binaryLen; i++) {{
                bytes[i] = binaryString.charCodeAt(i);
            }}
            
            var loadingTask = pdfjsLib.getDocument({{data: bytes}});
            loadingTask.promise.then(function(pdf) {{
                var container = document.getElementById('pdf-container');
                for (var pageNum = 1; pageNum <= pdf.numPages; pageNum++) {{
                    pdf.getPage(pageNum).then(function(page) {{
                        var scale = 1.5;
                        var viewport = page.getViewport({{scale: scale}});
                        var canvas = document.createElement('canvas');
                        var context = canvas.getContext('2d');
                        canvas.height = viewport.height;
                        canvas.width = viewport.width;
                        container.appendChild(canvas);
                        var renderContext = {{ canvasContext: context, viewport: viewport }};
                        page.render(renderContext);
                    }});
                }}
            }});
        </script>
    </body>
    </html>
    """
    components.html(pdf_js_html, height=height, scrolling=True)

# ---------------------------------------------------------
# Custom Premium UI Components (Glassmorphism & Overlays)
# ---------------------------------------------------------
def get_glass_overlay_html(message="AI is processing your request...", animal_emoji="🐕", theme_color="#8a2be2"):
    return f"""<style>
.glass-overlay-bg {{
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(10, 10, 15, 0.7);
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    z-index: 999999; display: flex; justify-content: center; align-items: center;
}}
.glass-dialog-box {{
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.01));
    border: 1px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    border-radius: 24px; padding: 50px 60px;
    text-align: center; position: relative; overflow: hidden;
    display: flex; flex-direction: column; align-items: center;
}}
.glass-dialog-box::before {{
    content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%;
    background: radial-gradient(circle, {theme_color}26 0%, transparent 60%);
    animation: pulse-glow 3s infinite alternate; z-index: 0;
}}
.float-container {{
    animation: floatAnim 2.5s ease-in-out infinite;
    margin-bottom: 10px; z-index: 2; position: relative;
}}
.interactive-animal {{
    font-size: 85px; user-select: none; display: inline-block;
    transition: transform 0.7s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}}
.interactive-animal:hover {{
    filter: drop-shadow(0 0 15px {theme_color});
}}
@keyframes floatAnim {{ 0%, 100% {{ transform: translateY(0px); }} 50% {{ transform: translateY(-15px); }} }}
.loading-text {{
    color: #ffffff; font-family: 'Segoe UI', sans-serif; font-size: 1.2rem;
    font-weight: 300; letter-spacing: 1px; margin: 0;
    text-shadow: 0 2px 10px rgba(0,0,0,0.5); z-index: 1; position: relative;
}}
@keyframes pulse-glow {{ 0% {{ opacity: 0.5; }} 100% {{ opacity: 1; }} }}
</style>
<div class="glass-overlay-bg">
    <div class="glass-dialog-box">
        <div class="float-container">
            <div class="interactive-animal" id="autoAnimAnimal">{animal_emoji}</div>
        </div>
        <h2 class="loading-text">{message}</h2>
    </div>
</div>
<img src="x" style="display:none;" onerror="
    var animal = document.getElementById('autoAnimAnimal');
    var currentRot = 0;
    function triggerRandomAnim() {{
        if(!animal || !document.body.contains(animal)) return;
        
        var addRot = (Math.floor(Math.random() * 3) + 1) * 360 * (Math.random() > 0.5 ? 1 : -1);
        currentRot += addRot;
        var scale = Math.random() * 0.5 + 0.8;
        
        animal.style.transform = 'rotate(' + newRot + 'deg) scale(' + scale + ')';
        setTimeout(function(){{
            if(document.body.contains(animal))
                animal.style.transform = 'rotate(' + currentRot + 'deg) scale(1)';
        }}, 350);
        
        var nextTime = Math.random() * 1200 + 600;
        setTimeout(triggerRandomAnim, nextTime);
    }}
    if(animal) setTimeout(triggerRandomAnim, 500);
">"""

# ---------------------------------------------------------
# Streamlit UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume Builder", page_icon="🚀", layout="wide")

db = init_firebase()

# --- Sidebar Settings ---
with st.sidebar:
    st.header("👤 Account")
    if st.session_state.logged_in:
        st.success(f"Logged in as: {st.session_state.user_email}")

        if st.button("☁️ Sync Base Profile to Cloud"):
            if db:
                current_prompt = st.session_state.get("custom_prompt_input", st.session_state.get("custom_prompt", ""))
                current_api_key = st.session_state.get("api_key", "")
                success, msg = save_user_profile(db, st.session_state.user_email, st.session_state.resume_data, current_prompt, current_api_key)
                if success:
                    st.toast(msg)
                else:
                    st.error(msg)
                    
        if st.button("⬇️ Pull Data from Cloud"):
            if db:
                loaded_resume, loaded_prompt, loaded_key = load_user_profile(db, st.session_state.user_email)
                if loaded_resume:
                    st.session_state.resume_data = loaded_resume
                    st.session_state.base_editor_key += 1
                    st.toast("✅ Base resume loaded from cloud.")
                if loaded_prompt:
                    st.session_state.custom_prompt = loaded_prompt
                    st.session_state.custom_prompt_input = loaded_prompt
                    st.toast("✅ Custom prompt loaded from cloud.")
                if loaded_key:
                    st.session_state.api_key = loaded_key
                    st.toast("✅ API Key loaded from cloud.")
                st.rerun()

        if st.button("🚪 Logout"):
            st.session_state.logged_in = False
            st.session_state.user_email = ""
            st.rerun()
    else:
        st.info("Log in to sync and track your job applications.")
        with st.form("login_form"):
            login_email = st.text_input("Email", key="sidebar_login_email").strip()
            login_pwd = st.text_input("Password", type="password", key="sidebar_login_pwd")
            login_submitted = st.form_submit_button("Login")
            if login_submitted:
                if db is None:
                    st.error("Firebase connection failed.")
                else:
                    success, msg = authenticate_user(db, login_email, login_pwd)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.user_email = login_email
                        
                        loaded_resume, loaded_prompt, loaded_key = load_user_profile(db, login_email)
                        if loaded_resume:
                            st.session_state.resume_data = loaded_resume
                            st.session_state.base_editor_key += 1
                            st.toast("✅ Base resume loaded from cloud.")
                        if loaded_prompt:
                            st.session_state.custom_prompt = loaded_prompt
                            st.session_state.custom_prompt_input = loaded_prompt
                            st.toast("✅ Custom prompt loaded from cloud.")
                        if loaded_key:
                            st.session_state.api_key = loaded_key
                            st.toast("✅ API Key loaded from cloud.")
                        st.rerun()
                    else:
                        st.error(msg)

        with st.expander("📝 Don't have an account? Register here"):
            with st.form("register_form"):
                reg_email = st.text_input("Email", key="sidebar_reg_email").strip()
                reg_pwd = st.text_input("Password", type="password", key="sidebar_reg_pwd")
                reg_pwd_confirm = st.text_input("Confirm Password", type="password", key="sidebar_reg_pwd_confirm")
                reg_submitted = st.form_submit_button("Register")
                if reg_submitted:
                    if reg_pwd != reg_pwd_confirm:
                        st.error("Passwords do not match!")
                    elif len(reg_pwd) < 6:
                        st.error("Password must be at least 6 characters long.")
                    else:
                        success, msg = register_user(db, reg_email, reg_pwd)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)

    st.markdown("---")
    st.header("⚙️ Settings")
    st.text_input("🔑 Google Gemini API Key", type="password", key="api_key", help="API Key is required to use AI features.")
    st.markdown("---")
    
    st.header("🏃 Loading Animation")
    animal_choice = st.selectbox(
        "Choose your runner",
        ["🦦 Otter", "🦫 Beaver", "🥟🥟 Dumplings", "🏂 Henry", "🐕 Dog", "🐅 Tiger", "🦖 T-Rex", "🐎 Horse", "🐢 Turtle", "🏃 Human"],
        index=0
    )
    st.session_state.animal_emoji = animal_choice.split(" ")[0]
    
    theme_color_choice = st.color_picker("Choose theme color", "#8a2be2")
    st.session_state.theme_color = theme_color_choice
    
    st.markdown("---")
    st.markdown("👉 [Get Gemini API Key for free](https://aistudio.google.com/app/apikey)")
    st.markdown("👨‍💻 **Developed by [NSYSUHermit](https://github.com/NSYSUHermit)**")

st.title("🚀 AI-Powered Resume Builder")
st.write("Combine Gemini AI with LaTeX to write, optimize, and export high-quality PDF resumes and cover letters effortlessly.")

st.markdown("---")
st.subheader("📝 Current Data Status")

@st.dialog("Base Profile Content", width="large")
def preview_base_profile():
    st.json(st.session_state.resume_data)

@st.dialog("Optimized Profile Content", width="large")
def preview_optimized_profile():
    st.json(st.session_state.optimized_resume_data)

col1, col2 = st.columns(2)

with col1:
    if st.button("👁️ Preview Base Profile", use_container_width=True):
        preview_base_profile()
    if st.session_state.get("base_resume_saved_time"):
        st.caption(f"💾 Base Saved: {st.session_state.base_resume_saved_time}")

with col2:
    if st.session_state.optimized_resume_data:
        if st.button("👁️ Preview Optimized Profile", use_container_width=True):
            preview_optimized_profile()
        if st.session_state.get("optimized_resume_saved_time"):
            st.caption(f"💾 Optimized Saved: {st.session_state.optimized_resume_saved_time}")
    else:
        st.button("👁️ Preview Optimized Profile", disabled=True, use_container_width=True)
        st.caption("🚫 Not generated yet")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5 = st.tabs([" Base Profile ", " AI Optimizer ", " ATS Analysis ", " Editor & Export ", " Job Tracker "])

# --- 1. Base Profile Tab ---
with tab1:
    st.header("👤 Edit Your Base Profile")
    st.info("This is your **Base Template**. AI will always use this as the ground truth for optimizations. Remember to click 'Save Changes' below.")
    
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
        auto_update=True,
    )
    
    if st.button("💾 Save JSON Changes", type="primary"):
        try:
            st.session_state.resume_data = json.loads(edited_json)
            st.session_state.base_resume_saved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.success("JSON data saved successfully!")
        except Exception as e:
            st.error(f"JSON format error, please check syntax: {e}")

# --- 2. AI Customization Tab ---
with tab2:
    st.header("🤖 Auto-Optimize Resume based on JD")
    col1, col2 = st.columns(2)
    enable_ats = col1.checkbox("Enable ATS Keyword Analysis", value=True)
    check_visa = col2.checkbox("Check Visa/Sponsorship Restrictions", value=True)
    
    jd_input = st.text_area("📄 Paste the Target Job Description (JD)", height=250, key="jd_input_for_cl")
    custom_prompt = st.text_area(
        "🗣️ Custom Prompt (Optional)", 
        value=st.session_state.get("custom_prompt", "Make the experiences sound more aggressive and impactful. Focus on system optimization and microservices keywords."),
        key="custom_prompt_input"
    )
    
    if st.button("🚀 Start AI Optimization & Analysis", type="primary"):
        if not jd_input:
            st.warning("Please paste the JD content first!")
        else:
            loading_overlay = st.empty()
            loading_overlay.markdown(get_glass_overlay_html("AI is crafting your resume...<br>Please wait.", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)
            
            success, report = ai_optimize_and_update(jd_input, custom_prompt, enable_ats, check_visa)
            st.session_state.ai_report = report
            
            loading_overlay.empty()
            
            if success:
                st.success("Optimization completed! Check the '3️⃣ Dashboard' or edit in '4️⃣ Editor'.")
            else:
                st.error("Optimization interrupted or failed. Check the details below:")
                st.warning(st.session_state.ai_report)

# --- 3. Dashboard Tab ---
with tab3:
    st.header("📊 ATS Analysis Report")
        
    if st.session_state.ai_report:
        st.info(st.session_state.ai_report)
        
    if st.session_state.ats_metrics:
        m = st.session_state.ats_metrics
        
        col1, col2, col3 = st.columns(3)
        delta_pct = m['optimized_pct'] - m['original_pct']
        
        col1.metric("Original Match", f"{m['original_pct']}%", f"{m['original_count']} / {m['total']} keywords", delta_color="off")
        col2.metric("Optimized Match", f"{m['optimized_pct']}%", f"+{delta_pct}% Improvement")
        col3.metric("Keywords Injected", f"{len(m['newly_added'])}", "AI newly added")
        
        st.write("##### Match Progress")
        st.progress(min(m['optimized_pct'] / 100.0, 1.0))
        st.markdown("---")
        
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            st.success("✅ **Successfully Hit Keywords**")
            for k in m['optimized_hits']:
                if k in m['newly_added']:
                    st.markdown(f"- `{k}` 🌟 *(Forced injection)*")
                else:
                    st.markdown(f"- `{k}`")
            if not m['optimized_hits']:
                st.write("- None")
                
        with col_k2:
            st.error("❌ **Missing Keywords**")
            for k in m['missing_keywords']:
                st.markdown(f"- `{k}`")
            if not m['missing_keywords']:
                st.write("- None")
                
        st.markdown("---")
        
    if st.session_state.changelog:
        st.write("### 📝 Changelog")
        st.info(st.session_state.changelog)
        
    if not st.session_state.ats_metrics and not st.session_state.changelog and not st.session_state.ai_report:
        st.write("No AI optimization executed yet. Please paste a JD in '2️⃣ AI Optimize' and run it.")

# --- 4. Editor & Export Tab ---
with tab4:
    st.header("📝 Editor & Export")

    if st.session_state.optimized_resume_data:
        # Main layout: Editor on the left, Preview/Export on the right
        col_edit, col_export = st.columns([6, 4])
        data_to_use = st.session_state.optimized_resume_data

        with col_edit:
            st.subheader("JSON Editor")
            st.info("Make final tweaks to the AI-generated JSON here. Click 'Save & Refresh' to update the previews on the right.")
            editor_value = json.dumps(data_to_use, indent=4, ensure_ascii=False)
            edited_opt_json = st_ace.st_ace(
                value=editor_value,
                language="json",
                theme="dracula",
                height=800,
                key=f"optimized_resume_editor_{st.session_state.opt_editor_key}",
                font_size=14, tab_size=2, show_gutter=True, auto_update=True,
            )

        with col_export:
            st.subheader("📄 Live Preview")

            if st.button("💾 Save JSON & Refresh Previews", type="primary", use_container_width=True):
                try:
                    st.session_state.optimized_resume_data = json.loads(edited_opt_json)
                    st.session_state.optimized_resume_saved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.toast("✅ JSON saved!")

                    loading_overlay = st.empty()
                    loading_overlay.markdown(get_glass_overlay_html("Generating Previews...<br>Please wait.", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)

                    resume_bytes, r_err = generate_preview_pdf_bytes(st.session_state.optimized_resume_data, "main.tex")
                    if resume_bytes: st.session_state.resume_preview_bytes = resume_bytes
                    
                    cl_bytes, cl_name, cl_err = generate_cover_letter_pdf_bytes(st.session_state.optimized_resume_data)
                    if cl_bytes:
                        st.session_state.cover_letter_preview_bytes = cl_bytes
                        st.session_state.cover_letter_filename = cl_name

                    loading_overlay.empty()
                    st.toast("✅ Previews refreshed!")
                except Exception as e:
                    st.error(f"JSON format error, please check syntax: {e}")

            preview_choice = st.radio("Preview Target:", ["Resume", "Cover Letter"], horizontal=True, key="preview_choice")
            if preview_choice == "Resume":
                if st.session_state.resume_preview_bytes: render_pdf_js(st.session_state.resume_preview_bytes, height=400)
                else: st.info("Click 'Save & Refresh Previews' to generate resume preview.")
            else:
                if st.session_state.cover_letter_preview_bytes: render_pdf_js(st.session_state.cover_letter_preview_bytes, height=400)
                else: st.info("Click 'Save & Refresh Previews' to generate cover letter preview.")

            st.divider()
            st.subheader("🖨️ Download Documents")

            with st.container(border=True):
                st.write("**Resume**")
                template_choice = st.radio("Template", ["💻 Tech", "📈 Consulting"], horizontal=True, key="dl_template")
                selected_template = "main.tex" if template_choice.startswith("💻") else "elsa_main.tex"
                
                if st.session_state.logged_in:
                    sync_to_firebase = st.checkbox("🔄 Sync application to Job Tracker", value=True)
                else:
                    sync_to_firebase = False

                if st.button("Generate Resume PDF", use_container_width=True, key="gen_resume_dl"):
                    loading_overlay = st.empty()
                    loading_overlay.markdown(get_glass_overlay_html("Compiling Resume...", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)
                    pdf_bytes, err = generate_preview_pdf_bytes(data_to_use, selected_template)
                    loading_overlay.empty()

                    if pdf_bytes:
                        st.toast("✅ Resume ready for download!")
                        if sync_to_firebase and st.session_state.logged_in and db:
                            company = data_to_use.get('target_company', 'Unknown')
                            if save_application(db, st.session_state.user_email, company, data_to_use):
                                st.toast(f"✅ Synced application for {company}!")
                        
                        company_name = data_to_use.get('target_company', 'Resume').replace(' ', '_')
                        role_name = data_to_use.get('target_role', 'Role').replace(' ', '_')
                        st.session_state.resume_dl_data = {"bytes": pdf_bytes, "name": f"{company_name}_{role_name}_Resume.pdf"}
                    else:
                        st.error("Resume generation failed."); st.session_state.resume_dl_data = None

                if st.session_state.resume_dl_data:
                    st.download_button("📥 Download Resume", st.session_state.resume_dl_data["bytes"], st.session_state.resume_dl_data["name"], "application/pdf", use_container_width=True)

            with st.container(border=True):
                st.write("**Cover Letter**")
                if st.button("Generate Cover Letter PDF", use_container_width=True, key="gen_cl_dl"):
                    if 'cover_letter' not in data_to_use or not data_to_use['cover_letter']:
                        st.warning("No 'cover_letter' content found in JSON."); st.session_state.cl_dl_data = None
                    else:
                        loading_overlay = st.empty()
                        loading_overlay.markdown(get_glass_overlay_html("Compiling Cover Letter...", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)
                        pdf_bytes, pdf_name, err = generate_cover_letter_pdf_bytes(data_to_use)
                        loading_overlay.empty()

                        if pdf_bytes:
                            st.toast("✅ Cover Letter ready for download!")
                            st.session_state.cl_dl_data = {"bytes": pdf_bytes, "name": pdf_name}
                        else:
                            st.error(f"Cover Letter generation failed: {err}"); st.session_state.cl_dl_data = None

                if st.session_state.cl_dl_data:
                    st.download_button("📥 Download Cover Letter", st.session_state.cl_dl_data["bytes"], st.session_state.cl_dl_data["name"], "application/pdf", use_container_width=True)
    else:
        st.warning("No optimized data generated yet. Please run the AI in '2️⃣ AI Optimizer' first.")

# --- 5. Job Tracker Tab ---
with tab5:
    st.header("📈 Job Application Tracker")
    if not st.session_state.logged_in:
        st.warning("🔒 Please log in to view your interview progress and conversion rates.")
    elif db:
        render_interview_progress(db, st.session_state.user_email)
        st.markdown("---")
        render_dashboard(db, st.session_state.user_email)
    else:
        st.error("❌ Cannot connect to Firebase database.")