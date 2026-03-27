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
    # Determine which .tex file to use
    tex_filename = "main.tex"
    if custom_tex_bytes:
        template_content = custom_tex_bytes.decode('utf-8')
        tex_filename = "custom_main.tex"
        with open(tex_filename, "w", encoding="utf-8") as f:
            f.write(template_content)

    try:
        # --- NEW LOGIC ---
        # Write the data to a temporary JSON file that the LuaLaTeX script expects.
        temp_json_filename = "ml_resume.json"
        with open(temp_json_filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        # The final PDF will be named after the .tex file, e.g., main.pdf
        # We will rename it later for consistency.
        base_name = os.path.splitext(tex_filename)[0]
        expected_pdf_name = f"{base_name}.pdf"
        final_pdf_name = "resume.pdf"
            
        # 呼叫 LuaLaTeX 編譯
        process = subprocess.Popen(
            ['lualatex', '-interaction=nonstopmode', tex_filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        
        if process.returncode == 0 and os.path.exists(expected_pdf_name):
            # Rename the output file for a consistent download name
            if os.path.exists(final_pdf_name):
                os.remove(final_pdf_name)
            os.rename(expected_pdf_name, final_pdf_name)
            return final_pdf_name
        else:
            st.error(f"LaTeX Compilation Failed (Return Code {process.returncode}) for {tex_filename}")
            with st.expander("View Full Compilation Log"):
                st.text(stdout.decode('utf-8', errors='ignore'))
                st.text(stderr.decode('utf-8', errors='ignore'))
            return None
    except Exception as e:
        st.error(f"Exception during generation: {e}")
        return None

# ---------------------------------------------------------
# Cover Letter AI and PDF Generation
# ---------------------------------------------------------
def generate_cover_letter_content(resume_data, jd_text, custom_cl_prompt):
    """Generates the body of the cover letter using AI."""
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            st.error("Please set your Gemini API Key in the sidebar.")
            return None

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""
        You are a professional career coach. Based on the candidate's resume and the target job description (JD), write a concise and impactful cover letter.

        **Candidate's Resume:**
        {json.dumps(resume_data, ensure_ascii=False)}

        **Target Job Description (JD):**
        {jd_text}

        **User's Special Instructions:**
        {custom_cl_prompt}

        **Task:**
        Generate the body of the cover letter only. It should be 3-4 paragraphs long.
        - Start with a strong opening that grabs the reader's attention.
        - Highlight 2-3 key experiences or skills from the resume that directly match the JD's requirements.
        - End with a confident closing and a call to action.
        - Do NOT include the sender's/recipient's address or the date. Just the body content, starting from "Dear Hiring Manager,".
        - Do NOT use markdown like '**'.

        **Output:**
        (The generated cover letter body text)
        """
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        st.error(f"AI Cover Letter generation failed: {e}")
        return None

def generate_cover_letter_pdf(cl_content, resume_data):
    """Generates a PDF from the cover letter content using a Jinja2 template."""
    try:
        # Using Jinja2 for simple text replacement is cleaner and safer
        latex_jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.abspath('.')),
            autoescape=False
        )
        template = latex_jinja_env.get_template('cover_letter.tex')

        # Prepare data for the template
        template_data = {
            "name": resume_data.get("heading", {}).get("name", "John Doe"),
            "email": resume_data.get("heading", {}).get("email", ""),
            "phone": resume_data.get("heading", {}).get("phone", ""),
            "linkedin": resume_data.get("heading", {}).get("linkedin", ""),
            "website": resume_data.get("heading", {}).get("website", ""),
            "body": cl_content.replace('\n', '\n\n') # Ensure paragraphs are spaced
        }

        rendered_tex = template.render(template_data)
        
        with open("rendered_cl.tex", "w", encoding="utf-8") as f:
            f.write(rendered_tex)

        # Compile with lualatex
        subprocess.run(['lualatex', '-interaction=nonstopmode', 'rendered_cl.tex'], check=True)
        return "rendered_cl.pdf"

    except Exception as e:
        st.error(f"Cover Letter PDF generation failed: {e}")
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
    jd_input = st.text_area("📄 Paste the Target Job Description (JD)", height=250, key="jd_input_for_cl")
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
    
    custom_cl_prompt = st.text_area("🗣️ Custom Prompt for Cover Letter (Optional)", value="Please write in a professional but friendly tone. Emphasize my backend skills.", key="cl_prompt")

    if st.button("✨ Generate & Download Cover Letter PDF", type="primary", key="gen_cl"):
        jd_text = st.session_state.get('jd_input_for_cl', "") # We need the JD from tab 2
        with st.spinner("AI is crafting your cover letter..."):
            cl_content = generate_cover_letter_content(data_to_use, jd_text, custom_cl_prompt)
        
        if cl_content:
            st.text_area("Generated Cover Letter Body (for review)", cl_content, height=300)
            with st.spinner("Now compiling the Cover Letter PDF..."):
                cl_pdf_path = generate_cover_letter_pdf(cl_content, data_to_use)
                if cl_pdf_path:
                    with open(cl_pdf_path, "rb") as f:
                        st.download_button("📥 Click to Download Cover Letter", f, file_name="cover_letter.pdf", mime="application/pdf")