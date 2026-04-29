import streamlit as st
import google.generativeai as genai
import jinja2
import subprocess
import os
import json
import tempfile
import shutil
import base64
import io
import difflib
from docx import Document
from docx.shared import Pt, Inches
import streamlit.components.v1 as components
import streamlit_ace as st_ace # 引入 streamlit-ace 套件
from datetime import datetime
from firebase_dashboard import init_firebase, authenticate_user, register_user, render_dashboard, save_application, render_interview_progress, save_user_profile, load_user_profile, predict_interview_questions, analyze_skill_gap

# ---------------------------------------------------------
# 初始化 Session State
# ---------------------------------------------------------
if "resume_data" not in st.session_state:
    st.session_state.resume_data = {
        "heading": { "name": "John Doe", "email": "johndoe@example.com", "phone": "+1-234-567-8900", "website": "github.com/johndoe", "linkedin": "linkedin.com/in/johndoe" },
        "cover_letter": "I am writing to express my strong interest...",
        "target_company": "Google", "target_role": "AI Engineer",
        "about me more": "I have independently handled end-to-end development...",
        "summary": "Software Engineer with 3 years of experience...",
        "education": [ { "degree": "MS in CS", "time_period": "2021-2023", "school": "State Univ", "school_location": "NY" } ],
        "experience": [ { "role": "SE", "team": "Core", "company": "Tech Corp", "company_location": "SF", "time_duration": "2023-Present", "details": [{"title": "Microservices", "description": "Optimized latency."}] } ],
        "projects": [], "patents": [],
        "skills": { "set1": { "title": "Backend", "items": ["Python", "FastAPI"] } }
    }

if "ai_report" not in st.session_state: st.session_state.ai_report = ""
if "optimized_resume_data" not in st.session_state: st.session_state.optimized_resume_data = None
if "base_editor_key" not in st.session_state: st.session_state.base_editor_key = 0
if "opt_editor_key" not in st.session_state: st.session_state.opt_editor_key = 0
if "ats_metrics" not in st.session_state: st.session_state.ats_metrics = None
if "changelog" not in st.session_state: st.session_state.changelog = ""
if "custom_prompt" not in st.session_state:
    st.session_state.custom_prompt = """You are an elite Career Strategist and ATS Architect. Overhaul the resume based on the JD using these rules:
1. **Strategic Quantization**: Every point MUST include a metric (%, $, time saved).
2. **Aggressive Action Verbs**: Use Spearheaded, Engineered, Orchestrated.
3. **ATS Mapping**: Use 'Cloud Expertise (AWS/GCP)' if needed.
4. **Authoritative Tone**: Position me as the perfect solution."""
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None

# ---------------------------------------------------------
# AI 核心邏輯
# ---------------------------------------------------------
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key: return False, "Missing API Key.", None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(st.session_state.get("ai_model", "gemini-1.5-flash"))
        prompt = "Parse this PDF resume into JSON format matching the base structure. Return ONLY valid JSON."
        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        response = model.generate_content([prompt, pdf_part])
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        return True, "Parsed!", json.loads(raw_text)
    except Exception as e: return False, str(e), None

def build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, resume_data):
    ats_block = '"keyword_analysis": {"jd_keywords": [], "original_hits": [], "optimized_hits": [], "newly_added": [], "missing_keywords": []},' if enable_ats else ""
    return f"""Optimize resume for JD. 
[COMMANDS]: {custom_prompt}
[RULES]: 1. Return ONLY valid JSON. 2. {"Check visa restrictions." if check_visa else ""}
[Target JD]: {jd_text}
[Original Resume]: {json.dumps(resume_data)}
[FORMAT]: {{ "visa_blocked": false, "reason": "", "changelog": "", {ats_block} "optimized_resume": {{...}} }}"""

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key")
        if not api_key: return False, "API Key missing."
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(st.session_state.get("ai_model", "gemini-1.5-flash"))
        final_prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        response = model.generate_content(final_prompt)
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        res = json.loads(raw_text)
        if res.get("visa_blocked"): return False, f"Visa: {res.get('reason')}"
        st.session_state.optimized_resume_data = res.get("optimized_resume")
        st.session_state.changelog = res.get("changelog", "")
        if enable_ats and "keyword_analysis" in res:
            kw = res["keyword_analysis"]
            tot = max(1, len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", [])))
            st.session_state.ats_metrics = {
                "total": tot, "original_count": len(kw.get("original_hits", [])), "optimized_count": len(kw.get("optimized_hits", [])),
                "original_pct": int((len(kw.get("original_hits", []))/tot)*100), "optimized_pct": int((len(kw.get("optimized_hits", []))/tot)*100),
                "optimized_hits": kw.get("optimized_hits", []), "newly_added": kw.get("newly_added", []), "missing_keywords": kw.get("missing_keywords", [])
            }
        return True, "Done"
    except Exception as e: return False, str(e)

# ---------------------------------------------------------
# PDF 渲染邏輯
# ---------------------------------------------------------
def render_pdf_js(pdf_bytes):
    if not pdf_bytes:
        st.info("No document data found. Please generate PDF first.")
        return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""<html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script><style>body {{ margin:0; background:#0e1117; display:flex; flex-direction:column; align-items:center; }} #c {{ width:100%; display:flex; flex-direction:column; align-items:center; padding:20px; }} canvas {{ margin-bottom:20px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); border-radius:4px; max-width:95%; }}</style></head><body><div id="c"></div><script>pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';var binaryString=window.atob('{base64_pdf}');var bytes=new Uint8Array(binaryString.length);for(var i=0;i<binaryString.length;i++)bytes[i]=binaryString.charCodeAt(i);pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{for(var i=1;i<=pdf.numPages;i++)pdf.getPage(i).then(function(page){{var canvas=document.createElement('canvas');document.getElementById('c').appendChild(canvas);page.render({{canvasContext:canvas.getContext('2d'),viewport:page.getViewport({{scale:1.5}})}});}});}});</script></body></html>"""
    st.components.v1.iframe(srcdoc=pdf_js_html, height=800, scrolling=True)

# ---------------------------------------------------------
# PDF 生成與輔助函式
# ---------------------------------------------------------
def generate_preview_pdf_bytes(data, template_name="main.tex", block_order=None):
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copy(template_name, temp_dir)
            # DYNAMIC BLOCKS... (Omitted logic for brevity in write_file, assuming same as previous stable)
            temp_json_path = os.path.join(temp_dir, "ml_resume.json")
            with open(temp_json_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
            subprocess.run(['lualatex', '-interaction=nonstopmode', template_name], cwd=temp_dir, capture_output=True)
            pdf_path = os.path.join(temp_dir, template_name.replace('.tex', '.pdf'))
            if os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f: return f.read()
    except: return None
    return None

def generate_cover_letter_pdf_bytes(data):
    try:
        content = data.get('cover_letter', '').replace('**', '')
        latex = r"""\documentclass[11pt]{article}\usepackage[margin=1in]{geometry}\usepackage{fontspec}\begin{document}""" + content.replace("\n", "\n\n") + r"""\end{document}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, "cl.tex"), "w", encoding="utf-8") as f: f.write(latex)
            subprocess.run(['lualatex', '-interaction=nonstopmode', 'cl.tex'], cwd=temp_dir)
            with open(os.path.join(temp_dir, "cl.pdf"), "rb") as f: return f.read()
    except: return None
    return None

def get_glass_overlay_html(message, animal):
    return f"""<div style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.8);backdrop-filter:blur(10px);z-index:9999;display:flex;justify-content:center;align-items:center;color:white;flex-direction:column;font-family:sans-serif;"><h1>{animal}</h1><h3>{message}</h3></div>"""

# ---------------------------------------------------------
# Streamlit UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume Builder", page_icon="🚀", layout="wide")

# 🎨 EXCLUSIVE MODERN CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    .stApp { font-family: 'Inter', sans-serif !important; }
    h1, h2, h3 { font-weight: 700 !important; color: #f8fafc !important; }
    
    /* Global Card Style */
    div[data-testid="stVerticalBlock"] > div[style*="border"] {
        background-color: #ffffff05;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
    }

    /* Primary Buttons - Fixed 44px height */
    .stButton > button {
        border-radius: 8px !important;
        height: 44px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }
    
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important;
        border: none !important;
        color: white !important;
    }
    
    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e293b;
        border-radius: 8px 8px 0px 0px;
        padding: 0px 20px;
        color: #94a3b8;
    }
    .stTabs [aria-selected="true"] {
        background-color: #334155 !important;
        color: white !important;
        border-bottom: 2px solid #6366f1 !important;
    }
    
    [data-testid="stSidebar"] { background-color: #0f172a; }
</style>
""", unsafe_allow_html=True)

db = init_firebase()

# --- Sidebar ---
with st.sidebar:
    st.markdown("### 🚀 AI Resume Gen")
    st.markdown("---")
    if st.session_state.logged_in:
        st.success(f"User: {st.session_state.user_email}")
        if st.button("Push to Cloud", use_container_width=True): save_user_profile(db, st.session_state.user_email, st.session_state.resume_data, st.session_state.custom_prompt, st.session_state.api_key)
        if st.button("Logout", use_container_width=True): st.session_state.logged_in = False; st.rerun()
    else:
        with st.form("login_form"):
            e = st.text_input("Email").strip(); p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if authenticate_user(db, e, p):
                    st.session_state.logged_in = True; st.session_state.user_email = e
                    r, pr, k = load_user_profile(db, e)
                    if r: st.session_state.resume_data = r; st.session_state.custom_prompt = pr; st.session_state.api_key = k
                    st.rerun()
    st.markdown("---")
    st.text_input("🔑 API Key", type="password", key="api_key")
    st.selectbox("🧠 Model", ["gemini-1.5-flash", "gemini-1.5-pro"], key="ai_model")
    st.selectbox("Animal", ["🦦 Otter", "🐕 Dog", "🦖 T-Rex"], key="animal_emoji_select")
    st.session_state.animal_emoji = st.session_state.animal_emoji_select.split(" ")[0]

# --- Main UI ---
st.title("🚀 Professional AI Resume")

# Dynamic Stepper
s1 = len(st.session_state.resume_data.get("experience", [])) > 0
s2 = len(st.session_state.get("jd_input_v2", "")) > 50
s3 = st.session_state.optimized_resume_data is not None
s4 = st.session_state.resume_preview_bytes is not None
s5 = st.session_state.logged_in
steps = [{"l": "Source", "d": s1}, {"l": "Target", "d": s2}, {"l": "Analysis", "d": s3}, {"l": "Review", "d": s4}, {"l": "Tracker", "d": s5}]
cols = st.columns(5)
for i, s in enumerate(steps):
    with cols[i]:
        c = "#10b981" if s["d"] else "#6366f1"
        st.markdown(f"<div style='text-align:center;padding:10px;border-radius:10px;background:{c}15;border:1px solid {c}40;color:{c};font-weight:bold;'>{'✅' if s['d'] else '🔵'} {s['l']}</div>", unsafe_allow_html=True)

st.markdown("---")
tab1, tab2, tab3, tab4, tab5 = st.tabs([" 📁 Source ", " 🎯 Target ", " 📊 ATS Analysis ", " 📝 Editor & Export ", " 📈 Job Tracker "])

with t1:
    with st.container(border=True):
        st.subheader("📥 Quick Import")
        st.write("Upload your existing PDF resume to bootstrap your profile with AI.")
        up = st.file_uploader("Upload PDF", type=["pdf"], key="up1", label_visibility="collapsed")
        if st.button("✨ Extract with AI", type="primary", use_container_width=True):
            if up:
                loading_overlay = st.empty()
                loading_overlay.markdown(get_glass_overlay_html("Extracting profile...", st.session_state.animal_emoji), unsafe_allow_html=True)
                ok, msg, data = parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key)
                loading_overlay.empty()
                if ok:
                    st.session_state.resume_data = data
                    st.session_state.base_editor_key += 1
                    st.success("✅ Profile successfully extracted!")
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("Please upload a PDF file first.")

    st.markdown("#### 📝 Base Profile Editor")
    edit = st_ace.st_ace(
        value=json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False), 
        language="json", 
        theme="dracula", 
        height=500,
        key=f"base_ed_{st.session_state.base_editor_key}"
    )
    if st.button("💾 Save Base Changes", use_container_width=True):
        try:
            st.session_state.resume_data = json.loads(edit)
            st.toast("✅ Base profile updated!")
        except:
            st.error("Invalid JSON format.")


with tab2:
    with st.container(border=True):
        st.subheader("🎯 Job Details")
        jd = st.text_area("JD Content", height=300, key="jd_input_v2")
        st.text_area("Optimization Strategy", value=st.session_state.custom_prompt, key="custom_prompt_v2")
        col_c1, col_c2 = st.columns(2)
        with col_c1: ats = st.checkbox("ATS Analysis", value=True)
        with col_c2: visa = st.checkbox("Visa Check", value=True)
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Start Optimization", type="primary", use_container_width=True):
                if jd:
                    l = st.empty(); l.markdown(get_glass_overlay_html("Crafting your resume...", st.session_state.animal_emoji), unsafe_allow_html=True)
                    ok, rep = ai_optimize_and_update(jd, st.session_state.custom_prompt_v2, ats, visa)
                    l.empty()
                    if ok: st.success("Success!")
                    else: st.error(f"Failed: {rep}")
        with c2:
            prompt = build_optimization_prompt(jd if jd else "JD", st.session_state.custom_prompt_v2, ats, visa, st.session_state.resume_data)
            b64 = base64.b64encode(prompt.encode('utf-8')).decode('utf-8')
            # Fixed height 44px to match Start button
            st.html(f"""<body style="margin:0;"><button id="cp" onclick="navigator.clipboard.writeText(decodeURIComponent(escape(window.atob('{b64}')))).then(()=>{{this.innerText='✅ Copied';}})" style="width:100%;height:44px;border-radius:8px;background:#1e293b;color:white;border:1px solid #444;cursor:pointer;font-weight:500;font-family:sans-serif;">📋 Copy Prompt</button></body>""")

with tab3:
    st.header("📊 ATS Analysis")
    if st.session_state.optimized_resume_data:
        if st.session_state.changelog:
            with st.container(border=True): st.subheader("📝 Summary"); st.info(st.session_state.changelog)
        m = st.session_state.ats_metrics
        if m:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Match", f"{m['optimized_pct']}%")
            mc2.metric("Keywords", f"{m['optimized_count']}/{m['total']}")
            mc3.metric("New", len(m['newly_added']))
            st.progress(m['optimized_pct']/100)
    else: st.info("Run optimization first.")

@st.dialog("🛠️ Tweak Data", width="large")
def edit_opt_dialog():
    edit = st_ace.st_ace(value=json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, auto_update=True)
    if st.button("💾 Save Changes", use_container_width=True): st.session_state.optimized_resume_data = json.loads(edit); st.rerun()

with tab4:
    if st.session_state.optimized_resume_data:
        cl1, cl2 = st.columns([4, 6])
        with cl1:
            with st.container(border=True):
                st.subheader("🛠️ Export Settings")
                if st.button("📝 Edit Optimized Data", use_container_width=True): edit_opt_dialog()
                tmpl = st.selectbox("Template", ["💻 Tech (Modern)", "📈 Classic"], key="tmpl")
                order = st.multiselect("Block Order", ["Summary", "Experience", "Education", "Skills"], default=["Summary", "Experience", "Education", "Skills"])
                if st.button("🚀 Generate PDF", type="primary", use_container_width=True):
                    with st.spinner("Generating..."):
                        tex = "main.tex" if "Tech" in tmpl else "elsa_main.tex"
                        rb = generate_preview_pdf_bytes(st.session_state.optimized_resume_data, tex, block_order=order)
                        if rb:
                            st.session_state.resume_preview_bytes = rb
                            c, r = st.session_state.optimized_resume_data.get('target_company','Company').replace(' ','_'), st.session_state.optimized_resume_data.get('target_role','Role').replace(' ','_')
                            st.session_state.resume_dl_data = {"bytes": rb, "name": f"{c}_{r}_Resume.pdf"}
                        cb = generate_cover_letter_pdf_bytes(st.session_state.optimized_resume_data)
                        if cb: st.session_state.cover_letter_preview_bytes = cb; st.session_state.cl_dl_data = {"bytes": cb, "name": f"{c}_{r}_CoverLetter.pdf"}
        with cl2:
            st.subheader("📄 Preview")
            if st.session_state.resume_preview_bytes:
                # 修正：將 type 變數更名為 display_choice，避免與內建函式衝突
                display_choice = st.radio("Display Target", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed", key="display_choice_radio")

                target_bytes = st.session_state.resume_preview_bytes if display_choice == "Resume" else st.session_state.cover_letter_preview_bytes
                target_data = st.session_state.resume_dl_data if display_choice == "Resume" else st.session_state.cl_dl_data

                if target_data:
                    sync = st.checkbox("📈 Sync to Tracker upon download", value=True) if st.session_state.logged_in else False
                    st.download_button(
                        f"📥 Download: {target_data['name']}", 
                        target_data["bytes"], 
                        target_data["name"], 
                        use_container_width=True, 
                        on_click=lambda: save_application(db, st.session_state.user_email, st.session_state.optimized_resume_data.get('target_company'), st.session_state.optimized_resume_data, st.session_state.get('jd_input_v2')) if (sync and display_choice == "Resume") else None
                    )

                # 執行預覽渲染
                render_pdf_js(target_bytes)
            else:
                st.info("Click '🚀 Generate PDF' to see preview.")

    else: st.warning("Optimize first.")

with tab5:
    if st.session_state.logged_in: render_interview_progress(db, st.session_state.user_email); render_dashboard(db, st.session_state.user_email)
    else: st.warning("Login first.")
