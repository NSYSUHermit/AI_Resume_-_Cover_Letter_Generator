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

# 🚀 1. 全域資料庫初始化 (最優先)
db = init_firebase()

# ---------------------------------------------------------
# AI Prompt Builder
# ---------------------------------------------------------
def build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, resume_data):
    """Helper to build high-impact optimization instructions"""
    ats_block = '"keyword_analysis": {"jd_keywords": [], "original_hits": [], "optimized_hits": [], "newly_added": [], "missing_keywords": []},' if enable_ats else ""
    visa_instr = "- Step 1: Check for visa sponsorship restrictions in the JD. If found, set 'visa_blocked': true and provide a reason." if check_visa else ""
    return f"""
Optimize resume for JD. 
[COMMANDS]: {custom_prompt}
[RULES]: 1. Return ONLY valid JSON. 2. {visa_instr}
[Target JD]: {jd_text}
[Original Resume]: {json.dumps(resume_data, ensure_ascii=False)}
[FORMAT]: {{ "visa_blocked": false, "reason": "", "changelog": "", {ats_block} "optimized_resume": {{...}} }}
"""

# ---------------------------------------------------------
# 初始化 Session State (JSON 資料結構)
# ---------------------------------------------------------
if "resume_data" not in st.session_state:
    st.session_state.resume_data = {
        "heading": { "name": "John Doe", "email": "johndoe@example.com", "phone": "+1-234-567-8900", "website": "github.com/johndoe", "linkedin": "linkedin.com/in/johndoe" },
        "cover_letter": "", "target_company": "", "target_role": "", "about me more": "", "summary": "", "education": [], "experience": [], "projects": [], "patents": [], "skills": { "set1": { "title": "Skills", "items": [] } }
    }

if "optimized_resume_data" not in st.session_state: st.session_state.optimized_resume_data = None
if "base_editor_key" not in st.session_state: st.session_state.base_editor_key = 0
if "opt_editor_key" not in st.session_state: st.session_state.opt_editor_key = 0
if "ats_metrics" not in st.session_state: st.session_state.ats_metrics = None
if "changelog" not in st.session_state: st.session_state.changelog = ""
if "custom_prompt" not in st.session_state:
    st.session_state.custom_prompt = """You are an elite Career Strategist and ATS Architect. Overhaul the resume based on the JD using these rules:
1. **Strategic Quantization**: Every experience bullet point MUST include a metric (%, $, time saved, scale).
2. **Aggressive Action Verbs**: Use high-ownership verbs like 'Spearheaded', 'Engineered', 'Orchestrated'.
3. **ATS Semantic Mapping**: Perform 'Horizontal Shifts' (e.g., AWS Experience to 'Cloud-native architecture').
4. **Pain Point Alignment**: Demonstrating how I solved problems mentioned in the JD."""
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None
if "resume_dl_data" not in st.session_state: st.session_state.resume_dl_data = None
if "cl_dl_data" not in st.session_state: st.session_state.cl_dl_data = None

# ---------------------------------------------------------
# AI 核心穩定邏輯
# ---------------------------------------------------------
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key: return False, "⚠️ Please set your API KEY in the sidebar first.", None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        response = model.generate_content(["Parse this PDF resume into JSON format. Return ONLY valid JSON.", pdf_part])
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        return True, "✅ Success!", json.loads(raw_text)
    except Exception as e: return False, f"⚠️ Error: {e}", None

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key")
        if not api_key: return False, "⚠️ API Key missing."
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        response = model.generate_content(prompt)
        
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        res = json.loads(raw_text)
        
        if res.get("visa_blocked"): return False, f"⛔ Visa Restriction: {res.get('reason')}"
        
        st.session_state.optimized_resume_data = res.get("optimized_resume")
        st.session_state.opt_editor_key += 1
        st.session_state.changelog = res.get("changelog", "")
        
        if enable_ats and "keyword_analysis" in res:
            kw = res["keyword_analysis"]
            tot = max(1, len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", [])))
            st.session_state.ats_metrics = {
                "total": tot, "original_count": len(kw.get("original_hits", [])), "optimized_count": len(kw.get("optimized_hits", [])),
                "original_pct": int((len(kw.get("original_hits", []))/tot)*100), "optimized_pct": int((len(kw.get("optimized_hits", []))/tot)*100),
                "optimized_hits": kw.get("optimized_hits", []), "newly_added": kw.get("newly_added", []), "missing_keywords": kw.get("missing_keywords", [])
            }
        return True, "✅ Done"
    except Exception as e: return False, str(e)

# ---------------------------------------------------------
# PDF 渲染邏輯 (穩定版)
# ---------------------------------------------------------
def render_pdf_js(pdf_bytes):
    if not pdf_bytes: return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""
    <!DOCTYPE html><html><head>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <style>body{{margin:0;background:#0f172a;display:flex;flex-direction:column;align-items:center;padding:20px;}} canvas{{margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.5);border-radius:8px;max-width:95%;}}</style>
    </head><body><div id="p"></div><script>
    pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
    var b=window.atob('{base64_pdf}');var bytes=new Uint8Array(b.length);for(var i=0;i<b.length;i++)bytes[i]=b.charCodeAt(i);
    pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{
        for(var i=1;i<=pdf.numPages;i++)pdf.getPage(i).then(function(page){{
            var v=page.getViewport({{scale:1.5}});var c=document.createElement('canvas');c.height=v.height;c.width=v.width;
            document.getElementById('p').appendChild(c);page.render({{canvasContext:c.getContext('2d'),viewport:v}});
        }});
    }});
    </script></body></html>"""
    components.html(pdf_js_html, height=800, scrolling=True)

def generate_preview_pdf_bytes(data, template_name, block_order):
    try:
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(template_name, td)
            tp = os.path.join(td, template_name)
            with open(tp, "r", encoding="utf-8") as f: content = f.read()
            if block_order and "BLOCKS_PLACEHOLDER" in content:
                bs = ""
                for b in block_order:
                    if b == "Summary": bs += "\\directlua{printSummary()}\n"
                    elif b == "Experience": bs += "\\section{WORK EXPERIENCE}\n\\directlua{printExperience()}\n"
                    elif b == "Education": bs += "\\section{EDUCATION}\n\\directlua{printEducation()}\n"
                    elif b == "Projects & Patents": bs += "\\directlua{printProjectsAndPatents()}\n"
                    elif b == "Skills": bs += "\\section{SKILLS}\n\\directlua{printSkills()}\n"
                content = content.replace("BLOCKS_PLACEHOLDER", bs)
                with open(tp, "w", encoding="utf-8") as f: f.write(content)
            with open(os.path.join(td, "ml_resume.json"), "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
            subprocess.run(['lualatex', '-interaction=nonstopmode', template_name], cwd=td, capture_output=True)
            op = tp.replace(".tex", ".pdf")
            if os.path.exists(op):
                with open(op, "rb") as f: return f.read()
    except: return None
    return None

def generate_cover_letter_pdf_bytes(data):
    try:
        txt = data.get('cover_letter', '').replace('**', '')
        lat = r"""\documentclass[11pt]{article}\usepackage[margin=1in]{geometry}\usepackage{fontspec}\begin{document}""" + txt.replace("\n", "\n\n") + r"""\end{document}"""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "cl.tex"), "w", encoding="utf-8") as f: f.write(lat)
            subprocess.run(['lualatex', '-interaction=nonstopmode', 'cl.tex'], cwd=td)
            if os.path.exists(os.path.join(td, "cl.pdf")):
                with open(os.path.join(td, "cl.pdf"), "rb") as f: return f.read()
    except: return None
    return None

def get_glass_overlay_html(message, animal):
    return f"""<div style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.85);backdrop-filter:blur(10px);z-index:9999;display:flex;justify-content:center;align-items:center;color:white;flex-direction:column;font-family:sans-serif;"><h1>{animal}</h1><h3>{message}</h3></div>"""

# ---------------------------------------------------------
# UI 介面設定
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume Builder", page_icon="🚀", layout="wide")

# 🎨 EXCLUSIVE MODERN CSS (Shadcn/UI Vibe)
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
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
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
        border: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #334155 !important;
        color: white !important;
        border-bottom: 2px solid #6366f1 !important;
    }
    
    [data-testid="stSidebar"] { background-color: #0f172a; }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.markdown("### 🚀 AI Resume Gen")
    st.markdown("---")
    if st.session_state.logged_in:
        st.success(f"**Welcome back,**\n`{st.session_state.user_email}`")
        with st.expander("☁️ Cloud Sync"):
            if st.button("Push to Cloud", use_container_width=True): save_user_profile(db, st.session_state.user_email, st.session_state.resume_data, st.session_state.custom_prompt, st.session_state.api_key)
            if st.button("Pull from Cloud", use_container_width=True):
                r, pr, k = load_user_profile(db, st.session_state.user_email)
                if r: st.session_state.resume_data = r; st.session_state.custom_prompt = pr; st.session_state.api_key = k; st.rerun()
        if st.button("🚪 Logout", use_container_width=True): st.session_state.logged_in = False; st.rerun()
    else:
        with st.form("login"):
            st.subheader("🔑 Login")
            e = st.text_input("Email").strip(); p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if authenticate_user(db, e, p): 
                    st.session_state.logged_in = True; st.session_state.user_email = e
                    r, pr, k = load_user_profile(db, e)
                    if r: st.session_state.resume_data = r; st.session_state.custom_prompt = pr; st.session_state.api_key = k
                    st.rerun()
        with st.expander("📝 Register Account"):
            with st.form("reg"):
                re = st.text_input("New Email"); rp = st.text_input("New Password", type="password")
                if st.form_submit_button("Register", use_container_width=True):
                    ok, msg = register_user(db, re, rp)
                    if ok: st.success(msg)
                    else: st.error(msg)
    st.markdown("---")
    st.text_input("🔑 API Key", type="password", key="api_key")
    st.selectbox("🧠 Model", ["gemini-2.5-flash", "gemini-2.5-pro"], key="ai_model")
    st.selectbox("Animal", ["🦦 Otter", "🐕 Dog", "🦖 T-Rex"], key="animal_emoji_select")
    st.session_state.animal_emoji = st.session_state.animal_emoji_select.split(" ")[0]

# --- Header & Stepper ---
st.title("🚀 Professional AI Resume")

# Dynamic Stepper logic
s1_done = len(st.session_state.resume_data.get("experience", [])) > 0
s2_done = len(st.session_state.get("jd_v2", "")) > 50
s3_done = st.session_state.optimized_resume_data is not None
s4_done = st.session_state.resume_preview_bytes is not None
steps = [
    {"l": "1. Source", "d": s1_done, "m": "Profile Ready" if s1_done else "Import Resume"},
    {"l": "2. Target", "d": s2_done, "m": "JD Linked" if s2_done else "Paste JD"},
    {"l": "3. Analysis", "d": s3_done, "m": "AI Optimized" if s3_done else "Run AI"},
    {"l": "4. Review", "d": s4_done, "m": "PDF Ready" if s4_done else "Export PDF"},
    {"l": "5. Tracker", "d": st.session_state.logged_in, "m": "Synced" if st.session_state.logged_in else "Login to Track"}
]

step_cols = st.columns(5)
for i, s in enumerate(steps):
    with step_cols[i]:
        c = "#10b981" if s["d"] else ("#6366f1" if (i == 0 or steps[i-1]["d"]) else "#334155")
        st.markdown(f"""<div style='text-align:center;padding:10px;border-radius:10px;background:{c}15;border:1px solid {c}40;'>
            <p style='margin:0;font-size:0.8rem;color:{c};font-weight:bold;'>{'✅' if s['d'] else '🔵'} {s['l']}</p>
            <p style='margin:0;font-size:0.7rem;color:#94a3b8;'>{s['m']}</p>
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# --- Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([" 📁 Source ", " 🎯 Target ", " 📊 ATS Analysis ", " 📝 Editor & Export ", " 📈 Job Tracker "])

with tab1:
    with st.container(border=True):
        st.subheader("📥 Quick Import")
        st.write("Upload your existing PDF resume to bootstrap your profile with AI.")
        up = st.file_uploader("Upload PDF", type=["pdf"], key="up1", label_visibility="collapsed")
        if st.button("✨ Extract with AI", type="primary", use_container_width=True) and up:
            loading_overlay = st.empty(); loading_overlay.markdown(get_glass_overlay_html("Extracting...", st.session_state.animal_emoji), unsafe_allow_html=True)
            ok, msg, data = parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key)
            loading_overlay.empty()
            if ok: st.session_state.resume_data = data; st.session_state.base_editor_key += 1; st.rerun()
            else: st.error(msg)
    
    st.markdown("#### 📝 Base Profile Editor")
    edit = st_ace.st_ace(value=json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, key=f"base_ed_{st.session_state.base_editor_key}")
    if st.button("💾 Save Base Changes", use_container_width=True): st.session_state.resume_data = json.loads(edit); st.toast("✅ Saved!")

with tab2:
    with st.container(border=True):
        st.subheader("🎯 Job Details")
        jd = st.text_area("Job Description (JD)", height=300, key="jd_v2", placeholder="Paste target JD here...")
        st.text_area("Optimization Strategy", value=st.session_state.custom_prompt, key="cp_v2", height=150)
        col_opt_c1, col_opt_c2 = st.columns(2)
        with col_opt_c1: ats_check = st.checkbox("ATS Keyword Analysis", value=True)
        with col_opt_c2: visa_check = st.checkbox("Visa Sponsorship Check", value=True)
        st.markdown("---")
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("🚀 Start AI Optimization", type="primary", use_container_width=True):
                if jd:
                    l = st.empty(); l.markdown(get_glass_overlay_html("Crafting your resume...", st.session_state.animal_emoji), unsafe_allow_html=True)
                    ok, rep = ai_optimize_and_update(jd, st.session_state.cp_v2, ats_check, visa_check)
                    l.empty()
                    if ok: st.success("✅ Success! Check 'ATS Analysis' tab.")
                    else: st.error(f"❌ Failed: {rep}")
                else: st.warning("Please paste JD first.")
        with c_btn2:
            p_text = build_optimization_prompt(jd if jd else "JD", st.session_state.cp_v2, True, True, st.session_state.resume_data)
            b64_p = base64.b64encode(p_text.encode('utf-8')).decode('utf-8')
            st.html(f"""<body style="margin:0;"><button id="cp" onclick="navigator.clipboard.writeText(decodeURIComponent(escape(window.atob('{b64_p}')))).then(()=>{{this.innerText='✅ Copied';}})" style="width:100%;height:44px;border-radius:8px;background:#1e293b;color:white;border:1px solid #444;cursor:pointer;font-weight:500;font-family:sans-serif;display:flex;align-items:center;justify-content:center;">📋 Copy Prompt</button></body>""")

with tab3:
    st.header("📊 ATS Analysis & Import")
    with st.expander("📥 Import Result from External AI", expanded=not st.session_state.optimized_resume_data):
        ext_json = st.text_area("Paste External JSON response here", height=200, key="ext_json_tab3")
        if st.button("🚀 Apply External JSON", use_container_width=True):
            try:
                raw = ext_json.replace('```json', '').replace('```', '').strip()
                data = json.loads(raw)
                st.session_state.optimized_resume_data = data.get("optimized_resume", data)
                st.session_state.changelog = data.get("changelog", "Imported.")
                if "keyword_analysis" in data:
                    kw = data["keyword_analysis"]
                    tot = max(1, len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", [])))
                    st.session_state.ats_metrics = { "total": tot, "original_count": len(kw.get("original_hits", [])), "optimized_count": len(kw.get("optimized_hits", [])), "original_pct": int((len(kw.get("original_hits", []))/tot)*100), "optimized_pct": int((len(kw.get("optimized_hits", []))/tot)*100), "optimized_hits": kw.get("optimized_hits", []), "newly_added": kw.get("newly_added", []), "missing_keywords": kw.get("missing_keywords", []) }
                st.success("✅ Applied!"); st.rerun()
            except: st.error("❌ Invalid JSON.")

    if st.session_state.optimized_resume_data:
        m = st.session_state.ats_metrics
        if m:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Match Rate", f"{m['optimized_pct']}%", f"+{m['optimized_pct']-m['original_pct']}%")
            mc2.metric("Keywords Hit", f"{m['optimized_count']}/{m['total']}")
            mc3.metric("New Added", len(m['newly_added']))
            st.progress(m['optimized_pct']/100)
            st.markdown("---")
            k1, k2 = st.columns(2)
            with k1:
                st.success("✅ **Hit Keywords**")
                for k in m.get('optimized_hits', []): st.markdown(f"- `{k}`" + (" 🌟" if k in m.get('newly_added', []) else ""))
            with k2:
                st.error("❌ **Missing Keywords**")
                for k in m.get('missing_keywords', []): st.markdown(f"- `{k}`")
        if st.session_state.changelog:
            st.markdown("---"); st.subheader("📝 Optimization Summary"); st.info(st.session_state.changelog)
    else: st.info("Run AI Optimization in **Step 2** to see results here.")

@st.dialog("🛠️ Tweak Optimized Data", width="large")
def edit_opt_dialog():
    st.write("Edit the custom resume data below. Saving will update the PDF source.")
    edit = st_ace.st_ace(value=json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, auto_update=True)
    if st.button("💾 Save Changes", use_container_width=True): 
        st.session_state.optimized_resume_data = json.loads(edit); st.rerun()

with tab4:
    if st.session_state.optimized_resume_data:
        l, r = st.columns([4, 6])
        with l:
            with st.container(border=True):
                st.subheader("🛠️ Export Settings")
                if st.button("📝 Edit Optimized JSON", use_container_width=True): edit_opt_dialog()
                tmpl = st.selectbox("Template", ["💻 Tech (Modern)", "📈 Classic"], key="tm")
                order = st.multiselect("Block Order", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"])
                if st.button("🚀 Generate PDF", type="primary", use_container_width=True):
                    with st.spinner("Generating Documents..."):
                        data = st.session_state.optimized_resume_data
                        tex = "main.tex" if "Tech" in tmpl else "elsa_main.tex"
                        rb = generate_preview_pdf_bytes(data, tex, order)
                        if rb:
                            st.session_state.resume_preview_bytes = rb
                            c, role = data.get('target_company','Company').replace(' ','_'), data.get('target_role','Role').replace(' ','_')
                            st.session_state.resume_dl_data = {"bytes": rb, "name": f"{c}_{role}_Resume.pdf"}
                        cb = generate_cover_letter_pdf_bytes(data)
                        if cb: st.session_state.cover_letter_preview_bytes = cb; st.session_state.cl_dl_data = {"bytes": cb, "name": f"{c}_{role}_CoverLetter.pdf"}
                        st.toast("✅ Ready!")
        with r:
            st.subheader("📄 Preview & Download")
            if st.session_state.resume_preview_bytes:
                ch = st.radio("Display", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed")
                target = st.session_state.resume_preview_bytes if ch == "Resume" else st.session_state.cover_letter_preview_bytes
                dl_info = st.session_state.resume_dl_data if ch == "Resume" else st.session_state.cl_dl_data
                sync = st.checkbox("📈 Sync to Tracker upon download", value=True) if st.session_state.logged_in else False
                if st.download_button(f"📥 Download: {dl_info['name']}", dl_info["bytes"], dl_info["name"], use_container_width=True):
                    if sync and ch == "Resume": save_application(db, st.session_state.user_email, st.session_state.optimized_resume_data.get('target_company'), st.session_state.optimized_resume_data, st.session_state.get('jd_v2'))
                render_pdf_js(target)
            else: st.info("Click '🚀 Generate PDF' to preview.")
    else: st.warning("⚠️ No optimized data. Run AI in **Step 2** first.")

with tab5:
    if st.session_state.logged_in: render_interview_progress(db, st.session_state.user_email); render_dashboard(db, st.session_state.user_email)
    else: st.warning("🔒 Login in the sidebar to track applications.")
