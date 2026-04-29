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

# 🚀 1. 全域初始化 (最優先)
db = init_firebase()

# ---------------------------------------------------------
# AI Prompt Builder
# ---------------------------------------------------------
def build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, resume_data):
    ats_block = '"keyword_analysis": {"jd_keywords": [], "original_hits": [], "optimized_hits": [], "newly_added": [], "missing_keywords": []},' if enable_ats else ""
    visa_instr = "- Step 1: Check for visa sponsorship restrictions in the JD." if check_visa else ""
    return f"""Optimize resume for JD. Return ONLY JSON.
[COMMANDS]: {custom_prompt}
[RULES]: 1. Return ONLY valid JSON. 2. {visa_instr}
[Target JD]: {jd_text}
[Original Resume]: {json.dumps(resume_data, ensure_ascii=False)}
[FORMAT]: {{ "visa_blocked": false, "reason": "", "changelog": "", {ats_block} "optimized_resume": {{...}} }}"""

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
    st.session_state.custom_prompt = "Overhaul focusing on quantifiable metrics and high-ownership action verbs."
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None
if "resume_dl_data" not in st.session_state: st.session_state.resume_dl_data = None
if "cl_dl_data" not in st.session_state: st.session_state.cl_dl_data = None

# ---------------------------------------------------------
# AI 核心邏輯 (使用 Gemini 2.5 flash)
# ---------------------------------------------------------
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key: return False, "Missing API Key.", None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        response = model.generate_content(["Parse PDF to JSON. Return ONLY JSON.", pdf_part])
        raw = response.text.strip()
        if "```" in raw: raw = raw.split("```")[1].replace("json", "").strip()
        return True, "Done", json.loads(raw)
    except Exception as e: return False, str(e), None

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key")
        if not api_key: return False, "Missing API Key."
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        response = model.generate_content(prompt)
        raw = response.text.strip()
        if "```" in raw: raw = raw.split("```")[1].replace("json", "").strip()
        res = json.loads(raw)
        
        # 📂 儲存 ATS 與優化結果到外部 JSON (恢復使用者要求的存入外部 JSON 功能)
        with open("ats_analysis.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=4)
            
        st.session_state.optimized_resume_data = res.get("optimized_resume")
        st.session_state.changelog = res.get("changelog", "")
        st.session_state.opt_editor_key += 1
        if enable_ats and "keyword_analysis" in res:
            kw = res["keyword_analysis"]
            tot = max(1, len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", [])))
            st.session_state.ats_metrics = { "total": tot, "original_count": len(kw.get("original_hits", [])), "optimized_count": len(kw.get("optimized_hits", [])), "original_pct": int((len(kw.get("original_hits", []))/tot)*100), "optimized_pct": int((len(kw.get("optimized_hits", []))/tot)*100), "optimized_hits": kw.get("optimized_hits", []), "newly_added": kw.get("newly_added", []), "missing_keywords": kw.get("missing_keywords", []) }
        return True, "Done"
    except Exception as e: return False, str(e)

# ---------------------------------------------------------
# PDF 渲染
# ---------------------------------------------------------
def render_pdf_js(pdf_bytes):
    if not pdf_bytes: return
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_js_html = f"""<!DOCTYPE html><html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script><style>body{{margin:0;background:#0f172a;display:flex;flex-direction:column;align-items:center;padding:20px;}} canvas{{margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.5);border-radius:8px;max-width:95%;}}</style></head><body><div id="p"></div><script>pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';var b=window.atob('{base64_pdf}');var bytes=new Uint8Array(b.length);for(var i=0;i<b.length;i++)bytes[i]=b.charCodeAt(i);pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{for(var i=1;i<=pdf.numPages;i++)pdf.getPage(i).then(function(page){{var v=page.getViewport({{scale:1.5}});var c=document.createElement('canvas');c.height=v.height;c.width=v.width;document.getElementById('p').appendChild(c);page.render({{canvasContext:c.getContext('2d'),viewport:v}});}});}});</script></body></html>"""
    components.html(pdf_js_html, height=800, scrolling=True)

def generate_preview_pdf_bytes(data, template_name, block_order):
    try:
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(template_name, td)
            tp = os.path.join(td, template_name)
            with open(tp, "r", encoding="utf-8") as f: c = f.read()
            if block_order and "BLOCKS_PLACEHOLDER" in c:
                bs = ""
                for b in block_order:
                    if b == "Summary": bs += "\\directlua{printSummary()}\n"
                    elif b == "Experience": bs += "\\section{WORK EXPERIENCE}\n\\directlua{printExperience()}\n"
                    elif b == "Education": bs += "\\section{EDUCATION}\n\\directlua{printEducation()}\n"
                    elif b == "Projects & Patents": bs += "\\directlua{printProjectsAndPatents()}\n"
                    elif b == "Skills": bs += "\\section{SKILLS}\n\\directlua{printSkills()}\n"
                c = c.replace("BLOCKS_PLACEHOLDER", bs)
                with open(tp, "w", encoding="utf-8") as f: f.write(c)
            with open(os.path.join(td, "ml_resume.json"), "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
            subprocess.run(['lualatex', '-interaction=nonstopmode', template_name], cwd=td, capture_output=True)
            op = tp.replace(".tex", ".pdf")
            if os.path.exists(op): return open(op, "rb").read()
    except: return None

def generate_cover_letter_pdf_bytes(data):
    try:
        # 獲取內容與標頭資訊 (由使用者要求恢復專業版面)
        txt = data.get('cover_letter') or data.get('coverLetter') or data.get('Cover Letter', '')
        if not txt: return None
        
        heading = data.get('heading', {})
        name = heading.get('name', 'Your Name')
        email = heading.get('email', '')
        phone = heading.get('phone', '')
        linkedin = heading.get('linkedin', '')
        website = heading.get('website', '')

        # 使用自定義 Jinja2 環境，避免與 LaTeX 的 {} 衝突 (由使用者回報錯誤修復)
        latex_jinja_env = jinja2.Environment(
            block_start_string='<%-',
            block_end_string='%>',
            variable_start_string='<<',
            variable_end_string='>>',
            comment_start_string='<#',
            comment_end_string='#>',
            line_statement_prefix='%%',
            line_comment_prefix='%#',
            trim_blocks=True,
            autoescape=False,
            loader=jinja2.FileSystemLoader(os.path.abspath('.'))
        )
        template = latex_jinja_env.get_template('cover_letter.tex')
        
        # 準備資料
        template_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "linkedin": linkedin,
            "website": website,
            "body": txt.replace("\n", "\n\n").replace('**', '')
        }
        
        rendered_tex = template.render(template_data)

        with tempfile.TemporaryDirectory() as td:
            tex_path = os.path.join(td, "c.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(rendered_tex)
            
            subprocess.run(['lualatex', '-interaction=nonstopmode', 'c.tex'], cwd=td, capture_output=True)
            pdf_path = os.path.join(td, "c.pdf")
            if os.path.exists(pdf_path):
                return open(pdf_path, "rb").read()
    except Exception as e:
        st.error(f"Cover Letter generation error: {e}")
        return None

def get_glass_overlay_html(message, animal):
    return f"""
    <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.5);backdrop-filter:blur(4px);z-index:9999;display:flex;justify-content:center;align-items:center;font-family:sans-serif;">
        <div style="background:rgba(30, 41, 59, 0.95); border:2px solid #6366f1; padding:40px 60px; border-radius:24px; text-align:center; box-shadow:0 25px 50px -12px rgba(0,0,0,0.5); max-width:450px;">
            <div style="font-size:100px; margin-bottom:20px; animation: bounce 2s infinite ease-in-out; display:inline-block;">{animal}</div>
            <h3 style="color:white; margin:0; font-weight:600; letter-spacing:0.5px;">{message}</h3>
            <div style="margin-top:15px; color:#94a3b8; font-size:14px;">Please hold on while AI works its magic...</div>
        </div>
    </div>
    <style>
        @keyframes bounce {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-30px); }}
        }}
    </style>
    """

# ---------------------------------------------------------
# UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume", page_icon="🚀", layout="wide")

# 🔔 處理 Rerun 後的通知 (由使用者要求)
if "pending_toast" in st.session_state:
    st.toast(st.session_state.pending_toast)
    del st.session_state.pending_toast

# 🎨 修正後的 CSS：避免影響圖示
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* 僅對標題與文字生效，不影響全局圖示 */
    h1, h2, h3, p, label, .stMarkdown { font-family: 'Inter', sans-serif !important; }
    
    div[data-testid="stVerticalBlock"] > div[style*="border"] {
        background-color: #ffffff05; border: 1px solid rgba(255, 255, 255, 0.1) !important; border-radius: 12px !important; padding: 1.5rem !important;
    }

    .stButton > button { border-radius: 8px !important; height: 44px !important; font-weight: 500 !important; }
    .stButton > button[kind="primary"] { background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important; border: none !important; color: white !important; }

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e293b; border-radius: 8px 8px 0px 0px; padding: 10px 20px; color: #94a3b8; border: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #334155 !important; color: white !important; border-bottom: 2px solid #6366f1 !important;
    }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🚀 AI Resume Gen")
    if st.session_state.logged_in:
        st.success(f"**User:** `{st.session_state.user_email}`")
        if st.button("Push to Cloud", use_container_width=True): 
            # 確保獲取 UI 上的最新資料 (由使用者強烈要求修復)
            # 1. 獲取 Prompt (優先使用 Target 頁籤的 cp_v2)
            current_prompt = st.session_state.get("cp_v2", st.session_state.custom_prompt)
            
            # 2. 獲取 Resume JSON (從 Ace 編輯器的 Session State Key 獲取)
            ace_key = f"base_ed_{st.session_state.base_editor_key}"
            current_resume = st.session_state.resume_data
            if ace_key in st.session_state:
                try:
                    # Ace 編輯器會將當前內容存入 session_state[key]
                    current_resume = json.loads(st.session_state[ace_key])
                    st.session_state.resume_data = current_resume # 同步回 session_state
                except Exception as e:
                    st.warning(f"Note: Using last saved JSON because of format error: {e}")
            
            st.session_state.custom_prompt = current_prompt # 同步回 session_state
            
            ok, msg = save_user_profile(db, st.session_state.user_email, current_resume, current_prompt, st.session_state.api_key)
            if ok: st.toast("✅ Profile pushed to cloud!")
            else: st.error(msg)
            
        if st.button("Pull from Cloud", use_container_width=True):
            r, pr, k = load_user_profile(db, st.session_state.user_email)
            if r: 
                st.session_state.resume_data = r
                st.session_state.custom_prompt = pr
                st.session_state.cp_v2 = pr
                st.session_state.api_key = k
                st.session_state.base_editor_key += 1
                st.session_state.pending_toast = "✅ Profile pulled from cloud!" # Rerun 通知
                st.rerun()
        if st.button("Logout", use_container_width=True): st.session_state.logged_in = False; st.rerun()
    else:
        with st.form("l"):
            e = st.text_input("Email"); p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if authenticate_user(db, e, p): 
                    st.session_state.logged_in = True; st.session_state.user_email = e
                    r, pr, k = load_user_profile(db, e)
                    if r: 
                        st.session_state.resume_data = r
                        st.session_state.custom_prompt = pr
                        st.session_state.cp_v2 = pr # 同步更新 Strategy 欄位
                        st.session_state.api_key = k
                        st.session_state.base_editor_key += 1
                    st.rerun()
    st.markdown("---")
    st.text_input("🔑 API Key", type="password", key="api_key")
    st.selectbox("🧠 Model", ["gemini-2.5-flash", "gemini-2.5-flash"], key="ai_model")
    st.selectbox("Animal", ["🦦 Otter", "🐕 Dog", "🦖 T-Rex"], key="animal_emoji_select")
    st.session_state.animal_emoji = st.session_state.animal_emoji_select.split(" ")[0]

# --- Stepper ---
s1, s2, s3, s4 = len(st.session_state.resume_data.get("experience", [])) > 0, len(st.session_state.get("jd_v2", "")) > 50, st.session_state.optimized_resume_data is not None, st.session_state.resume_preview_bytes is not None
steps = [{"l": "Source", "d": s1}, {"l": "Target", "d": s2}, {"l": "Analysis", "d": s3}, {"l": "Review", "d": s4}, {"l": "Tracker", "d": st.session_state.logged_in}]
cols = st.columns(5)
for i, s in enumerate(steps):
    with cols[i]:
        c = "#10b981" if s["d"] else "#6366f1"
        st.markdown(f"<div style='text-align:center;padding:10px;border-radius:10px;background:{c}15;border:1px solid {c}40;color:{c};font-weight:bold;'>{'✅' if s['d'] else '🔵'} {s['l']}</div>", unsafe_allow_html=True)

st.markdown("---")
t1, t2, t3, t4, t5 = st.tabs([" 📁 Source ", " 🎯 Target ", " 📊 ATS ", " 📝 Review ", " 📈 Tracker "])

with t1:
    with st.container(border=True):
        st.subheader("📥 Quick Import")
        up = st.file_uploader("Upload PDF", type=["pdf"], key="up1", label_visibility="collapsed")
        if st.button("✨ Extract Data", type="primary", use_container_width=True) and up:
            loading = st.empty(); loading.markdown(get_glass_overlay_html("Extracting...", st.session_state.animal_emoji), unsafe_allow_html=True)
            ok, msg, data = parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key)
            loading.empty()
            if ok: 
                st.session_state.resume_data = data
                st.session_state.base_editor_key += 1
                st.session_state.pending_toast = "✅ Data extracted successfully!"
                st.rerun()
            else: st.error(msg)
    
    st.markdown("#### 📝 Profile Editor")
    edit = st_ace.st_ace(value=json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False), language="json", theme="dracula", height=500, key=f"base_ed_{st.session_state.base_editor_key}")
    if st.button("💾 Save Base Changes", use_container_width=True): 
        st.session_state.resume_data = json.loads(edit)
        st.toast("💾 Base Profile Saved!")

with t2:
    with st.container(border=True):
        st.subheader("🎯 Job Details")
        jd = st.text_area("JD Content", height=300, key="jd_v2")
        st.text_area("Strategy", value=st.session_state.custom_prompt, key="cp_v2", height=150)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Optimize Resume", type="primary", use_container_width=True):
                if jd:
                    l = st.empty(); l.markdown(get_glass_overlay_html("Gemini Crafting...", st.session_state.animal_emoji), unsafe_allow_html=True)
                    ok, rep = ai_optimize_and_update(jd, st.session_state.cp_v2, True, True)
                    l.empty()
                    if ok: 
                        st.session_state.pending_toast = "✅ Resume Optimized Successfully!"
                        st.rerun()
                    else: st.error(rep)
        with c2:
            p_text = build_optimization_prompt(jd if jd else "JD", st.session_state.cp_v2, True, True, st.session_state.resume_data)
            b64 = base64.b64encode(p_text.encode('utf-8')).decode('utf-8')
            components.html(f"""
            <body style="margin:0; padding:0;">
                <button id="copyPromptBtn" onclick="copyPrompt()" style="
                    width:100%; height:44px; border-radius:8px; 
                    background:#1e293b; color:white; border:1px solid rgba(255,255,255,0.2); 
                    cursor:pointer; font-weight:500; font-family:sans-serif; 
                    display:flex; align-items:center; justify-content:center; transition:all 0.2s;">
                    📋 Copy Prompt
                </button>
            </body>
            <script>
            function copyPrompt() {{
                try {{
                    const b64 = "{b64}";
                    const text = decodeURIComponent(escape(window.atob(b64)));
                    const textArea = document.createElement("textarea");
                    textArea.value = text;
                    textArea.style.position = "fixed"; textArea.style.left = "-9999px"; textArea.style.top = "0";
                    document.body.appendChild(textArea);
                    textArea.focus(); textArea.select();
                    const successful = document.execCommand('copy');
                    document.body.removeChild(textArea);
                    if (successful) {{
                        const btn = document.getElementById('copyPromptBtn');
                        btn.innerText = '✅ Copied';
                        btn.style.borderColor = '#059669'; btn.style.color = '#34d399';
                        setTimeout(() => {{ 
                            btn.innerText = '📋 Copy Prompt'; 
                            btn.style.borderColor = 'rgba(255,255,255,0.2)'; btn.style.color = 'white';
                        }}, 2000);
                    }}
                }} catch (err) {{ console.error(err); }}
            }}
            </script>
            """, height=45)

with t3:
    st.header("📊 ATS Analysis")
    
    # 📥 手動匯入外部推論結果 (由使用者要求)
    with st.expander("📥 Manual Result Import (Paste JSON)"):
        manual_json = st.text_area("Paste the externally inferred JSON here:", height=200, key="manual_ats_json")
        if st.button("Apply Manual Result", use_container_width=True):
            try:
                res = json.loads(manual_json)
                st.session_state.optimized_resume_data = res.get("optimized_resume")
                st.session_state.changelog = res.get("changelog", "")
                if "keyword_analysis" in res:
                    kw = res["keyword_analysis"]
                    tot = max(1, len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", [])))
                    st.session_state.ats_metrics = { "total": tot, "original_count": len(kw.get("original_hits", [])), "optimized_count": len(kw.get("optimized_hits", [])), "original_pct": int((len(kw.get("original_hits", []))/tot)*100), "optimized_pct": int((len(kw.get("optimized_hits", []))/tot)*100), "optimized_hits": kw.get("optimized_hits", []), "newly_added": kw.get("newly_added", []), "missing_keywords": kw.get("missing_keywords", []) }
                    st.success("Manual result applied!")
                    st.rerun()
                else:
                    st.error("JSON structure missing 'keyword_analysis'.")
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

    if st.session_state.optimized_resume_data:
        # 📝 修改日誌 (移至最上方由使用者要求)
        if st.session_state.changelog:
            st.info(f"**Changelog:** {st.session_state.changelog}")

        m = st.session_state.ats_metrics
        if m:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Match Rate", f"{m['optimized_pct']}%")
            mc2.metric("Keywords", f"{m['optimized_count']}/{m['total']}")
            mc3.metric("New Added", len(m['newly_added']))
            st.progress(m['optimized_pct']/100)
            k1, k2 = st.columns(2)
            with k1:
                st.success("✅ Hit Keywords")
                for k in m.get('optimized_hits', []): st.markdown(f"- `{k}`" + (" 🌟" if k in m.get('newly_added', []) else ""))
            with k2:
                st.error("❌ Missing")
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
        cl1, cl2 = st.columns([4, 6])
        with cl1:
            with st.container(border=True):
                st.subheader("🛠️ Export Settings")
                if st.button("📝 Edit Optimized JSON", use_container_width=True): edit_opt_dialog()
                tmpl = st.selectbox("Template", ["💻 Tech", "📈 Business"], key="tm")
                order = st.multiselect("Order", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"])
                if st.button("🚀 Generate PDF", type="primary", use_container_width=True):
                    with st.spinner("Generating..."):
                        d = st.session_state.optimized_resume_data
                        rb = generate_preview_pdf_bytes(d, "main.tex" if "Tech" in tmpl else "elsa_main.tex", order)
                        if rb:
                            st.session_state.resume_preview_bytes = rb
                            c, r = d.get('target_company','Co').replace(' ','_'), d.get('target_role','Role').replace(' ','_')
                            st.session_state.resume_dl_data = {"bytes": rb, "name": f"{c}_{r}_Resume.pdf"}
                        cb = generate_cover_letter_pdf_bytes(d)
                        if cb: 
                            st.session_state.cover_letter_preview_bytes = cb
                            st.session_state.cl_dl_data = {"bytes": cb, "name": f"{c}_{r}_CL.pdf"}
                        st.toast("✅ PDF Generated Successfully!")
        with cl2:
            st.subheader("📄 Preview")
            if st.session_state.resume_preview_bytes or st.session_state.cover_letter_preview_bytes:
                ch = st.radio("Target", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed", key="tr")
                target = st.session_state.resume_preview_bytes if ch == "Resume" else st.session_state.cover_letter_preview_bytes
                dl = st.session_state.resume_dl_data if ch == "Resume" else st.session_state.cl_dl_data
                if dl:
                    sync = st.checkbox("📈 Sync to Tracker", value=True) if st.session_state.logged_in else False
                    st.download_button(f"📥 Download {dl['name']}", dl["bytes"], dl["name"], use_container_width=True, on_click=lambda: save_application(db, st.session_state.user_email, st.session_state.optimized_resume_data.get('target_company'), st.session_state.optimized_resume_data, st.session_state.get('jd_v2')) if sync and ch=="Resume" else None)
                if target: render_pdf_js(target)
                else: st.info(f"The {ch} data is missing.")
            else: st.info("Click 'Generate PDF' to see preview.")
    else: st.warning("Optimize first.")

with t5:
    if st.session_state.logged_in: render_interview_progress(db, st.session_state.user_email); render_dashboard(db, st.session_state.user_email)
    else: st.warning("Login first.")
