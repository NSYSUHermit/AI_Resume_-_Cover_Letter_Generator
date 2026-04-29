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
# AI Prompt Builder (放在最頂部確保全域可用)
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
# 初始化 Session State
# ---------------------------------------------------------
if "resume_data" not in st.session_state:
    st.session_state.resume_data = {
        "heading": { "name": "John Doe", "email": "johndoe@example.com", "phone": "+1-234-567-8900", "website": "github.com/johndoe", "linkedin": "linkedin.com/in/johndoe" },
        "cover_letter": "I am writing to express my strong interest in...",
        "target_company": "Company", "target_role": "Software Engineer",
        "about me more": "", "summary": "", "education": [], "experience": [], "projects": [], "patents": [],
        "skills": { "set1": { "title": "Skills", "items": [] } }
    }

if "optimized_resume_data" not in st.session_state: st.session_state.optimized_resume_data = None
if "base_editor_key" not in st.session_state: st.session_state.base_editor_key = 0
if "opt_editor_key" not in st.session_state: st.session_state.opt_editor_key = 0
if "ats_metrics" not in st.session_state: st.session_state.ats_metrics = None
if "changelog" not in st.session_state: st.session_state.changelog = ""
if "custom_prompt" not in st.session_state:
    st.session_state.custom_prompt = """You are an elite Career Strategist and ATS Architect. Overhaul the resume based on the JD:
1. **Strategic Quantization**: Every bullet MUST include a metric (%, $, time saved).
2. **Aggressive Action Verbs**: Use high-ownership verbs like Spearheaded, Engineered.
3. **ATS Mapping**: Align keywords to match JD requirements."""
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None

# ---------------------------------------------------------
# AI 核心邏輯
# ---------------------------------------------------------
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key: return False, "API Key missing.", None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = "Parse this PDF resume into JSON format. Return ONLY valid JSON."
        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        response = model.generate_content([prompt, pdf_part])
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        return True, "Success!", json.loads(raw_text)
    except Exception as e: return False, str(e), None

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key")
        if not api_key: return False, "API Key missing."
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        final_prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        response = model.generate_content(final_prompt)
        
        raw_text = response.text.strip()
        if "```" in raw_text: raw_text = raw_text.split("```")[1].replace("json", "").strip()
        res = json.loads(raw_text)
        
        if res.get("visa_blocked"): return False, f"Visa: {res.get('reason')}"
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
# PDF 渲染與生成
# ---------------------------------------------------------
def render_pdf_js(pdf_bytes):
    if not pdf_bytes: return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""<!DOCTYPE html><html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script><style>body{{margin:0;background:#0f172a;display:flex;flex-direction:column;align-items:center;padding:20px;}} canvas{{margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.5);border-radius:8px;max-width:95%;}}</style></head><body><div id="p"></div><script>pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';var b=window.atob('{base64_pdf}');var bytes=new Uint8Array(b.length);for(var i=0;i<b.length;i++)bytes[i]=b.charCodeAt(i);pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{for(var i=1;i<=pdf.numPages;i++)pdf.getPage(i).then(function(page){{var v=page.getViewport({{scale:1.5}});var c=document.createElement('canvas');c.height=v.height;c.width=v.width;document.getElementById('p').appendChild(c);page.render({{canvasContext:c.getContext('2d'),viewport:v}});}});}});</script></body></html>"""
    components.html(pdf_js_html, height=800, scrolling=True)

def generate_preview_pdf_bytes(data, template_name="main.tex", block_order=None):
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copy(template_name, temp_dir)
            tex_path = os.path.join(temp_dir, template_name)
            with open(tex_path, "r", encoding="utf-8") as f: content = f.read()
            if block_order and "BLOCKS_PLACEHOLDER" in content:
                blocks = ""
                for b in block_order:
                    if b == "Summary": blocks += "\\directlua{printSummary()}\n"
                    elif b == "Experience": blocks += "\\section{WORK EXPERIENCE}\n\\directlua{printExperience()}\n"
                    elif b == "Education": blocks += "\\section{EDUCATION}\n\\directlua{printEducation()}\n"
                    elif b == "Projects & Patents": blocks += "\\directlua{printProjectsAndPatents()}\n"
                    elif b == "Skills": blocks += "\\section{SKILLS}\n\\directlua{printSkills()}\n"
                content = content.replace("BLOCKS_PLACEHOLDER", blocks)
                with open(tex_path, "w", encoding="utf-8") as f: f.write(content)
            with open(os.path.join(temp_dir, "ml_resume.json"), "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
            subprocess.run(['lualatex', '-interaction=nonstopmode', template_name], cwd=temp_dir, capture_output=True)
            out_pdf = tex_path.replace(".tex", ".pdf")
            if os.path.exists(out_pdf):
                with open(out_pdf, "rb") as f: return f.read()
    except: return None
    return None

def generate_cover_letter_pdf_bytes(data):
    try:
        cl_text = data.get('cover_letter', '').replace('**', '')
        latex = r"""\documentclass[11pt]{article}\usepackage[margin=1in]{geometry}\usepackage{fontspec}\begin{document}""" + cl_text.replace("\n", "\n\n") + r"""\end{document}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, "cl.tex"), "w", encoding="utf-8") as f: f.write(latex)
            subprocess.run(['lualatex', '-interaction=nonstopmode', 'cl.tex'], cwd=temp_dir)
            if os.path.exists(os.path.join(temp_dir, "cl.pdf")):
                with open(os.path.join(temp_dir, "cl.pdf"), "rb") as f: return f.read()
    except: return None
    return None

# ---------------------------------------------------------
# UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume", page_icon="🚀", layout="wide")
st.markdown("""<style>@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');h1,h2,h3,p,label,.stText{font-family:'Inter',sans-serif!important;}div[data-testid="stVerticalBlock"]>div[style*="border"]{background-color:#ffffff05;border:1px solid rgba(255,255,255,0.1)!important;border-radius:12px!important;padding:1.5rem!important;}.stButton>button{border-radius:8px!important;height:44px!important;font-weight:500!important;}.stButton>button[kind="primary"]{background:linear-gradient(135deg,#6366f1 0%,#a855f7 100%)!important;border:none!important;color:white!important;}[data-testid="stSidebar"]{background-color:#0f172a;}</style>""", unsafe_allow_html=True)
db = init_firebase()

# --- Sidebar ---
with st.sidebar:
    st.markdown("### 🚀 AI Resume")
    if st.session_state.logged_in:
        st.success(f"User: {st.session_state.user_email}")
        if st.button("Push to Cloud", use_container_width=True): 
            save_user_profile(db, st.session_state.user_email, st.session_state.resume_data, st.session_state.custom_prompt, st.session_state.api_key)
        if st.button("Logout", use_container_width=True): 
            st.session_state.logged_in = False
            st.rerun()
    else:
        # --- 登入區塊 ---
        with st.form("login_form"):
            st.subheader("🔑 Login")
            e = st.text_input("Email").strip()
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if authenticate_user(db, e, p): 
                    st.session_state.logged_in = True
                    st.session_state.user_email = e
                    # 自動 Pull
                    r, pr, k = load_user_profile(db, e)
                    if r: st.session_state.resume_data = r; st.session_state.custom_prompt = pr; st.session_state.api_key = k
                    st.rerun()
                else:
                    st.error("Invalid credentials.")

        # --- 補回：註冊區塊 ---
        with st.expander("📝 Register New Account"):
            with st.form("register_form"):
                reg_email = st.text_input("New Email").strip()
                reg_pwd = st.text_input("New Password", type="password")
                if st.form_submit_button("Register", use_container_width=True):
                    if reg_email and reg_pwd:
                        ok, msg = register_user(db, reg_email, reg_pwd)
                        if ok: st.success(msg)
                        else: st.error(msg)
                    else:
                        st.warning("Please fill all fields.")

    st.markdown("---")
    st.text_input("🔑 API Key", type="password", key="api_key")
    st.selectbox("🧠 Model", ["gemini-2.5-flash", "gemini-2.5-pro"], key="ai_model")


# --- Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([" 📁 Source ", " 🎯 Target ", " 📊 ATS ", " 📝 Export ", " 📈 Tracker "])

with tab1:
    with st.container(border=True):
        st.subheader("📥 Import from PDF")
        up = st.file_uploader("Upload", type=["pdf"], key="up1", label_visibility="collapsed")
        if st.button("✨ Extract Data", type="primary", use_container_width=True) and up:
            ok, msg, data = parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key)
            if ok: st.session_state.resume_data = data; st.rerun()
    st.markdown("#### 📝 Base Profile Editor")
    edit = st_ace.st_ace(value=json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500)
    if st.button("💾 Save Changes", use_container_width=True): st.session_state.resume_data = json.loads(edit); st.toast("Saved!")

with tab2:
    with st.container(border=True):
        st.subheader("🎯 Job Details")
        jd = st.text_area("JD Content", height=300, key="jd_v2")
        st.text_area("Custom Prompt", value=st.session_state.custom_prompt, key="cp_v2", height=150)
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

with tab3:
    st.header("📊 ATS Analysis")
    
    # --- 📥 外部 JSON 匯入區域 ---
    with st.expander("📥 Import Result from External AI (ChatGPT/Claude)", expanded=not st.session_state.optimized_resume_data):
        ext_json = st.text_area("Paste the JSON response from other AIs here", height=200, key="ext_json_tab3")
        if st.button("🚀 Apply JSON", use_container_width=True):
            if ext_json.strip():
                try:
                    clean_str = ext_json.replace('```json', '').replace('```', '').strip()
                    data = json.loads(clean_str)
                    st.session_state.optimized_resume_data = data.get("optimized_resume", data)
                    st.session_state.opt_editor_key += 1
                    st.session_state.changelog = data.get("changelog", "Imported from external AI.")
                    
                    if "keyword_analysis" in data:
                        kw = data["keyword_analysis"]
                        tot = max(1, len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", [])))
                        st.session_state.ats_metrics = {
                            "total": tot, "original_count": len(kw.get("original_hits", [])), "optimized_count": len(kw.get("optimized_hits", [])),
                            "original_pct": int((len(kw.get("original_hits", []))/tot)*100), "optimized_pct": int((len(kw.get("optimized_hits", []))/tot)*100),
                            "optimized_hits": kw.get("optimized_hits", []), "newly_added": kw.get("newly_added", []), "missing_keywords": kw.get("missing_keywords", [])
                        }
                    st.success("✅ JSON applied!")
                    st.rerun()
                except Exception as e: st.error(f"Invalid JSON: {e}")

    if st.session_state.optimized_resume_data:
        m = st.session_state.ats_metrics
        if st.session_state.changelog:
            st.markdown("---")
            st.subheader("📝 Optimization Summary")
            st.info(st.session_state.changelog)
            
        if m:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Match Rate", f"{m['optimized_pct']}%")
            mc2.metric("Keywords", f"{m['optimized_count']}/{m['total']}")
            mc3.metric("New Added", len(m['newly_added']))
            st.progress(m['optimized_pct']/100)
            
            # --- 🚀 補回：關鍵字詳細列點 ---
            st.markdown("---")
            k_col1, k_col2 = st.columns(2)
            with k_col1:
                st.success("✅ **Hit Keywords**")
                for k in m.get('optimized_hits', []):
                    # 如果是新加入的，加個星星標記
                    star = " 🌟" if k in m.get('newly_added', []) else ""
                    st.markdown(f"- `{k}`{star}")
            with k_col2:
                st.error("❌ **Missing Keywords**")
                for k in m.get('missing_keywords', []):
                    st.markdown(f"- `{k}`")

    else: st.info("Run optimization first.")

@st.dialog("🛠️ Tweak Data", width="large")
def edit_opt_dialog():
    edit = st_ace.st_ace(value=json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, auto_update=True)
    if st.button("💾 Save Changes", use_container_width=True): st.session_state.optimized_resume_data = json.loads(edit); st.rerun()

with tab4:
    if st.session_state.optimized_resume_data:
        l, r = st.columns([4, 6])
        with l:
            with st.container(border=True):
                st.subheader("🛠️ Settings")
                if st.button("📝 Edit Optimized JSON", use_container_width=True): edit_opt_dialog()
                tmpl = st.selectbox("Template", ["💻 Tech (Modern)", "📈 Classic"], key="tm")
                order = st.multiselect("Order", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"])
            if st.button("🚀 Generate PDF", type="primary", use_container_width=True):
                    with st.spinner("Generating..."):
                        data = st.session_state.optimized_resume_data
                        tex = "main.tex" if "Tech" in tmpl else "elsa_main.tex"
                        rb = generate_preview_pdf_bytes(data, tex, block_order=order)
                        if rb: st.session_state.resume_preview_bytes = rb
                        cb = generate_cover_letter_pdf_bytes(data)
                        if cb: st.session_state.cover_letter_preview_bytes = cb
                        st.toast("Ready!")
        with r:
            st.subheader("📄 Preview")
            if st.session_state.resume_preview_bytes:
                choice = st.radio("Display", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed")
                target = st.session_state.resume_preview_bytes if choice == "Resume" else st.session_state.cover_letter_preview_bytes
                render_pdf_js(target)
            else: st.info("Click 'Generate PDF' to preview.")
    else: st.warning("Optimize first.")

with tab5:
    if st.session_state.logged_in: render_interview_progress(db, st.session_state.user_email); render_dashboard(db, st.session_state.user_email)
    else: st.warning("Login first.")
