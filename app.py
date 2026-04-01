import streamlit as st
import google.generativeai as genai
import jinja2
import subprocess
import os
import json
import streamlit_ace as st_ace # 引入 streamlit-ace 套件
from datetime import datetime

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

if "base_resume_saved_time" not in st.session_state:
    st.session_state.base_resume_saved_time = None
if "optimized_resume_saved_time" not in st.session_state:
    st.session_state.optimized_resume_saved_time = None
if "opt_editor_key" not in st.session_state:
    st.session_state.opt_editor_key = 0

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


        Task Instructions:
        1. Information Extraction: Accurately extract the Company Name and Job Title from the provided Job Description (JD). Populate these into the target_company and target_role fields respectively.
        2. Cover Letter Composition: Write a professional and compelling Cover Letter based on the JD. The content must be tailored to the specific requirements and company culture mentioned. Place the full text into the cover_letter field of the JSON.
        3. Signature Formatting: Ensure the Cover Letter concludes with the following specific format:
        4. Use the closing phrase "Best regards,"
            Followed by a new line.
            Followed by the Applicant's First Name only.

        Output Format:
        Please provide the final result strictly in JSON format.

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
            return False, f"⚠️ AI 輸出了格式錯誤的 JSON (JSON 語法錯誤)。建議您再點擊執行一次！\n\n**系統錯誤訊息:** {json_err}\n\n**AI 原始輸出片段 (供除錯):**\n```json\n{raw_text[:800]}\n```"

        modified_resume_data = ai_result.get("optimized_resume", {})
        if not modified_resume_data:
            return False, "⚠️ Parsing Error: Could not find the optimized resume data."
            
        st.session_state.optimized_resume_data = modified_resume_data

        # 直接將 AI 生成的結果寫入 ml_resume.json 檔案
        with open("ml_resume.json", "w", encoding="utf-8") as f:
            json.dump(modified_resume_data, f, indent=4, ensure_ascii=False)

        # 更新動態 Key 來強制 Streamlit Ace 編輯器重新渲染並載入新資料
        st.session_state.opt_editor_key += 1
        # AI 剛跑完，重設儲存時間，提示使用者去手動儲存
        st.session_state.optimized_resume_saved_time = None
        
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
def generate_pdf_from_json(data, custom_tex_bytes=None, template_name="main.tex"):
    # Determine which .tex file to use
    tex_filename = template_name
    if custom_tex_bytes:
        template_content = custom_tex_bytes.decode('utf-8')
        tex_filename = "custom_main.tex"
        with open(tex_filename, "w", encoding="utf-8") as f:
            f.write(template_content)

    try:
        # --- 清除所有的 Markdown 粗體符號 (**) ---
        # 透過先轉為 JSON 字串，取代後再轉回 dict，避免 dict 物件沒有 replace 方法的錯誤
        data_str = json.dumps(data, ensure_ascii=False)
        data_str = data_str.replace('**', '')
        clean_data = json.loads(data_str)

        # --- NEW LOGIC ---
        # Write the data to a temporary JSON file that the LuaLaTeX script expects.
        temp_json_filename = "ml_resume.json"
        with open(temp_json_filename, "w", encoding="utf-8") as f:
            json.dump(clean_data, f, ensure_ascii=False, indent=4)

        # The final PDF will be named after the .tex file, e.g., main.pdf
        # We will rename it later for consistency.
        base_name = os.path.splitext(tex_filename)[0]
        expected_pdf_name = f"{base_name}.pdf"
        
        company = clean_data.get('target_company', 'Company').replace(' ', '_').replace('/', '_')
        role = clean_data.get('target_role', 'Role').replace(' ', '_').replace('/', '_')
        final_pdf_name = f"{company}_{role}_resume.pdf"
            
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
def generate_cover_letter_pdf(resume_data):
    """Generates a PDF from the 'cover_letter' field using a hardcoded clean LaTeX template."""
    # --- NEW: Unify data source by reading from ml_resume.json first ---
    temp_json_filename = "ml_resume.json"
    if not os.path.exists(temp_json_filename):
        st.error(f"Error: `{temp_json_filename}` not found. Please generate a resume first.")
        return None
    
    with open(temp_json_filename, "r", encoding="utf-8") as f:
        data_from_file = json.load(f)

    try:
        # 取得公司與職位名，處理檔名 (將空格與斜線替換為底線)
        company = data_from_file.get('target_company', 'Company').replace(' ', '_').replace('/', '_')
        role = data_from_file.get('target_role', 'Role').replace(' ', '_').replace('/', '_')

        custom_filename = f"{company}_{role}_coverletter"
        tex_filename = f"{custom_filename}.tex"
        pdf_filename = f"{custom_filename}.pdf"

        # 取得內容並進行清理
        cl_content = data_from_file.get('cover_letter', 'No content')
        clean_cl_content = cl_content.replace('**', '')

        # 跳脫 LaTeX 特殊字元，防止 % (註解)、$ (數學模式) 等造成編譯失敗
        def escape_tex(text):
            # 替換順序很重要，先處理反斜線
            text = text.replace('\\', '\\textbackslash{}')
            chars_to_escape = ['&', '%', '$', '#', '_', '{', '}']
            for c in chars_to_escape:
                text = text.replace(c, '\\' + c)
            text = text.replace('~', '\\textasciitilde{}')
            text = text.replace('^', '\\textasciicircum{}')
            return text
            
        escaped_content = escape_tex(clean_cl_content)

        # --- 乾淨的 LaTeX 模板 ---
        latex_template = r"""
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{fontspec}
\usepackage{setspace}
\usepackage{parskip} % ✨ 魔法在這裡：這行會強制取消所有縮排，讓文字完美靠左！
\onehalfspacing
\begin{document}
""" + escaped_content.replace("\n", "\n\n") + r"""
\end{document}
"""
        
        # 寫入 .tex
        with open(tex_filename, "w", encoding="utf-8") as f:
            f.write(latex_template)

        # Compile with lualatex
        process = subprocess.run(
            ['lualatex', '-interaction=nonstopmode', tex_filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if process.returncode == 0 and os.path.exists(pdf_filename):
            return pdf_filename
        else:
            st.error("❌ Cover Letter PDF 生成失敗。")
            with st.expander("View Full Compilation Log (查看錯誤日誌)"):
                st.text(process.stdout)
                st.text(process.stderr)
            return None

    except Exception as e:
        st.error(f"Cover Letter PDF generation failed: {e}")
        return None

# ---------------------------------------------------------
# Custom Premium UI Components (Glassmorphism & Overlays)
# ---------------------------------------------------------
def get_glass_overlay_html(message="AI is processing your request...", animal_emoji="🐕", theme_color="#8a2be2"):
    """全螢幕的玻璃擬態載入層，利用 fixed 與 high z-index 凍結所有底部按鈕操作"""
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
        var scale = Math.random() * 0.5 + 0.8; // 隨機縮放 0.8 到 1.3
        
        animal.style.transform = 'rotate(' + newRot + 'deg) scale(' + scale + ')';
        setTimeout(function(){{
            if(document.body.contains(animal))
                animal.style.transform = 'rotate(' + currentRot + 'deg) scale(1)';
        }}, 350);
        
        // 隨機安排下一次動作的時間 (600毫秒 ~ 1800毫秒之間)
        var nextTime = Math.random() * 1200 + 600;
        setTimeout(triggerRandomAnim, nextTime);
    }}
    if(animal) setTimeout(triggerRandomAnim, 500);
">"""

def get_glass_warning_html():
    """帶有琥珀色脈衝三角核心的玻璃擬態警告框"""
    return """<div style="background: rgba(20, 10, 10, 0.5); border: 1px solid rgba(255, 165, 0, 0.3); border-radius: 16px; padding: 25px; display: flex; align-items: center; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4); backdrop-filter: blur(12px); margin-bottom: 20px;">
    <div style="width: 40px; height: 40px; background: radial-gradient(circle, rgba(255,165,0,0.9) 0%, rgba(255,140,0,0.2) 80%); clip-path: polygon(50% 0%, 0% 100%, 100% 100%); animation: pulse-amber 2s infinite alternate; margin-right: 25px; flex-shrink: 0; box-shadow: 0 0 20px rgba(255, 165, 0, 0.6);"></div>
    <div>
        <h3 style="color: #ffcc00; margin: 0 0 8px 0; font-family: sans-serif; font-weight: 500; letter-spacing: 0.5px; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);">resume.json Not Opened</h3>
        <p style="color: #e0e0e0; margin: 0; font-size: 0.95em; font-weight: 300;">System cannot locate the generated resume data. Please execute the AI generation first to create the base file.</p>
    </div>
</div>
<style>
@keyframes pulse-amber { 
    0% { transform: scale(0.95); opacity: 0.7; filter: drop-shadow(0 0 5px rgba(255,165,0,0.5)); } 
    100% { transform: scale(1.05); opacity: 1; filter: drop-shadow(0 0 15px rgba(255,165,0,1)); } 
}
</style>"""

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
    with st.container(border=True):
        st.markdown("##### 👤 Base Profile")
        if st.session_state.get("base_resume_saved_time"):
            st.success(f"Last saved: {st.session_state.base_resume_saved_time}")
        else:
            st.info("Default template loaded. No changes saved yet.")
        
        if st.button("👁️ Preview Base Profile"):
            preview_base_profile()

with col2:
    with st.container(border=True):
        st.markdown("##### ✨ Optimized Profile (ml_resume)")
        if st.session_state.optimized_resume_data:
            if st.session_state.get("optimized_resume_saved_time"):
                st.success(f"Last saved: {st.session_state.optimized_resume_saved_time}")
            else:
                st.warning("Data loaded. Review and save in Tab 4.")
            
            if st.button("👁️ Preview Optimized Profile"):
                preview_optimized_profile()
        else:
            st.info("Not yet generated. Run AI in Tab 2.")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["1️⃣ Base Profile", "2️⃣ AI Customization", "3️⃣ AI Report", "4️⃣ Edit Optimized Result", "5️⃣ Export PDF & Cover Letter"])

# --- 1. Base Profile Tab ---
with tab1:
    st.header("👤 Edit Your Base Profile")
    st.info("This is your **Base Template**. AI will always use this as the ground truth for optimizations. Remember to click 'Save Changes' below.")
    
    json_str = json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False)
    # 將 st.text_area 替換為 st_ace.st_ace，提供更豐富的編輯體驗，包含行號和語法高亮
    edited_json = st_ace.st_ace(
        value=json_str,
        language="json", # 設定為 JSON 語法高亮
        theme="dracula", # 選擇一個類似 VS Code 的深色主題，例如 "dracula" 或 "monokai"
        height=500,
        key="base_resume_editor", # 為編輯器設定一個唯一的 key
        font_size=14, # 設定字體大小
        tab_size=2, # 設定 Tab 縮排大小
        show_gutter=True, # 啟用行號顯示
        auto_update=True, # 自動更新編輯器內容到 Streamlit
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
    custom_prompt = st.text_area("🗣️ Custom Prompt (Optional)", value="Make the experiences sound more aggressive and impactful. Focus on system optimization and microservices keywords.")
    
    if st.button("🚀 Start AI Optimization & Analysis", type="primary"):
        if not jd_input:
            st.warning("Please paste the JD content first!")
        else:
            # 呼叫全螢幕動態凍結載入層
            loading_overlay = st.empty()
            loading_overlay.markdown(get_glass_overlay_html("AI is crafting your resume...<br>Please wait.", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)
            
            success, report = ai_optimize_and_update(jd_input, custom_prompt, enable_ats, check_visa)
            st.session_state.ai_report = report
            
            # 執行完畢，移除載入層，解除凍結
            loading_overlay.empty()
            
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

    # --- FIX: Move button to the top and handle state update before rendering ---
    if st.button("🔄 Refresh from ml_resume.json"):
        if os.path.exists("ml_resume.json"):
            with open("ml_resume.json", "r", encoding="utf-8") as f:
                refreshed_data = json.load(f)
                st.session_state.optimized_resume_data = refreshed_data
                # 改變 key 強制重新渲染編輯器
                st.session_state.opt_editor_key += 1
                st.session_state.optimized_resume_saved_time = None
                st.success("Refreshed data from `ml_resume.json`! The view will update.")
        else:
            # 使用高質感的琥珀色警告框
            st.markdown(get_glass_warning_html(), unsafe_allow_html=True)

    if st.session_state.optimized_resume_data:
        st.info("This is the new version tailored by AI based on the JD! You can make final tweaks here before exporting.")
        
        editor_value = json.dumps(st.session_state.optimized_resume_data, indent=4, ensure_ascii=False)

        edited_opt_json = st_ace.st_ace(
            value=editor_value,
            language="json",
            theme="dracula",
            height=500,
            key=f"optimized_resume_editor_{st.session_state.opt_editor_key}", # 動態 key 強制更新
            font_size=14,
            tab_size=2,
            show_gutter=True, # 啟用行號顯示
            auto_update=True,
        )
        
        if st.button("💾 Save Optimized Changes", type="primary", key="save_opt"):
            try:
                st.session_state.optimized_resume_data = json.loads(edited_opt_json)
                # The editor's content is already up-to-date via auto_update=True. We just need to save the parsed data.
                st.session_state.optimized_resume_saved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    
    template_choice = st.radio("🎨 Select Resume Template", ["💻", "📈"], horizontal=True)
    selected_template = "main.tex" if template_choice.startswith("💻") else "elsa_main.tex"

    uploaded_tex = st.file_uploader("Upload custom resume main.tex (Optional)", type=["tex"], key="resume_tex")
    
    if st.button("Compile & Generate PDF Resume", type="primary"):
        loading_overlay = st.empty()
        loading_overlay.markdown(get_glass_overlay_html("Calling LaTeX engine in the cloud...<br>Compiling your Resume...", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)
        
        tex_bytes = uploaded_tex.getvalue() if uploaded_tex else None
        pdf_path = generate_pdf_from_json(data_to_use, tex_bytes, template_name=selected_template)
        
        loading_overlay.empty()
        
        if pdf_path:
            st.success("✅ PDF successfully generated!")
            with open(pdf_path, "rb") as f:
                st.download_button(f"📥 Click to Download Resume", f, file_name=pdf_path, mime="application/pdf")
                    
    st.markdown("---")
    st.subheader("✉️ Export Cover Letter")
    
    if st.button("✨ Generate & Download Cover Letter PDF", type="primary", key="gen_cl"):
        if 'cover_letter' not in data_to_use or not data_to_use['cover_letter']:
            st.warning("No 'cover_letter' field found in the current resume data. Please run AI optimization first if it's supposed to generate it.")
        else:
            loading_overlay = st.empty()
            loading_overlay.markdown(get_glass_overlay_html("Compiling the Cover Letter PDF...<br>Almost done.", st.session_state.get('animal_emoji', '🐕'), st.session_state.get('theme_color', '#8a2be2')), unsafe_allow_html=True)
            
            cl_pdf_path = generate_cover_letter_pdf(data_to_use)
            
            loading_overlay.empty()
            
            if cl_pdf_path:
                with open(cl_pdf_path, "rb") as f:
                    st.download_button("📥 Click to Download Cover Letter", f, file_name=cl_pdf_path, mime="application/pdf")