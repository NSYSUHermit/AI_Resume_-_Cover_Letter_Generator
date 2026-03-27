import streamlit as st
import google.generativeai as genai
import jinja2
import subprocess
import os
import json

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
        ai_result = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        
        modified_resume_data = ai_result.get("optimized_resume", {})
        if not modified_resume_data:
            return False, "⚠️ Parsing Error: Could not find the optimized resume data."
            
        st.session_state.optimized_resume_data = modified_resume_data
        
        # 生成 Markdown 報告
        if enable_ats and "keyword_analysis" in ai_result:
            kw = ai_result["keyword_analysis"]
            tot = len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", []))
            orig_c = len(kw.get("original_hits", []))
            opt_c = len(kw.get("optimized_hits", []))
            opt_pct = int((opt_c / tot) * 100) if tot > 0 else 0
            
            report_md += f"### 🎯 ATS Keyword Match Score\n"
            report_md += f"- **Before Optimization**: {orig_c} / {tot}\n"
            report_md += f"- **After AI Optimization**: {opt_c} / {tot} (**{opt_pct}%**)\n\n"
            
            report_md += "**✅ Successfully Hit Keywords:**\n"
            for k in kw.get("optimized_hits", []):
                if k in kw.get("newly_added", []):
                    report_md += f"- `{k}` 🌟 *(Forced injection via AI horizontal shift)*\n"
                else:
                    report_md += f"- `{k}`\n"
            if kw.get("missing_keywords"):
                report_md += "\n**❌ Missing Keywords:**\n"
                for k in kw.get("missing_keywords", []):
                    report_md += f"- `{k}`\n"
            report_md += "\n---\n"
            
        report_md += f"### 📝 Changelog\n{ai_result.get('changelog', '')}"
        
        return True, report_md
    except Exception as e:
        return False, f"⚠️ AI execution error: {e}"

# ---------------------------------------------------------
# PDF 生成邏輯 (支援自訂 main.tex)
# ---------------------------------------------------------
def generate_pdf_from_json(data, custom_tex_bytes=None):
    # 決定使用的 tex 模板內容
    if custom_tex_bytes:
        template_content = custom_tex_bytes.decode('utf-8')
        template_name = "custom_main.tex"
        with open(template_name, "w", encoding="utf-8") as f:
            f.write(template_content)
    else:
        template_name = "main.tex"

    # 設定 Jinja2 環境，避免與 LaTeX 的 {} 衝突
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
    
    try:
        template = latex_jinja_env.get_template(template_name)
        rendered_tex = template.render(**data)
        
        # 將渲染後的內容寫入暫存的 tex 檔
        tex_filename = "rendered_resume.tex"
        pdf_filename = "rendered_resume.pdf"
        
        with open(tex_filename, "w", encoding="utf-8") as f:
            f.write(rendered_tex)
            
        # 呼叫 LuaLaTeX 編譯
        process = subprocess.Popen(
            ['lualatex', '-interaction=nonstopmode', tex_filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        
        if process.returncode == 0 and os.path.exists(pdf_filename):
            return pdf_filename
        else:
            st.error(f"LaTeX Compilation Failed (Return Code {process.returncode})")
            with st.expander("View Compilation Log"):
                st.text(stdout.decode('utf-8', errors='ignore'))
                st.text(stderr.decode('utf-8', errors='ignore'))
            return None
    except Exception as e:
        st.error(f"Exception during generation: {e}")
        return None

# ---------------------------------------------------------
# Streamlit UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI Resume Builder", page_icon="🚀", layout="wide")

# --- Sidebar Settings ---
with st.sidebar:
    st.header("⚙️ Settings")
    api_key_input = st.text_input("🔑 Google Gemini API Key", type="password", help="API Key is required to use AI features.")
    if api_key_input:
        st.session_state.api_key = api_key_input
    st.markdown("---")
    st.markdown("👉 Get Gemini API Key for free")
    st.markdown("---")
    st.markdown("👨‍💻 **Developed by NSYSUHermit**")

st.title("🚀 AI-Powered Resume Builder")
st.write("Combine Gemini AI with LaTeX to write, optimize, and export high-quality PDF resumes and cover letters effortlessly.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["1️⃣ Base Profile", "2️⃣ AI Customization", "3️⃣ AI Report", "4️⃣ Edit Optimized Result", "5️⃣ Export PDF & Cover Letter"])

# --- 1. Base Profile Tab ---
with tab1:
    st.header("👤 Edit Your Base Profile")
    st.info("This is your **Base Template**. AI will always use this as the ground truth for optimizations. Remember to click 'Save Changes' below.")
    
    json_str = json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False)
    edited_json = st.text_area("Resume JSON Structure", value=json_str, height=500)
    
    if st.button("💾 Save JSON Changes", type="primary"):
        try:
            st.session_state.resume_data = json.loads(edited_json)
            st.success("JSON data saved successfully!")
        except Exception as e:
            st.error(f"JSON format error, please check syntax: {e}")

# --- 2. AI Customization Tab ---
with tab2:
    st.header("🤖 Auto-Optimize Resume based on JD")
    col1, col2 = st.columns(2)
    enable_ats = col1.checkbox("Enable ATS Keyword Analysis", value=True)
    check_visa = col2.checkbox("Check Visa/Sponsorship Restrictions", value=True)
    
    jd_input = st.text_area("📄 Paste the Target Job Description (JD)", height=250)
    custom_prompt = st.text_area("🗣️ Custom Prompt (Optional)", value="Make the experiences sound more aggressive and impactful. Focus on system optimization and microservices keywords.")
    
    if st.button("🚀 Start AI Optimization & Analysis", type="primary"):
        if not jd_input:
            st.warning("Please paste the JD content first!")
        else:
            with st.spinner("AI is deeply analyzing and rewriting to match ATS keywords. This might take 30~60 seconds..."):
                success, report = ai_optimize_and_update(jd_input, custom_prompt, enable_ats, check_visa)
                st.session_state.ai_report = report
                if success:
                    st.success("Optimization completed! Please go to '4️⃣ Edit Optimized Result' to review and tweak.")
                else:
                    st.error("Optimization interrupted or failed. Check the report details.")

# --- 3. AI Report Tab ---
with tab3:
    st.header("📊 AI Execution Result & ATS Report")
    if st.session_state.ai_report:
        st.markdown(st.session_state.ai_report)
        st.info("💡 Report generated! The optimized resume has been saved to '4️⃣ Edit Optimized Result'. Your base profile remains untouched.")
    else:
        st.write("No AI optimization executed yet. Please paste a JD in '2️⃣ AI Customization' and run it.")

# --- 4. Edit Optimized Result Tab ---
with tab4:
    st.header("📝 Review & Edit Optimized Resume")
    if st.session_state.optimized_resume_data:
        st.info("This is the new version tailored by AI based on the JD! You can make final tweaks here before exporting.")
        opt_json_str = json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False)
        edited_opt_json = st.text_area("Optimized Resume JSON", value=opt_json_str, height=500, key="opt_json_area")
        
        if st.button("💾 Save Optimized Changes", type="primary", key="save_opt"):
            try:
                st.session_state.optimized_resume_data = json.loads(edited_opt_json)
                st.success("Optimized data saved successfully!")
            except Exception as e:
                st.error(f"JSON format error, please check syntax: {e}")
    else:
        st.warning("No optimized data generated yet. Please run the AI in '2️⃣ AI Customization' or proceed directly to '5️⃣ Export' to use your base profile.")

# --- 5. Export Tab ---
with tab5:
    st.header("🖨️ Generate & Export PDF Resume / Cover Letter")
    
    st.subheader("📄 Export PDF Resume")
    st.write("The system defaults to using the data from '4️⃣ Edit Optimized Result'. If no optimized data exists, it will use your '1️⃣ Base Profile'.")
    
    data_to_use = st.session_state.optimized_resume_data if st.session_state.optimized_resume_data else st.session_state.resume_data
    
    uploaded_tex = st.file_uploader("Upload custom resume main.tex (Optional)", type=["tex"], key="resume_tex")
    
    if st.button("Compile & Generate PDF Resume", type="primary"):
        with st.spinner("Calling LaTeX engine in the cloud..."):
            tex_bytes = uploaded_tex.getvalue() if uploaded_tex else None
            pdf_path = generate_pdf_from_json(data_to_use, tex_bytes)
            
            if pdf_path:
                st.success("✅ PDF successfully generated!")
                with open(pdf_path, "rb") as f:
                    st.download_button("📥 Click to Download Resume (resume.pdf)", f, file_name="resume.pdf", mime="application/pdf")
                    
    st.markdown("---")
    st.subheader("✉️ Export Cover Letter")
    st.info("💡 This section is ready for Cover Letters! In the future, we just need to add a generation prompt and a `.tex` template to output one-click cover letters.")
    st.button("Generate Cover Letter (Coming Soon)", disabled=True)