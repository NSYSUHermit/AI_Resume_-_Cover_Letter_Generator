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
def parse_pdf_resume_to_json(pdf_bytes, api_key):
    if not api_key:
        return False, "⚠️ Error: Please set your GEMINI API KEY in the sidebar first.", None

    try:
        genai.configure(api_key=api_key)
        model_name = st.session_state.get("ai_model", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)

        prompt = """
        You are an expert resume parser. I will provide you with a resume in PDF format.
        Extract all the relevant information and structure it STRICTLY in the following JSON format.
        Do not make up information. If a field is missing in the resume, leave it empty or omit it gracefully.
        Return ONLY valid JSON, without any markdown formatting like ```json.

        Expected JSON Structure:
        {
            "heading": { "name": "", "email": "", "phone": "", "website": "", "linkedin": "" },
            "cover_letter": "",
            "target_company": "",
            "target_role": "",
            "about me more": "",
            "summary": "",
            "education": [ { "degree": "", "time_period": "", "school": "", "school_location": "" } ],
            "experience": [ { "role": "", "team": "", "company": "", "company_location": "", "time_duration": "", "details": [ { "title": "", "description": "" } ] } ],
            "projects": [ { "name": "", "time": "", "description": "" } ],
            "patents": [ { "name": "", "time": "", "description": "" } ],
            "skills": { "set1": { "title": "", "items": [] }, "set2": { "title": "", "items": [] } }
        }
        """

        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        response = model.generate_content([prompt, pdf_part])
        raw_text = response.text.replace('```json', '').replace('```', '').strip()

        parsed_json = json.loads(raw_text)
        return True, "✅ PDF successfully parsed into JSON!", parsed_json
    except json.JSONDecodeError as e:
        return False, f"⚠️ Failed to parse AI response into JSON. Raw output might be malformed: {e}", None
    except Exception as e:
        return False, f"⚠️ Error during PDF parsing: {e}", None

def build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, resume_data):
    """Helper function to build the full prompt text"""
    visa_check_instruction = ""
    if check_visa:
        visa_check_instruction = """
    - Step 1 (Visa Check): First, analyze the [Target JD] for visa sponsorship restrictions (e.g., "U.S. Citizen only", "no sponsorship"). If you find any, you MUST STOP and return ONLY this JSON: `{"visa_blocked": true, "reason": "Your reason here"}`.
    - Step 2 (Optimization): If the visa check passes, proceed with the optimization and return the full JSON structure as described below, with `"visa_blocked": false`.
    """
    else:
        visa_check_instruction = """
    - Step 1 (Visa Check): This step is disabled. Proceed directly to Step 2.
    - Step 2 (Optimization): Proceed with the optimization and return the full JSON structure as described below, with `"visa_blocked": false`.
    """

    ats_example = ""
    if enable_ats:
        ats_example = """"keyword_analysis": {"jd_keywords": ["AWS", "Python"], "original_hits": ["Python"], "optimized_hits": ["Python", "AWS"], "newly_added": ["AWS"], "missing_keywords": []},"""

    final_prompt = f"""
You are an expert resume optimizer. Follow these steps and rules precisely.

{custom_prompt}

{visa_check_instruction}

[Target JD]: {jd_text}
[Original Resume JSON]: {json.dumps(resume_data, ensure_ascii=False)}

🔥 STRICT RULES for Step 2 (if you get here):
1. Cover Letter:
    - Write a complete cover letter based on the JD and place it in the "cover_letter" field.
    - ALWAYS end with "Best regards," followed by a newline and the applicant's first name.
2. Extraction: Extract the target company and role from the JD and put them into "target_company" and "target_role" fields.
3. ATS Keyword Injection:
    - Horizontal Shift: If JD requires GCP and the candidate has AWS, rewrite as "AWS/GCP" in skills or summary. Do not hallucinate unrelated skills.
    - Concept Replacement: Cleverly replace synonyms in experience descriptions to hit ATS keywords.
    - ⚠️ Consistency Rule: Keywords in `newly_added` MUST strictly appear in `optimized_resume`.
4. Strict JSON Schema Preservation:
    - NEVER drop, rename, or omit any fields/keys from the [Original Resume JSON].
    - The `experience.details` MUST STRICTLY remain a list of objects exactly like `[{{"title": "...", "description": "..."}}]`. Do NOT simplify it into a list of strings.
    - Preserve the exact hierarchical structure of the original data. Only mutate the text values inside to optimize them.

⚠️ [Output Format Limitation]: Your entire response MUST be a single, valid JSON object. Do not use markdown ticks like ```json.
The final JSON structure for a successful optimization (Step 2) should be:
{{
    "visa_blocked": false,
    "changelog": "Brief explanation of modifications...",
    {ats_example}
    "optimized_resume": {{...Updated full resume JSON structure...}}
}}
"""
    return final_prompt

def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            return False, "⚠️ Error: Please set your GEMINI API KEY in the sidebar first."
            
        genai.configure(api_key=api_key)
        model_name = st.session_state.get("ai_model", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)
        report_md = ""
        
        final_prompt = build_optimization_prompt(jd_text, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
        
        # Single API call
        response = model.generate_content(
            final_prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        raw_text = response.text.strip()
        
        try:
            ai_result = json.loads(raw_text)
        except json.JSONDecodeError as json_err:
            return False, f"⚠️ AI output malformed JSON. Please try again!\n\n**System Error:** {json_err}\n\n**Raw Output Fragment:**\n```json\n{raw_text[:800]}\n```"

        # Handle response based on visa_blocked flag
        if ai_result.get("visa_blocked"):
            report_md = f"### ⛔ Visa Sponsorship Check Failed\n**Reason:** {ai_result.get('reason')}\n\n💡 Suggestion: Due to visa restrictions, AI has stopped the optimization. Save your time for the next company!"
            return False, report_md
        
        # If not blocked, proceed with processing the successful result
        report_md += "✅ **Visa check passed! No explicit sponsorship barriers found.**\n\n---\n" if check_visa else ""

        modified_resume_data = ai_result.get("optimized_resume", {})
        if not modified_resume_data:
            return False, "⚠️ Parsing Error: Could not find the optimized resume data in AI response."
            
        st.session_state.optimized_resume_data = modified_resume_data
        st.session_state.opt_editor_key += 1
        st.session_state.optimized_resume_saved_time = None
        st.session_state.ats_metrics = None
        st.session_state.changelog = ai_result.get('changelog', '')

        # Generate Markdown report
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
def generate_preview_pdf_bytes(data, template_name="main.tex", custom_tex_bytes=None, block_order=None):
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
            
            # --- Dynamic Block Injection ---
            tex_path = os.path.join(temp_dir, template_name)
            with open(tex_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            if block_order and "BLOCKS_PLACEHOLDER" in template_content:
                blocks_latex = ""
                for block in block_order:
                    if block == "Summary":
                        blocks_latex += "\\directlua{printSummary()}\n"
                    elif block == "Experience":
                        if "elsa" in template_name:
                            blocks_latex += "\\section{PROFESSIONAL EXPERIENCE}\n  \\vspace{4pt}\n  \\directlua{printExperience()}\n"
                        else:
                            blocks_latex += "\\section{WORK EXPERIENCE}\n  \\directlua{printExperience()}\n"
                    elif block == "Education":
                        if "elsa" in template_name:
                            blocks_latex += "\\section{EDUCATION}\n  \\directlua{printEducation()}\n"
                        else:
                            blocks_latex += "\\section{EDUCATION}\n  \\directlua{printEducation()}\n"
                    elif block == "Projects & Patents":
                        blocks_latex += "\\directlua{printProjectsAndPatents()}\n"
                    elif block == "Skills":
                        if "elsa" in template_name:
                            blocks_latex += "\\section{CORE SKILLS}\n  \\directlua{printSkills()}\n"
                        else:
                            blocks_latex += "\\section{SKILLS}\n  \\directlua{printSkills()}\n"
                
                template_content = template_content.replace("BLOCKS_PLACEHOLDER", blocks_latex)
                with open(tex_path, "w", encoding="utf-8") as f:
                    f.write(template_content)
            # -------------------------------

            temp_json_path = os.path.join(temp_dir, "ml_resume.json")
            with open(temp_json_path, "w", encoding="utf-8") as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=4)
                
            try:
                process = subprocess.run(
                    ['lualatex', '-interaction=nonstopmode', '-halt-on-error', template_name],
                    cwd=temp_dir,
                    capture_output=True,
                    timeout=30
                )
                
                pdf_path = os.path.join(temp_dir, template_name.replace('.tex', '.pdf'))
                if process.returncode == 0 and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        return f.read(), None
                else:
                    return None, process.stdout.decode('utf-8', errors='ignore')
            except subprocess.TimeoutExpired:
                return None, "⚠️ LaTeX compilation timed out after 30 seconds. This might be caused by syntax errors or missing packages."
    except Exception as e:
        return None, str(e)

def generate_word_from_json(resume_data, block_order=None):
    """Generate a simple, editable Word document from the JSON data."""
    doc = Document()
    
    # Adjust margins to fit more content like a resume
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)
        
    # Heading
    heading = resume_data.get("heading", {})
    p_name = doc.add_paragraph()
    p_name.alignment = 1  # Center
    run_name = p_name.add_run(heading.get("name", "Name"))
    run_name.bold = True
    run_name.font.size = Pt(20)
    
    contact_info = [heading.get("email", ""), heading.get("phone", ""), heading.get("linkedin", ""), heading.get("website", "")]
    contact_str = " | ".join([c for c in contact_info if c])
    p_contact = doc.add_paragraph(contact_str)
    p_contact.alignment = 1
    
    if not block_order:
        block_order = ["Summary", "Experience", "Education", "Projects & Patents", "Skills"]
        
    for block in block_order:
        if block == "Summary" and resume_data.get("summary"):
            doc.add_heading("SUMMARY", level=1)
            doc.add_paragraph(resume_data.get("summary", ""))
            
        elif block == "Experience" and resume_data.get("experience"):
            doc.add_heading("WORK EXPERIENCE", level=1)
            for exp in resume_data.get("experience", []):
                p = doc.add_paragraph()
                p.add_run(exp.get("company", "")).bold = True
                p.add_run(f" - {exp.get('role', '')}").italic = True
                loc_time = " | ".join([x for x in [exp.get("company_location", ""), exp.get("time_duration", "")] if x])
                if loc_time:
                    p.add_run(f" ({loc_time})")
                for d in exp.get("details", []):
                    doc.add_paragraph(d.get("description", ""), style="List Bullet")
                    
        elif block == "Education" and resume_data.get("education"):
            doc.add_heading("EDUCATION", level=1)
            for edu in resume_data.get("education", []):
                p = doc.add_paragraph()
                p.add_run(edu.get("school", "")).bold = True
                p.add_run(f" - {edu.get('degree', '')}")
                loc_time = " | ".join([x for x in [edu.get("school_location", ""), edu.get("time_period", "")] if x])
                if loc_time:
                    p.add_run(f" ({loc_time})")
                    
        elif block == "Projects & Patents":
            projects_patents = resume_data.get("projects", []) + resume_data.get("patents", [])
            if projects_patents:
                doc.add_heading("PROJECTS & PATENTS", level=1)
                for item in projects_patents:
                    p = doc.add_paragraph()
                    p.add_run(item.get("name", "")).bold = True
                    if item.get("time"):
                        p.add_run(f" ({item.get('time', '')})")
                    if item.get("description"):
                        doc.add_paragraph(item.get("description", ""), style="List Bullet")
                        
        elif block == "Skills" and resume_data.get("skills"):
            doc.add_heading("SKILLS", level=1)
            for key in ["set1", "set2", "set3"]:
                s = resume_data["skills"].get(key, {})
                if s.get("title") and s.get("items"):
                    p = doc.add_paragraph()
                    p.add_run(s.get("title", "") + ": ").bold = True
                    p.add_run(", ".join(s.get("items", [])))
                
    file_stream = io.BytesIO()
    doc.save(file_stream)
    return file_stream.getvalue()

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

        # Extract and format heading info for Cover Letter
        heading = resume_data.get('heading', {})
        name = escape_tex(heading.get('name', ''))
        email = escape_tex(heading.get('email', ''))
        phone = escape_tex(heading.get('phone', ''))
        linkedin = escape_tex(heading.get('linkedin', ''))
        website = escape_tex(heading.get('website', ''))

        header_tex = "\\begin{flushright}\n"
        if name: header_tex += f"{{\\Large\\bfseries {name}}} \\\\[1em]\n"
        if email: header_tex += f"{email} \\\\\n"
        if phone: header_tex += f"{phone} \\\\\n"
        if linkedin: header_tex += f"{linkedin} \\\\\n"
        if website: header_tex += f"{website} \\\\\n"
        header_tex += "\\end{flushright}\n\\vspace{1em}\n\\today\n\\vspace{2em}\n\n"

        latex_template = r"""
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{fontspec}
\usepackage{setspace}
\usepackage{parskip}
\onehalfspacing
\begin{document}
""" + header_tex + escaped_content.replace("\n", "\n\n") + r"""
\end{document}
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_filename = "cover_letter.tex"
            tex_path = os.path.join(temp_dir, tex_filename)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_template)

            try:
                process = subprocess.run(
                    ['lualatex', '-interaction=nonstopmode', '-halt-on-error', tex_filename],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                gen_pdf_path = os.path.join(temp_dir, tex_filename.replace('.tex', '.pdf'))
                if process.returncode == 0 and os.path.exists(gen_pdf_path):
                    with open(gen_pdf_path, "rb") as f:
                        return f.read(), pdf_filename, None
                else:
                    return None, None, process.stdout + "\n" + process.stderr
            except subprocess.TimeoutExpired:
                return None, None, "⚠️ Cover Letter LaTeX compilation timed out after 30 seconds."
    except Exception as e:
        return None, None, str(e)

def generate_cover_letter_word_bytes(resume_data):
    """Generate a simple, editable Word document for the Cover Letter."""
    doc = Document()
    
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
        
    heading = resume_data.get('heading', {})
    p_head = doc.add_paragraph()
    p_head.alignment = 2  # Right aligned (matches flushright in LaTeX)
    
    run_name = p_head.add_run(heading.get('name', '') + "\n")
    run_name.bold = True
    run_name.font.size = Pt(16)
    
    contact_info = [heading.get('email', ''), heading.get('phone', ''), heading.get('linkedin', ''), heading.get('website', '')]
    contact_str = "\n".join([c for c in contact_info if c])
    if contact_str:
        p_head.add_run(contact_str)
        
    p_date = doc.add_paragraph()
    p_date.add_run("\n" + datetime.today().strftime('%B %d, %Y') + "\n")
    
    cl_content = resume_data.get('cover_letter', '').replace('**', '')
    for para in cl_content.split('\n'):
        if para.strip():
            doc.add_paragraph(para.strip())
            
    file_stream = io.BytesIO()
    doc.save(file_stream)
    return file_stream.getvalue()

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

@st.dialog("🔍 AI Optimization Diff (Base vs Optimized)", width="large")
def show_diff_dialog(base_json, opt_json):
    base_lines = json.dumps(base_json, indent=4, ensure_ascii=False).splitlines()
    opt_lines = json.dumps(opt_json, indent=4, ensure_ascii=False).splitlines()
    
    html_diff = difflib.HtmlDiff().make_file(
        base_lines, opt_lines, 
        fromdesc="Base Profile (Original)", todesc="Optimized Profile (AI Generated)",
        context=True, numlines=5
    )
    
    # Inject custom CSS for Dark Mode and better formatting
    custom_css = """
    <style>
        body { font-family: 'Courier New', Courier, monospace; font-size: 13px; background-color: #0e1117; color: #fafafa; margin: 0; padding: 10px;}
        table.diff { width: 100%; border-collapse: collapse; }
        table.diff th { background-color: #262730; border: 1px solid #444; padding: 4px; text-align: left; }
        table.diff td { padding: 4px; border: 1px solid #333; word-wrap: break-word; max-width: 300px; }
        .diff_header { background-color: #262730; color: #888; text-align: center; width: 1%; }
        .diff_add { background-color: rgba(46, 160, 67, 0.4); }
        .diff_chg { background-color: rgba(227, 179, 65, 0.4); }
        .diff_sub { background-color: rgba(255, 75, 75, 0.4); }
        .diff_next { display: none; }
    </style>
    """
    html_diff = html_diff.replace("</head>", custom_css + "</head>")
    components.html(html_diff, height=650, scrolling=True)

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
    
    ai_model_choice = st.selectbox(
        "🧠 AI Model",
        ["gemini-2.5-flash", "gemini-2.5-pro"],
        index=0,
        help="Select the Gemini model to use for generation."
    )
    st.session_state.ai_model = ai_model_choice
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
    
    with st.container(border=True):
        st.subheader("📥 Auto-Fill from PDF")
        st.write("Upload your existing PDF resume, and let Gemini AI automatically extract and fill the JSON for you!")
        uploaded_pdf = st.file_uploader("Upload your current PDF resume", type=["pdf"])
        if st.button("✨ Auto-Fill JSON from PDF", type="primary", use_container_width=True):
            if uploaded_pdf is None:
                st.warning("Please upload a PDF file first.")
            else:
                loading_overlay = st.empty()
                loading_overlay.markdown(get_glass_overlay_html("Extracting data from PDF...<br>Please wait.", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)

                success, msg, parsed_json = parse_pdf_resume_to_json(uploaded_pdf.getvalue(), st.session_state.get("api_key", ""))

                loading_overlay.empty()
                if success and parsed_json:
                    st.session_state.resume_data = parsed_json
                    st.session_state.base_editor_key += 1
                    st.toast(msg)
                    st.rerun()
                else:
                    st.error(msg)

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
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        run_ai = st.button("🚀 Start AI Optimization", type="primary", use_container_width=True)
    with col_btn2:
        if not jd_input:
            show_prompt = st.button("📋 Copy Prompt for Other AIs", use_container_width=True)
            if show_prompt:
                st.warning("Please paste the JD content first!")
        else:
            prompt_text = build_optimization_prompt(jd_input, custom_prompt, enable_ats, check_visa, st.session_state.resume_data)
            # 將 Prompt 轉換成 Base64，確保換行與特殊字元在傳入 JS 時不會發生語法錯誤
            b64_text = base64.b64encode(prompt_text.encode('utf-8')).decode('utf-8')
            
            html_code = f"""
            <!DOCTYPE html>
            <html>
            <head>
            <style>
            body {{ margin: 0; padding: 0; background-color: transparent; font-family: "Source Sans Pro", sans-serif; }}
            .copy-btn {{
                display: flex; align-items: center; justify-content: center;
                font-weight: 400; padding: 0.25rem 0.75rem; border-radius: 0.5rem;
                min-height: 38px; margin: 0; line-height: 1.6;
                color: rgb(250, 250, 250); width: 100%; user-select: none;
                background-color: transparent; border: 1px solid rgba(250, 250, 250, 0.2);
                cursor: pointer; font-size: 16px; box-sizing: border-box;
                transition: all 0.2s ease;
            }}
            .copy-btn:hover {{ border-color: #ff4b4b; color: #ff4b4b; }}
            .copy-btn:active {{ background-color: #ff4b4b; color: white; }}
            </style>
            </head>
            <body>
                <button class="copy-btn" id="copyBtn" onclick="copyToClipboard()">📋 Copy Prompt for Other AIs</button>
                <script>
                function copyToClipboard() {{
                    const b64 = "{b64_text}";
                    const text = decodeURIComponent(escape(window.atob(b64)));
                    navigator.clipboard.writeText(text).then(function() {{
                        const btn = document.getElementById('copyBtn');
                        btn.innerText = '✅ Copied to Clipboard!';
                        btn.style.borderColor = '#00cc66';
                        btn.style.color = '#00cc66';
                        setTimeout(() => {{
                            btn.innerText = '📋 Copy Prompt for Other AIs';
                            btn.style.borderColor = 'rgba(250, 250, 250, 0.2)';
                            btn.style.color = 'rgb(250, 250, 250)';
                        }}, 2000);
                    }}).catch(function(err) {{
                        console.error('Copy failed', err);
                        const btn = document.getElementById('copyBtn');
                        btn.innerText = '❌ Copy Failed';
                    }});
                }}
                </script>
            </body>
            </html>
            """
            components.html(html_code, height=45)
    
    if run_ai:
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
    
    col_main, col_side = st.columns([7, 3])
    
    with col_side:
        with st.container(border=True):
            st.subheader("📥 Import External JSON")
            st.write("Used ChatGPT or Claude? Paste the full JSON response here to update the ATS metrics and Editor.")
            external_json_str = st.text_area("Paste JSON here", height=400, key="external_json_input")
            
            if st.button("Apply External JSON", type="primary", use_container_width=True):
                if not external_json_str.strip():
                    st.warning("Please paste some JSON first.")
                else:
                    try:
                        # Clean potential markdown backticks (e.g. ```json ... ```)
                        clean_str = external_json_str.replace('```json', '').replace('```', '').strip()
                        external_data = json.loads(clean_str)
                        
                        # Very robust extraction (fallback to full JSON if missing the wrapper structure)
                        modified_resume_data = external_data.get("optimized_resume", external_data)
                        st.session_state.optimized_resume_data = modified_resume_data
                        st.session_state.opt_editor_key += 1
                        st.session_state.optimized_resume_saved_time = None
                        st.session_state.changelog = external_data.get('changelog', 'Imported from external AI.')
                        st.session_state.ai_report = "✅ **External JSON loaded successfully!**\n\n---\n"
                        
                        # Calculate ATS metrics if provided
                        if "keyword_analysis" in external_data:
                            kw = external_data["keyword_analysis"]
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
                        else:
                            st.session_state.ats_metrics = None
                            
                        st.toast("✅ External JSON successfully applied!")
                        st.rerun()
                        
                    except json.JSONDecodeError as json_err:
                        st.error(f"⚠️ Malformed JSON. Please check syntax!\n\nError: {json_err}")
                    except Exception as e:
                        st.error(f"⚠️ Error: {e}")

    with col_main:
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
            st.write("No AI optimization executed yet. Please paste a JD in '2️⃣ AI Optimize' and run it, or import JSON from the right panel.")

# --- 4. Editor & Export Tab ---
with tab4:
    if st.session_state.optimized_resume_data:
        col_title, col_slider = st.columns([6, 4])
        with col_title:
            st.header("📝 Editor & Export")
        with col_slider:
            # 使用 Slider 動態控制左右欄位的寬度比例
            editor_width = st.slider("📐 Adjust Layout (Editor Width %)", min_value=30, max_value=80, value=60, step=5, format="%d%%", help="Slide to resize the Editor and Preview panels")
        
        # Main layout dynamically controlled by the slider
        col_edit, col_export = st.columns([editor_width, 100 - editor_width])
        data_to_use = st.session_state.optimized_resume_data

        with col_edit:
            col_ed_title, col_ed_btn = st.columns([6, 4])
            with col_ed_title:
                st.subheader("JSON Editor")
            with col_ed_btn:
                if st.button("🔍 Compare Changes", use_container_width=True, help="See what the AI modified compared to your Base Profile"):
                    show_diff_dialog(st.session_state.resume_data, data_to_use)
                    
            st.info("Make final tweaks to the AI-generated JSON here. Click 'Save & Refresh' to update the previews on the right.")
            editor_value = json.dumps(data_to_use, indent=4, ensure_ascii=False)
            edited_opt_json = st_ace.st_ace(
                value=editor_value,
                language="json",
                theme="dracula",
                height=800,
                key=f"optimized_resume_editor_{st.session_state.opt_editor_key}",
            font_size=14, tab_size=2, show_gutter=True, auto_update=False,
            )

        with col_export:
            st.subheader("⚙️ Resume Settings")
            
            col_tmpl, col_order = st.columns(2)
            with col_tmpl:
                preview_template = st.selectbox("Template:", ["💻 Tech", "📈 Consulting"], key="preview_template")
                selected_preview_template = "main.tex" if preview_template.startswith("💻") else "elsa_main.tex"

            with col_order:
                default_order = ["Experience", "Education", "Projects & Patents", "Skills"]
                if data_to_use.get("summary"):
                    default_order.insert(0, "Summary")
                block_order = st.multiselect("Block Order:", ["Summary", "Experience", "Education", "Projects & Patents", "Skills"], default=default_order)

            if st.button("🔄 Generate & Update", type="primary", use_container_width=True):
                try:
                    st.session_state.optimized_resume_data = json.loads(edited_opt_json)
                    st.session_state.optimized_resume_saved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    data_to_use = st.session_state.optimized_resume_data
                    
                    st.toast("✅ JSON saved!")

                    loading_overlay = st.empty()
                    loading_overlay.markdown(get_glass_overlay_html("Compiling Documents...<br>Please wait.", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)

                    resume_bytes, r_err = generate_preview_pdf_bytes(data_to_use, selected_preview_template, block_order=block_order)
                    if resume_bytes:
                        st.session_state.resume_preview_bytes = resume_bytes
                        company_name = data_to_use.get('target_company', 'Resume').replace(' ', '_')
                        role_name = data_to_use.get('target_role', 'Role').replace(' ', '_')
                        st.session_state.resume_dl_data = {
                            "bytes": resume_bytes, 
                            "name": f"{company_name}_{role_name}_Resume.pdf",
                            "word_bytes": generate_word_from_json(data_to_use, block_order)
                        }
                        
                    else:
                        st.error(f"Resume generation failed: {r_err}")
                        st.session_state.resume_preview_bytes = None
                        st.session_state.resume_dl_data = None
                    
                    cl_bytes, cl_name, cl_err = generate_cover_letter_pdf_bytes(data_to_use)
                    if cl_bytes:
                        st.session_state.cover_letter_preview_bytes = cl_bytes
                        st.session_state.cl_dl_data = {
                            "bytes": cl_bytes,
                            "name": cl_name,
                            "word_bytes": generate_cover_letter_word_bytes(data_to_use)
                        }
                    else:
                        st.session_state.cover_letter_preview_bytes = None
                        st.session_state.cl_dl_data = None

                    loading_overlay.empty()
                    if resume_bytes:
                        st.toast("✅ Documents successfully generated!")
                except Exception as e:
                    st.error(f"JSON format error, please check syntax: {e}")

            st.divider()
            st.subheader(" Document Preview & Download")
            preview_choice = st.radio("Target:", ["Resume", "Cover Letter"], horizontal=True, key="preview_choice", label_visibility="collapsed")

            if preview_choice == "Resume":
                if st.session_state.resume_dl_data:
                    st.caption(f"📄 **File:** `{st.session_state.resume_dl_data['name']}`")
                    
                    if st.session_state.logged_in:
                        do_sync = st.checkbox("🔄 Sync this application to Job Tracker upon download", value=True, key="sync_resume")
                    else:
                        do_sync = False
                        
                    def on_resume_dl():
                        if do_sync and st.session_state.logged_in and db:
                            company = data_to_use.get('target_company', 'Unknown')
                            jd_text = st.session_state.get('jd_input_for_cl', '')
                            if save_application(db, st.session_state.user_email, company, data_to_use, jd_text):
                                st.toast(f"✅ Synced application for {company} to Job Tracker!")
                                
                    dl_col_pdf, dl_col_word = st.columns([7, 3])
                    with dl_col_pdf:
                        st.download_button("📥 Download PDF", st.session_state.resume_dl_data["bytes"], st.session_state.resume_dl_data["name"], "application/pdf", use_container_width=True, on_click=on_resume_dl)
                    with dl_col_word:
                        word_name = st.session_state.resume_dl_data['name'].replace('.pdf', '.docx')
                        st.download_button("📝 Word (.docx)", st.session_state.resume_dl_data["word_bytes"], word_name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True, help="Download an editable Word document for manual tweaks.", on_click=on_resume_dl)
                    
                    render_pdf_js(st.session_state.resume_preview_bytes, height=500)
                else:
                    st.info("Click '🔄 Generate & Update' to see your resume here.")
            else:
                if st.session_state.cl_dl_data:
                    st.caption(f"📄 **File:** `{st.session_state.cl_dl_data['name']}`")
                    
                    if st.session_state.logged_in:
                        do_sync_cl = st.checkbox("🔄 Sync this application to Job Tracker upon download", value=False, key="sync_cl", help="Unchecked by default to prevent duplicate entries if you already synced the Resume.")
                    else:
                        do_sync_cl = False
                        
                    def on_cl_dl():
                        if do_sync_cl and st.session_state.logged_in and db:
                            company = data_to_use.get('target_company', 'Unknown')
                            jd_text = st.session_state.get('jd_input_for_cl', '')
                            if save_application(db, st.session_state.user_email, company, data_to_use, jd_text):
                                st.toast(f"✅ Synced application for {company} to Job Tracker!")

                    dl_col_pdf_cl, dl_col_word_cl = st.columns([7, 3])
                    with dl_col_pdf_cl:
                        st.download_button("📥 Download PDF", st.session_state.cl_dl_data["bytes"], st.session_state.cl_dl_data["name"], "application/pdf", use_container_width=True, on_click=on_cl_dl)
                    with dl_col_word_cl:
                        cl_word_name = st.session_state.cl_dl_data['name'].replace('.pdf', '.docx')
                        st.download_button("📝 Word (.docx)", st.session_state.cl_dl_data["word_bytes"], cl_word_name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True, help="Download an editable Word document for manual tweaks.", on_click=on_cl_dl)
                    
                    render_pdf_js(st.session_state.cover_letter_preview_bytes, height=500)
                else:
                    st.info("Click '🔄 Generate & Update' to see your cover letter here.")
    else:
        st.header("📝 Editor & Export")
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