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
from firebase_dashboard import init_firebase, authenticate_user, register_user, render_dashboard, save_application, render_interview_progress, save_user_profile, load_user_profile, predict_interview_questions, analyze_skill_gap

st.set_page_config(page_title="AI Resume", page_icon="AI", layout="wide")

def get_db():
    return init_firebase()

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
[FORMAT]: {{ 
  "visa_blocked": false, 
  "reason": "", 
  "changelog": "", 
  {ats_block} 
  "optimized_resume": {{
    "target_company": "Extract target company name from JD",
    "target_role": "Extract target job title from JD",
    "cover_letter": "Generate a professional 3-paragraph cover letter tailored to this JD",
    "heading": {{ "name": "...", "email": "...", "phone": "...", "website": "...", "linkedin": "..." }},
    "summary": "...",
    "education": [],
    "experience": [],
    "projects": [],
    "patents": [],
    "skills": {{ "set1": {{ "title": "...", "items": [] }} }}
  }} 
}}"""

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
    st.session_state.custom_prompt = """You are an elite Career Strategist and ATS Architect. Overhaul the resume and cover letter based on the JD:
1. **Resume (STAR Method)**: Rewrite every experience bullet point using the STAR method (Situation, Task, Action, Result). Keep them concise (1-2 lines) but highly impactful. Every point MUST include a quantifiable metric (%, $, time saved, or scale).
2. **Aggressive Action Verbs**: Use high-ownership verbs like 'Spearheaded', 'Engineered', 'Orchestrated', 'Pioneered'.
3. **ATS Semantic Mapping**: Naturally inject keywords from the JD. Perform 'Horizontal Shifts' (e.g., if they ask for GCP and you have AWS, write 'AWS/GCP').
4. **Cover Letter**: Generate a compelling 3-paragraph letter. 
   - Para 1: Strong hook and immediate value proposition.
   - Para 2: Concrete evidence of 2-3 skills matching the JD's 'Required' section.
   - Para 3: Passion for the company's mission and a clear call to action.
5. **Formatting**: Return ONLY valid JSON. Do NOT use markdown like '**' inside the strings."""
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_email" not in st.session_state: st.session_state.user_email = ""
if "resume_preview_bytes" not in st.session_state: st.session_state.resume_preview_bytes = None
if "cover_letter_preview_bytes" not in st.session_state: st.session_state.cover_letter_preview_bytes = None
if "resume_dl_data" not in st.session_state: st.session_state.resume_dl_data = None
if "cl_dl_data" not in st.session_state: st.session_state.cl_dl_data = None
if "ats_analysis" not in st.session_state: st.session_state.ats_analysis = None
if "optimized_source_snapshot" not in st.session_state: st.session_state.optimized_source_snapshot = None

def clear_pdf_outputs():
    st.session_state.resume_preview_bytes = None
    st.session_state.cover_letter_preview_bytes = None
    st.session_state.resume_dl_data = None
    st.session_state.cl_dl_data = None

def clear_generated_outputs():
    st.session_state.optimized_resume_data = None
    st.session_state.ats_metrics = None
    st.session_state.ats_analysis = None
    st.session_state.changelog = ""
    st.session_state.optimized_source_snapshot = None
    clear_pdf_outputs()

def resume_snapshot(data):
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)

def optimized_result_is_stale():
    snapshot = st.session_state.get("optimized_source_snapshot")
    return snapshot is not None and resume_snapshot(st.session_state.resume_data) != snapshot

def sync_base_editor_to_state(show_error=True):
    ace_key = f"base_ed_{st.session_state.base_editor_key}"
    raw_resume_json = st.session_state.get(ace_key)
    if raw_resume_json is None:
        return True
    try:
        st.session_state.resume_data = json.loads(raw_resume_json)
        return True
    except json.JSONDecodeError as e:
        if show_error:
            st.error(f"Source JSON is invalid: {e}")
        return False

def safe_filename_part(value, fallback):
    text = str(value or fallback).strip().replace(" ", "_")
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    return cleaned.strip("_") or fallback

def render_json_editor(value, key, height=500):
    return st.text_area(
        "JSON Editor",
        value=value,
        key=key,
        height=height,
        label_visibility="collapsed",
    )

def sync_application_to_tracker():
    tracker_db = get_db()
    if tracker_db is None:
        st.error("Tracker is unavailable until Firebase secrets are configured.")
        return
    save_application(
        tracker_db,
        st.session_state.user_email,
        st.session_state.optimized_resume_data.get('target_company'),
        st.session_state.optimized_resume_data,
        st.session_state.get('jd_v2')
    )

# ---------------------------------------------------------
# AI 核心邏輯 (強制鎖定使用 gemini-1.5-flash)
# ---------------------------------------------------------
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key: return False, "Missing API Key.", None
    try:
        genai.configure(api_key=api_key)
        # 使用穩定版本 gemini-1.5-flash
        model_name = "gemini-1.5-flash"
        model = genai.GenerativeModel(model_name)
        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        
        prompt = """
        Extract all information from this resume PDF into the EXACT JSON structure below. 
        Maintain high fidelity to the original content but format it strictly.
        
        ### EXPECTED JSON STRUCTURE:
        {
          "heading": {
            "name": "Full Name",
            "email": "Email Address",
            "phone": "Phone Number",
            "website": "Personal Website/Portfolio URL",
            "linkedin": "LinkedIn Profile URL"
          },
          "summary": "A concise professional summary",
          "education": [
            {
              "school": "University Name",
              "time_period": "e.g., Aug 2018 - May 2022",
              "degree": "e.g., Bachelor of Science in Computer Science",
              "school_location": "City, State/Country"
            }
          ],
          "experience": [
            {
              "company": "Company Name",
              "role": "Job Title",
              "time_duration": "e.g., June 2022 - Present",
              "company_location": "City, State/Country",
              "details": [
                { "description": "Bullet point of achievement/responsibility" }
              ]
            }
          ],
          "projects": [
            {
              "name": "Project Name",
              "time": "Date/Duration",
              "description": "Brief description of your role and the project outcome"
            }
          ],
          "patents": [
            {
              "name": "Patent Title",
              "time": "Date",
              "description": "Brief description"
            }
          ],
          "skills": {
            "set1": { "title": "Languages & Frameworks", "items": ["Python", "Java", ...] },
            "set2": { "title": "Tools & Technologies", "items": ["AWS", "Docker", ...] },
            "set3": { "title": "Other Skills", "items": ["Agile", "Leadership", ...] }
          }
        }
        
        ### RULES:
        1. Return ONLY the JSON object.
        2. Ensure "experience" details are objects with a "description" key.
        3. If a field is missing in the PDF, use an empty string or empty list/object as appropriate.
        """
        
        # 使用 JSON 模式確保輸出穩定性，並降低溫度減少幻覺
        response = model.generate_content(
            [prompt, pdf_part], 
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        )
        return True, "Done", json.loads(response.text)
    except Exception as e: return False, str(e), None

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key")
        if not api_key: return False, "Missing API Key."
        genai.configure(api_key=api_key)
        
        # 使用穩定版本 gemini-1.5-flash
        model_name = "gemini-1.5-flash"
        model = genai.GenerativeModel(model_name)
        prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        
        # 使用 JSON 模式確保輸出穩定性，並降低溫度減少幻覺
        response = model.generate_content(
            prompt, 
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        )
        res = json.loads(response.text)
        st.session_state.ats_analysis = res
            
        st.session_state.optimized_resume_data = res.get("optimized_resume")
        st.session_state.changelog = res.get("changelog", "")
        st.session_state.optimized_source_snapshot = resume_snapshot(st.session_state.resume_data)
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
    # 效能優化版 PDF 檢視器：移除陰影與圓角效果
    pdf_js_html = f"""<!DOCTYPE html><html><head><script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script><style>body{{margin:0;background:#0f172a;display:flex;flex-direction:column;align-items:center;padding:10px;}} canvas{{margin-bottom:10px;border:1px solid #334155;max-width:98%;}}</style></head><body><div id="p"></div><script>pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';var b=window.atob('{base64_pdf}');var bytes=new Uint8Array(b.length);for(var i=0;i<b.length;i++)bytes[i]=b.charCodeAt(i);pdfjsLib.getDocument({{data:bytes}}).promise.then(function(pdf){{for(var i=1;i<=pdf.numPages;i++)pdf.getPage(i).then(function(page){{var v=page.getViewport({{scale:1.3}});var c=document.createElement('canvas');c.height=v.height;c.width=v.width;document.getElementById('p').appendChild(c);page.render({{canvasContext:c.getContext('2d'),viewport:v}});}});}});</script></body></html>"""
    components.html(pdf_js_html, height=800, scrolling=True)

def escape_latex_chars(obj):
    """Recursively escape LaTeX special characters to prevent compilation errors."""
    if isinstance(obj, str):
        latex_escape_map = {
            '\\': r'\textbackslash{}',
            '$': r'\$',
            '%': r'\%',
            '&': r'\&',
            '＆': r'\&',
            '_': r'\_',
            '#': r'\#',
            '{': r'\{',
            '}': r'\}',
            '~': r'\textasciitilde{}',
            '^': r'\textasciicircum{}',
        }
        return "".join(latex_escape_map.get(ch, ch) for ch in obj)
    elif isinstance(obj, list):
        return [escape_latex_chars(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: escape_latex_chars(v) for k, v in obj.items()}
    return obj

def generate_preview_pdf_bytes(data, template_name, block_order):
    try:
        escaped_data = escape_latex_chars(data)
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
            with open(os.path.join(td, "ml_resume.json"), "w", encoding="utf-8") as f: json.dump(escaped_data, f, ensure_ascii=False)
            result = subprocess.run(['lualatex', '-interaction=nonstopmode', template_name], cwd=td, capture_output=True, text=True)
            if result.returncode != 0:
                st.error("Resume PDF generation failed. Check the LaTeX log below.")
                st.code((result.stdout or result.stderr or "")[-4000:], language="text")
                return None
            op = tp.replace(".tex", ".pdf")
            if os.path.exists(op): return open(op, "rb").read()
            st.error("Resume PDF generation finished without producing a PDF.")
    except Exception as e:
        st.error(f"Resume PDF generation error: {e}")
    return None

def generate_cover_letter_pdf_bytes(data):
    try:
        # 獲取內容與標頭資訊 (由使用者要求恢復專業版面)
        txt = data.get('cover_letter') or data.get('coverLetter') or data.get('Cover Letter', '')
        if not txt: return None
        
        escaped_data = escape_latex_chars(data)
        escaped_txt = escape_latex_chars(txt)
        
        heading = escaped_data.get('heading', {})
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
            "body": escaped_txt.replace("\n", "\n\n").replace('**', '')
        }
        
        rendered_tex = template.render(template_data)

        with tempfile.TemporaryDirectory() as td:
            tex_path = os.path.join(td, "c.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(rendered_tex)
            
            result = subprocess.run(['lualatex', '-interaction=nonstopmode', 'c.tex'], cwd=td, capture_output=True, text=True)
            if result.returncode != 0:
                st.error("Cover Letter PDF generation failed. Check the LaTeX log below.")
                st.code((result.stdout or result.stderr or "")[-4000:], language="text")
                return None
            pdf_path = os.path.join(td, "c.pdf")
            if os.path.exists(pdf_path):
                return open(pdf_path, "rb").read()
    except Exception as e:
        st.error(f"Cover Letter generation error: {e}")
        return None

# 🔔 處理 Rerun 後的通知
if "pending_toast" in st.session_state:
    st.toast(st.session_state.pending_toast)
    del st.session_state.pending_toast

# Lightweight visual system: native CSS only, no UI/animation framework.
st.markdown("""
<style>
    :root {
        --bg: #f8fafc;
        --surface: #ffffff;
        --surface-soft: #f1f5f9;
        --border: #e2e8f0;
        --border-strong: #bfdbfe;
        --text: #111827;
        --muted: #64748b;
        --brand: #2563eb;
        --brand-dark: #1d4ed8;
        --success: #059669;
        --warning: #d97706;
        --danger: #dc2626;
        --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.06);
        --shadow-md: 0 10px 24px rgba(15, 23, 42, 0.08);
        --radius: 8px;
        --ease: 180ms ease-in-out;
    }

    html, body, [data-testid="stAppViewContainer"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: var(--bg);
        color: var(--text);
    }

    .main .block-container {
        padding-top: 3.25rem;
        padding-bottom: 3rem;
        max-width: 1320px;
    }

    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
        font-size: 1.1rem;
        line-height: 1.3;
        margin-bottom: 0.35rem;
    }

    h1, h2, h3, h4 {
        color: var(--text);
        letter-spacing: 0;
    }

    p, label, [data-testid="stCaptionContainer"] {
        color: var(--muted);
    }

    div[data-testid="stVerticalBlock"] > div[style*="border"] {
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        padding: 1.2rem !important;
        margin-bottom: 1rem !important;
        box-shadow: var(--shadow-sm);
    }

    .stButton > button,
    .stDownloadButton > button,
    button[data-baseweb="tab"],
    div[data-baseweb="select"] > div,
    input,
    textarea {
        transition: background-color var(--ease), border-color var(--ease), box-shadow var(--ease), color var(--ease), transform var(--ease) !important;
    }

    .stButton > button,
    .stDownloadButton > button {
        border-radius: var(--radius) !important;
        min-height: 42px !important;
        font-weight: 650 !important;
        border: 1px solid var(--border) !important;
        background: var(--surface) !important;
        color: var(--text) !important;
        box-shadow: var(--shadow-sm);
    }

    .stButton > button p,
    .stDownloadButton > button p {
        color: inherit !important;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        border-color: var(--border-strong) !important;
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }

    .stButton > button[kind="primary"] { 
        background: var(--brand) !important;
        border-color: var(--brand) !important;
        color: #ffffff !important;
    }

    .stButton > button[kind="primary"]:hover {
        background: var(--brand-dark) !important;
        border-color: var(--brand-dark) !important;
    }

    .stButton > button:focus-visible,
    .stDownloadButton > button:focus-visible,
    input:focus,
    textarea:focus,
    [data-baseweb="select"] div:focus,
    [data-baseweb="radio"] input:focus-visible + div {
        outline: none !important;
        border-color: var(--brand) !important;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18) !important;
    }

    input,
    textarea,
    div[data-baseweb="select"] > div {
        border-radius: var(--radius) !important;
        border-color: var(--border) !important;
        background: var(--surface) !important;
    }

    textarea {
        line-height: 1.55 !important;
    }

    hr {
        border-color: var(--border);
        margin: 1.1rem 0;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        padding: 4px;
        border-radius: var(--radius);
        background: var(--surface-soft);
        border: 1px solid var(--border);
    }

    .stTabs [data-baseweb="tab"] {
        height: 40px;
        border-radius: 6px;
        padding: 8px 16px;
        color: var(--muted);
        font-weight: 650;
        border: 1px solid transparent;
    }

    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(255, 255, 255, 0.72);
        color: var(--text);
    }

    .stTabs [aria-selected="true"] {
        background: var(--surface) !important;
        color: var(--brand) !important;
        border-color: var(--border) !important;
        box-shadow: var(--shadow-sm);
    }

    [data-testid="stAlert"] {
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
    }

    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 0.85rem 1rem;
        box-shadow: var(--shadow-sm);
    }

    .step-pill {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 40px;
        padding: 0 12px;
        border: 1px solid var(--border);
        border-radius: var(--radius);
        background: var(--surface);
        color: var(--muted);
        font-size: 0.9rem;
        font-weight: 650;
        box-shadow: var(--shadow-sm);
        white-space: nowrap;
    }

    .step-pill.done {
        border-color: rgba(5, 150, 105, 0.25);
        background: rgba(5, 150, 105, 0.08);
        color: var(--success);
    }

    .lite-loader {
        width: 18px;
        height: 18px;
        border: 2px solid #bfdbfe;
        border-top-color: var(--brand);
        border-radius: 50%;
        animation: lite-spin 700ms linear infinite;
    }

    @keyframes lite-spin {
        to { transform: rotate(360deg); }
    }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### AI Resume Studio")
    st.caption("Resume, cover letter, and application tracking.")
    if st.session_state.logged_in:
        st.success(f"**User:** `{st.session_state.user_email}`")
        if st.button("Push to Cloud", use_container_width=True): 
            if sync_base_editor_to_state():
                current_prompt = st.session_state.get("cp_v2", st.session_state.custom_prompt)
                st.session_state.custom_prompt = current_prompt
                cloud_db = get_db()
                if cloud_db is not None:
                    ok, msg = save_user_profile(
                        cloud_db,
                        st.session_state.user_email,
                        st.session_state.resume_data,
                        current_prompt,
                        st.session_state.get("api_key", ""),
                    )
                    if ok: st.toast("Profile pushed.")
                    else: st.error(msg)
            
        if st.button("Pull from Cloud", use_container_width=True):
            cloud_db = get_db()
            if cloud_db is not None:
                r, pr, k = load_user_profile(cloud_db, st.session_state.user_email)
                if r is not None or pr is not None or k is not None:
                    if r is not None:
                        st.session_state.resume_data = r
                        st.session_state.base_editor_key += 1
                        clear_generated_outputs()
                    if pr is not None:
                        st.session_state.custom_prompt = pr
                        st.session_state.cp_v2 = pr
                    if k is not None:
                        st.session_state.api_key = k
                    st.session_state.pending_toast = "Profile pulled."
                    st.rerun()
        if st.button("Logout", use_container_width=True): st.session_state.logged_in = False; st.rerun()
    else:
        auth_mode = st.radio("Auth Mode", ["Login", "Register"], horizontal=True, label_visibility="collapsed")
        with st.form("auth_form"):
            e = st.text_input("Email")
            p = st.text_input("Password", type="password")
            if auth_mode == "Login":
                if st.form_submit_button("Login", type="primary", use_container_width=True):
                    email = e.strip()
                    auth_db = get_db()
                    if auth_db is not None:
                        ok, msg = authenticate_user(auth_db, email, p)
                        if ok:
                            st.session_state.logged_in = True; st.session_state.user_email = email
                            r, pr, k = load_user_profile(auth_db, email)
                            if r is not None:
                                st.session_state.resume_data = r
                                st.session_state.base_editor_key += 1
                                clear_generated_outputs()
                            if pr is not None:
                                st.session_state.custom_prompt = pr
                                st.session_state.cp_v2 = pr
                            if k is not None:
                                st.session_state.api_key = k
                            st.rerun()
                        else:
                            st.error(msg)
            else:
                if st.form_submit_button("Create Account", type="primary", use_container_width=True):
                    auth_db = get_db()
                    if auth_db is not None:
                        ok, msg = register_user(auth_db, e.strip(), p)
                        if ok: st.success(msg)
                        else: st.error(msg)
    st.markdown("---")
    st.markdown("**API Settings**")
    st.caption("[Get your free API Key from Google AI Studio](https://aistudio.google.com/app/apikey)")
    st.text_input("API Key", type="password", key="api_key")
    
    st.markdown("---")
    if st.button("Reset All Data", use_container_width=True, type="secondary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    
    st.caption("Developed by NSYSUHermit")

# --- Simplified Stepper ---
s1, s2, s3, s4 = len(st.session_state.resume_data.get("experience", [])) > 0, len(st.session_state.get("jd_v2", "")) > 50, st.session_state.optimized_resume_data is not None, st.session_state.resume_preview_bytes is not None
steps = [{"l": "Source", "d": s1}, {"l": "Target", "d": s2}, {"l": "Analysis", "d": s3}, {"l": "Review", "d": s4}, {"l": "Tracker", "d": st.session_state.logged_in}]
cols = st.columns(5)
for i, s in enumerate(steps):
    with cols[i]:
        step_class = "step-pill done" if s['d'] else "step-pill"
        st.markdown(f"<div class='{step_class}'>{s['l']}</div>", unsafe_allow_html=True)

st.markdown("---")
active_view = st.radio(
    "Workspace",
    ["Source", "Target", "ATS", "Review", "Tracker"],
    key="active_view",
    horizontal=True,
    label_visibility="collapsed",
)

if active_view == "Source":
    with st.container(border=True):
        st.subheader("Quick Import")
        up = st.file_uploader("Upload PDF", type=["pdf"], key="up1", label_visibility="collapsed")
        if st.button("Extract Resume Data", type="primary", use_container_width=True) and up:
            with st.spinner("Extracting resume data..."):
                ok, msg, data = parse_pdf_resume_to_json(up.getvalue(), st.session_state.api_key)
                if ok: 
                    st.session_state.resume_data = data
                    st.session_state.base_editor_key += 1
                    clear_generated_outputs()
                    st.session_state.pending_toast = "Data extracted."
                    st.rerun()
                else: st.error(msg)
    
    st.markdown("#### Profile Editor")
    edit = render_json_editor(json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False), key=f"base_ed_{st.session_state.base_editor_key}", height=500)
    if st.button("Save Source JSON", use_container_width=True): 
        try:
            st.session_state.resume_data = json.loads(edit)
            clear_generated_outputs()
            st.toast("Saved. Previous optimized output cleared.")
        except json.JSONDecodeError as e:
            st.error(f"Source JSON is invalid: {e}")

if active_view == "Target":
    with st.container(border=True):
        st.subheader("Job Details")
        jd = st.text_area("JD Content", height=300, key="jd_v2")
        st.text_area("Strategy", value=st.session_state.custom_prompt, key="cp_v2", height=150)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Optimize Resume", type="primary", use_container_width=True):
                if jd:
                    if sync_base_editor_to_state():
                        st.session_state.custom_prompt = st.session_state.cp_v2
                        clear_generated_outputs()
                        with st.spinner("Optimizing resume..."):
                            ok, rep = ai_optimize_and_update(jd, st.session_state.cp_v2, True, True)
                            if ok: 
                                st.session_state.pending_toast = "Optimized from current Source JSON."
                                st.rerun()
                            else: st.error(rep)
                else:
                    st.warning("Paste a job description before optimizing.")
        with c2:
            sync_base_editor_to_state(show_error=False)
            p_text = build_optimization_prompt(jd if jd else "JD", st.session_state.cp_v2, True, True, st.session_state.resume_data)
            b64 = base64.b64encode(p_text.encode('utf-8')).decode('utf-8')
            components.html(f"""
            <body style="margin:0; padding:0;">
                <button id="copyPromptBtn" onclick="copyPrompt()" style="
                    width:100%; height:42px; border-radius:8px; 
                    background:#ffffff; color:#111827; border:1px solid #e2e8f0; 
                    cursor:pointer; font-weight:650; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; 
                    display:flex; align-items:center; justify-content:center;
                    box-shadow:0 1px 2px rgba(15,23,42,0.06);
                    transition:background-color 180ms ease-in-out,border-color 180ms ease-in-out,box-shadow 180ms ease-in-out,color 180ms ease-in-out;">
                    Copy Prompt
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
                        btn.innerText = 'Copied';
                        btn.style.borderColor = '#059669'; btn.style.color = '#059669';
                        setTimeout(() => {{ 
                            btn.innerText = 'Copy Prompt'; 
                            btn.style.borderColor = '#e2e8f0'; btn.style.color = '#111827';
                        }}, 2000);
                    }}
                }} catch (err) {{ console.error(err); }}
            }}
            </script>
            """, height=44)

if active_view == "ATS":
    st.subheader("ATS Analysis")
    st.caption("See how well your resume matches the JD and identify missing keywords.")
    
    # 手動匯入外部推論結果
    with st.expander("Manual Result Import"):
        st.caption("If you ran the AI optimization elsewhere, paste the resulting JSON here to update the dashboard.")
        manual_json = st.text_area("Paste the externally inferred JSON here:", height=200, key="manual_ats_json")
        if st.button("Apply Manual Result", use_container_width=True):
            try:
                res = json.loads(manual_json)
                if "optimized_resume" not in res:
                    st.error("JSON structure missing 'optimized_resume'.")
                elif "keyword_analysis" in res:
                    clear_pdf_outputs()
                    st.session_state.ats_analysis = res
                    st.session_state.optimized_resume_data = res.get("optimized_resume")
                    st.session_state.changelog = res.get("changelog", "")
                    st.session_state.optimized_source_snapshot = resume_snapshot(st.session_state.resume_data)
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
        # 修改日誌
        if st.session_state.changelog:
            st.markdown("### Optimization Changelog")
            st.info(st.session_state.changelog)

        m = st.session_state.ats_metrics
        if m:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Match Rate", f"{m['optimized_pct']}%")
            mc2.metric("Keywords", f"{m['optimized_count']}/{m['total']}")
            mc3.metric("New Added", len(m['newly_added']))
            st.progress(m['optimized_pct']/100)
            k1, k2 = st.columns(2)
            with k1:
                st.success("Matched Keywords")
                for k in m.get('optimized_hits', []): st.markdown(f"- `{k}`" + (" (new)" if k in m.get('newly_added', []) else ""))
            with k2:
                st.error("Missing Keywords")
                for k in m.get('missing_keywords', []): st.markdown(f"- `{k}`")
        if st.session_state.changelog: st.info(st.session_state.changelog)
    else: st.info("Run optimization first.")

@st.dialog("Edit Optimized Data", width="large")
def edit_opt_dialog():
    edit = render_json_editor(json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False), key=f"opt_ed_{st.session_state.opt_editor_key}", height=500)
    if st.button("Save Changes", use_container_width=True): 
        try:
            st.session_state.optimized_resume_data = json.loads(edit)
            clear_pdf_outputs()
            st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"Optimized JSON is invalid: {e}")

if active_view == "Review":
    sync_base_editor_to_state(show_error=False)
    # 允許手動匯入已優化的 JSON (方便使用者直接複製格式)
    with st.expander("Manual Data Import"):
        st.caption("If you already have a structured resume JSON, paste it here to skip AI optimization.")
        manual_opt_json = st.text_area("Paste Optimized JSON here:", height=200, key="manual_opt_input")
        if st.button("Apply Manual Data", use_container_width=True):
            try:
                manual_data = json.loads(manual_opt_json)
                st.session_state.optimized_resume_data = manual_data
                st.session_state.ats_analysis = None
                st.session_state.ats_metrics = None
                st.session_state.changelog = ""
                st.session_state.optimized_source_snapshot = None
                clear_pdf_outputs()
                st.toast("Manual data applied.")
                st.rerun()
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

    if st.session_state.optimized_resume_data:
        if optimized_result_is_stale():
            st.warning("Source JSON has changed since the current optimized result was created. Re-run Optimize Resume before generating a new PDF.")
        cl1, cl2 = st.columns([4, 6])
        with cl1:
            with st.container(border=True):
                st.subheader("Export Settings")
                st.caption("Select your preferred template and section order, then generate the final PDFs.")
                if st.button("Edit Optimized JSON", use_container_width=True): edit_opt_dialog()
                tmpl = st.selectbox("Template", ["Tech", "Business"], key="tm")
                order = st.multiselect("Order", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=["Summary", "Experience", "Education", "Projects & Patents", "Skills"])
                if st.button("Generate PDF", type="primary", use_container_width=True):
                    if optimized_result_is_stale():
                        st.error("This optimized result is stale. Re-run Optimize Resume so the PDF uses the latest Source JSON.")
                    else:
                        with st.spinner("Generating..."):
                            d = st.session_state.optimized_resume_data
                            co = safe_filename_part(d.get('target_company'), 'Company')
                            ro = safe_filename_part(d.get('target_role'), 'Role')
                            clear_pdf_outputs()
                            rb = generate_preview_pdf_bytes(d, "main.tex" if "Tech" in tmpl else "elsa_main.tex", order)
                            if rb:
                                st.session_state.resume_preview_bytes = rb
                                # 統一檔名格式 (由使用者要求)
                                st.session_state.resume_dl_data = {"bytes": rb, "name": f"{co}_{ro}_Resume.pdf"}
                            cb = generate_cover_letter_pdf_bytes(d)
                            if cb: 
                                st.session_state.cover_letter_preview_bytes = cb
                                # 確保與履歷檔名格式一致
                                st.session_state.cl_dl_data = {"bytes": cb, "name": f"{co}_{ro}_CL.pdf"}
                            if rb or cb:
                                st.toast("PDF generated.")
                            else:
                                st.error("No PDF was generated.")
        with cl2:
            st.subheader("Preview")
            if st.session_state.resume_preview_bytes or st.session_state.cover_letter_preview_bytes:
                ch = st.radio("Target", ["Resume", "Cover Letter"], horizontal=True, label_visibility="collapsed", key="tr")
                target = st.session_state.resume_preview_bytes if ch == "Resume" else st.session_state.cover_letter_preview_bytes
                dl = st.session_state.resume_dl_data if ch == "Resume" else st.session_state.cl_dl_data
                if dl:
                    sync = st.checkbox("Sync to Tracker", value=True) if st.session_state.logged_in else False
                    st.download_button(f"Download {dl['name']}", dl["bytes"], dl["name"], use_container_width=True, on_click=sync_application_to_tracker if sync and ch=="Resume" else None)
                if target: render_pdf_js(target)
                else: st.info(f"The {ch} data is missing.")
            else: st.info("Click 'Generate PDF' to see preview.")
    else: st.warning("Optimize first.")

if active_view == "Tracker":
    if st.session_state.logged_in:
        tracker_db = get_db()
        if tracker_db is not None:
            render_interview_progress(tracker_db, st.session_state.user_email)
            render_dashboard(tracker_db, st.session_state.user_email)
        else:
            st.warning("Tracker is unavailable until Firebase secrets are configured.")
    else: st.warning("Login first.")
