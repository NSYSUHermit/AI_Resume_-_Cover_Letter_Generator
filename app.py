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

# 🚀 1. 全域資料庫初始化
db = init_firebase()

# ---------------------------------------------------------
# AI Prompt Builder
# ---------------------------------------------------------
def build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, resume_data):
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
# 初始化 Session State
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
    st.session_state.custom_prompt = "Optimize for high-impact metrics and ATS keywords."
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None
if "resume_dl_data" not in st.session_state: st.session_state.resume_dl_data = None
if "cl_dl_data" not in st.session_state: st.session_state.cl_dl_data = None

# ---------------------------------------------------------
# AI 核心邏輯
# ---------------------------------------------------------
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key: return False, "API Key missing.", None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        response = model.generate_content(["Parse this PDF resume into JSON format. Return ONLY valid JSON.", pdf_part])
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        return True, "Success!", json.loads(raw_text)
    except Exception as e: return False, str(e), None

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key")
        if not api_key: return False, "API Key missing."
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        final_prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        response = model.generate_content(final_prompt)
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        res = json.loads(raw_text)
        
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
        return True, "Done"
    except Exception as e: return False, str(e)

# ---------------------------------------------------------
# PDF 渲染邏輯
# ---------------------------------------------------------
def render_pdf_js(pdf_bytes):
    if not pdf_bytes:
        return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""<!DOCTYPE html><html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script><style>body{{margin:0;background:#0f172a;display:flex;flex-direction:column;align-items:center;padding:20px;}} canvas{{margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.5);border-radius:8px;max-width:95%;}}</style></head><body><div id="p"></div><script>pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';var b=window.atob('{base64_pdf}');var bytes=new Uint8Array(b.length);for(var i=0;i<b.length;i++)bytes[i]=b.charCodeAt(i);pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{for(var i=1;i<=pdf.numPages;i++)pdf.getPage(i).then(function(page){{var v=page.getViewport({{scale:1.5}});var c=document.createElement('canvas');c.height=v.height;c.width=v.width;document.getElementById('p').appendChild(c);page.render({{canvasContext:c.getContext('2d'),viewport:v}});}});}});</script></body></html>"""
    components.html(pdf_js_html, height=800, scrolling=True)

# ---------------------------------------------------------
# PDF 生成函式
# ---------------------------------------------------------
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
        # 🚀 智能抓取：容錯處理 cover_letter 與 coverLetter
        cl_text = data.get('cover_letter') or data.get('coverLetter') or data.get('Cover Letter', '')
        if not cl_text: return None
        
        cl_text = cl_text.replace('**', '')
        latex = r"""\documentclass[11pt]{article}\usepackage[margin=1in]{geometry}\usepackage{fontspec}\begin{document}""" + cl_text.replace("\n", "\n\n") + r"""\end{document}"""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "cl.tex"), "w", encoding="utf-8") as f: f.write(latex)
            subprocess.run(['lualatex', '-interaction=nonstopmode', 'cl.tex'], cwd=td)
            if os.path.exists(os.path.join(td, "cl.pdf")):
                with open(os.path.join(td, "cl.pdf"), "rb") as f: return f.read()
    except: return None
    return None

def get_glass_overlay_html(message, animal):
    return f"""<div style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.85);backdrop-filter:blur(10px);z-index:9999;display:flex;justify-content:center;align-items:center;color:white;flex-direction:column;font-family:sans-serif;"><h1>{animal}</h1><h3>{message}</h3></div>"""

# ---------------------------------------------------------
# UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume", layout="wide")
st.markdown("""<style>@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');h1,h2,h3,p,label{font-family:'Inter',sans-serif!important;}div[data-testid="stVerticalBlock"]>div[style*="border"]{background-color:#ffffff05;border:1px solid rgba(255,255,255,0.1)!important;border-radius:12px!important;padding:1.5rem!important;}.stButton>button{border-radius:8px!important;height:44px!important;font-weight:500!important;}.stButton>button[kind="primary"]{background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%)!important;border:none!important;color:white!important;}[data-testid="stSidebar"]{background-color:#0f172a;}</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🚀 AI Resume Gen")
    if st.session_state.logged_in:
        st.success(f"User: {st.session_state.user_email}")
        if st.button("Push to Cloud", use_container_width=True): save_user_profile(db, st.session_state.user_email, st.session_state.resume_data, st.session_state.custom_prompt, st.session_state.api_key)
        if st.button("Logout", use_container_width=True): st.session_state.logged_in = False; st.rerun()
    else:
        with st.form("l"):
            e = st.text_input("Email"); p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if authenticate_user(db, e, p): 
                    st.session_state.logged_in = True; st.session_state.user_email = e; st.rerun()
    st.markdown("---")
    st.text_input("🔑 API Key", type="password", key="api_key")
    st.selectbox("🧠 Model", ["gemini-1.5-flash", "gemini-1.5-pro"], key="ai_model")
    st.selectbox("Animal", ["🦦 Otter", "🐕 Dog", "🦖 T-Rex"], key="animal_emoji_select")
    st.session_state.animal_emoji = st.session_state.animal_emoji_select.split(" ")[0]

# 動態進度指示器
s1, s2, s3, s4 = len(st.session_state.resume_data.get("experience", [])) > 0, len(st.session_state.get("jd_v2", "")) > 50, st.session_state.optimized_resume_data is not None, st.session_state.resume_preview_bytes is not None
steps = [{"l": "Source", "d": s1}, {"l": "Target", "d": s2}, {"l": "Analysis", "d": s3}, {"l": "Review", "d": s4}, {"l": "Tracker", "d": st.session_state.logged_in}]
cols = st.columns(5)
for i, s in enumerate(steps):
    with cols[i]:
        c = "#10b981" if s["d"] else "#6366f1"
        st.markdown(f"<div style='text-align:center;padding:10px;border-radius:10px;background:{c}15;border:1px solid {c}40;color:{c};font-weight:bold;'>{'✅' if s['d'] else '🔵'} {s['l']}</div>", unsafe_allow_html=True)

t1, t2, t3, t4, t5 = st.tabs([" 📁 Source ", " 🎯 Target ", " 📊 ATS ", " 📝 Export ", " 📈 Tracker "])

with t1:
    with st.container(border=True):
        st.subheader("📥 Import from PDF")
        up = st.file_uploader("Upload", type=["pdf"], key="up1", label_visibility="collapsed")
        if st.button("✨ Extract Data", type="primary", use_container_width=True) and up:
            ok, msg, data = parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key)
            if ok: st.session_state.resume_data = data; st.rerun()
    st.markdown("#### 📝 Base Profile Editor")
    edit = st_ace.st_ace(value=json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, key=f"base_ed_{st.session_state.base_editor_key}")
    if st.button("💾 Save Base Changes", use_container_width=True): st.session_state.resume_data = json.loads(edit); st.toast("Saved!")

with t2:
    with st.container(border=True):
        st.subheader("🎯 Job Details")
        jd = st.text_area("JD Content", height=300, key="jd_v2")
        st.text_area("Prompt", value=st.session_state.custom_prompt, key="cp_v2", height=150)
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Start AI Optimization", type="primary", use_container_width=True):
                if jd:
                    with st.spinner("Optimizing..."):
                        ok, rep = ai_optimize_and_update(jd, st.session_state.cp_v2, True, True)
                        if ok: st.success("Done!")
                        else: st.error(rep)
        with c2:
            p_text = build_optimization_prompt(jd if jd else "JD", st.session_state.cp_v2, True, True, st.session_state.resume_data)
            b64_p = base64.b64encode(p_text.encode('utf-8')).decode('utf-8')
            st.html(f"""<body style="margin:0;"><button onclick="navigator.clipboard.writeText(decodeURIComponent(escape(window.atob('{b64_p}')))).then(()=>{{this.innerText='✅ Copied';}})" style="width:100%;height:44px;border-radius:8px;background:#1e293b;color:white;border:1px solid #444;cursor:pointer;font-weight:500;">📋 Copy Prompt</button></body>""")

with t3:
    st.header("📊 ATS Analysis")
    if st.session_state.optimized_resume_data:
        m = st.session_state.ats_metrics
        if m:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Match Rate", f"{m['optimized_pct']}%")
            mc2.metric("Keywords", f"{m['optimized_count']}/{m['total']}")
            mc3.metric("New Added", len(m['newly_added']))
            st.progress(m['optimized_pct']/100)
            st.markdown("---")
            k1, k2 = st.columns(2)
            with k1:
                st.success("✅ **Hit Keywords**")
                for k in m.get('optimized_hits', []): st.markdown(f"- `{k}`" + (" 🌟" if k in m.get('newly_added', []) else ""))
            with k2:
                st.error("❌ **Missing**")
                for k in m.get('missing_keywords', []): st.markdown(f"- `{k}`")
        if st.session_state.changelog: st.info(st.session_state.changelog)
    else: st.info("Run optimization first.")

@st.dialog("🛠️ Tweak Data", width="large")
def edit_opt_dialog():
    edit = st_ace.st_ace(value=json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, auto_update=True)
    if st.button("💾 Save Changes", use_container_width=True): 
        st.session_state.optimized_resume_data = json.loads(edit); st.rerun()

with t4:
    if st.session_state.optimized_resume_data:
        l, r = st.columns([4, 6])
        with l:
            with st.container(border=True):
                st.subheader("🛠️ Settings")
                if st.button("📝 Edit Optimized JSON", use_container_width=True): edit_opt_dialog()
                tmpl = st.selectbox("Template", ["💻 Tech", "📈 Classic"], key="tm")
                order = st.multiselect("Order", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"])
                if st.button("🚀 Generate PDF", type="primary", use_container_width=True):
                    with st.spinner("Generating..."):
                        data = st.session_state.optimized_resume_data
                        tex = "main.tex" if "Tech" in tmpl else "elsa_main.tex"
                        rb = generate_preview_pdf_bytes(data, tex, order)
                        if rb:
                            st.session_state.resume_preview_bytes = rb
                            c, role = data.get('target_company','Company').replace(' ','_'), data.get('target_role','Role').replace(' ','_')
                            st.session_state.resume_dl_data = {"bytes": rb, "name": f"{c}_{role}_Resume.pdf"}
                        cb = generate_cover_letter_pdf_bytes(data)
                        if cb:
                            st.session_state.cover_letter_preview_bytes = cb
                            st.session_state.cl_dl_data = {"bytes": cb, "name": f"{c}_{role}_CL.pdf"}
                        st.toast("Ready!")
        with r:
            st.subheader("📄 Preview")
            if st.session_state.resume_preview_bytes or st.session_state.cover_letter_preview_bytes:
                ch = st.radio("Display", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed", key="preview_radio")
                target = st.session_state.resume_preview_bytes if ch == "Resume" else st.session_state.cover_letter_preview_bytes
                dl = st.session_state.resume_dl_data if ch == "Resume" else st.session_state.cl_dl_data
                
                if dl:
                    sync = st.checkbox("📈 Sync to Tracker", value=True) if st.session_state.logged_in else False
                    st.download_button(f"📥 Download {dl['name']}", dl["bytes"], dl["name"], use_container_width=True)
                
                if target: render_pdf_js(target)
                else: st.info(f"The {ch} has not been generated yet.")
            else: st.info("Click 'Generate PDF' to see preview.")
    else: st.warning("Optimize first.")

with t5:
    if st.session_state.logged_in: render_interview_progress(db, st.session_state.user_email); render_dashboard(db, st.session_state.user_email)
    else: st.warning("Login first.")
