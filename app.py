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
            "name": "Henry Lin",
            "email": "hungjuli@asu.edu",
            "phone": "+1-623-290-5568",
            "website": "github.com/NSYSUHermit",
            "linkedin": "linkedin.com/in/henry-lin-57b796187"
        },
        "about me more": "我獨立包辦了從底層模型優化、後端微服務架構，到前端使用者介面的端到端 (End-to-End) 開發...",
        "summary": "Senior Software Engineer with 5 years of experience specializing in scalable Python backend architectures and AI-driven systems...",
        "education": [
            {
                "degree": "Master of Science in Computer Software Engineering",
                "time_period": "Aug 2024 - May 2026",
                "school": "Arizona State University",
                "school_location": "Tempe, Arizona"
            }
        ],
        "experience": [
            {
                "role": "Software Engineer Intern",
                "team": "BIOS Development Software Team",
                "company": "Dell Technologies",
                "company_location": "Hybrid",
                "time_duration": "Jun 2025 - Aug 2025",
                "details": [
                    {
                        "title": "FastAPI & Agentic Workflow Architecture",
                        "description": "Architected a high-performance backend using FastAPI and Asyncio to orchestrate LangGraph-based Agentic workflows..."
                    }
                ]
            }
        ],
        "projects": [
            {
                "name": "Capstone Project: WeVibe - AI-Powered Matchmaking Platform",
                "time": "Jan 2026 -- Present",
                "description": "Led a cross-functional team as Scrum Master to develop a modern dating app..."
            }
        ],
        "patents": [],
        "skills": {
            "set1": {
                "title": "Backend & Architecture",
                "items": ["Python (FastAPI, Asyncio, Django, Pydantic)", "RESTful API Design"]
            }
        }
    }

if "ai_report" not in st.session_state:
    st.session_state.ai_report = ""

# ---------------------------------------------------------
# AI 核心邏輯 (ATS 關鍵字分析與履歷優化)
# ---------------------------------------------------------
def ai_optimize_and_update(jd_text, custom_prompt, enable_ats, check_visa):
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            return False, "⚠️ 錯誤：請先在左側欄位設定 GEMINI API KEY"
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        report_md = ""

        # 🛑 階段一：簽證審查
        if check_visa:
            visa_prompt = f"""
            請嚴格審查以下 Job Description (JD)。請檢查是否有以下任何一種情況：
            1. 明確要求必須是「美國公民」或「綠卡/永久居民」。
            2. 明確標示「不提供簽證贊助 (No visa sponsorship)」。
            直接回傳合法 JSON: {{"blocked": true/false, "reason": "..."}}
            [JD]: {jd_text}
            """
            visa_res = model.generate_content(visa_prompt)
            visa_json = json.loads(visa_res.text.replace('```json', '').replace('```', '').strip())
            
            if visa_json.get("blocked"):
                report_md += f"### ⛔ 簽證審查未通過\n**原因:** {visa_json.get('reason')}\n\n💡 建議：因為簽證限制，AI 已中斷後續履歷優化，請將精力留給下一家公司！"
                return False, report_md
            else:
                report_md += "✅ **簽證審查通過！未發現明確的身分阻礙。**\n\n---\n"

        # 🚀 階段二：ATS 關鍵字與履歷優化
        ats_instruction = ""
        ats_example = ""
        if enable_ats:
            ats_instruction = """
            - "keyword_analysis": 包含 "jd_keywords", "original_hits", "optimized_hits", "newly_added", "missing_keywords" (皆為字串陣列)。"""
            ats_example = """
            "keyword_analysis": {"jd_keywords": ["AWS", "Python"], "original_hits": ["Python"], "optimized_hits": ["Python", "AWS"], "newly_added": ["AWS"], "missing_keywords": []},"""

        final_prompt = f"""
        {custom_prompt}

        [目標職位 JD]: {jd_text}
        [原始履歷 JSON]: {json.dumps(st.session_state.resume_data, ensure_ascii=False)}

        🔥 【高級 ATS 關鍵字強制寫入與平移規則】：
        1. 技能平移：若 JD 要求 GCP，申請人有 AWS，請以「平移擴充」寫成 "AWS/GCP" 寫入 skills 或 summary。不准增加無關技術。
        2. 概念替換：巧妙替換經歷描述中的同義詞命中 ATS 字眼。
        3. ⚠️ 一致性鐵律：newly_added 中的字必須出現在 optimized_resume 中。

        ⚠️ 【輸出格式限制】：回傳合法 JSON，無 ``` 標籤。
        {{
            "changelog": "修改細節說明...",{ats_example}
            "optimized_resume": {{...更新後的完整履歷 JSON 結構...}}
        }}
        """
        
        response = model.generate_content(final_prompt)
        ai_result = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        
        modified_resume_data = ai_result.get("optimized_resume", {})
        if not modified_resume_data:
            return False, "⚠️ 解析錯誤：找不到優化後的履歷資料。"
            
        st.session_state.resume_data = modified_resume_data
        
        # 生成 Markdown 報告
        if enable_ats and "keyword_analysis" in ai_result:
            kw = ai_result["keyword_analysis"]
            tot = len(kw.get("optimized_hits", [])) + len(kw.get("missing_keywords", []))
            orig_c = len(kw.get("original_hits", []))
            opt_c = len(kw.get("optimized_hits", []))
            opt_pct = int((opt_c / tot) * 100) if tot > 0 else 0
            
            report_md += f"### 🎯 ATS 關鍵字匹配率 (Match Score)\n"
            report_md += f"- **優化前匹配度**: {orig_c} / {tot}\n"
            report_md += f"- **AI優化後匹配度**: {opt_c} / {tot} (**{opt_pct}%**)\n\n"
            
            report_md += "**✅ 成功命中的關鍵字:**\n"
            for k in kw.get("optimized_hits", []):
                if k in kw.get("newly_added", []):
                    report_md += f"- `{k}` 🌟 *(AI 已運用平移技術強制寫入)*\n"
                else:
                    report_md += f"- `{k}`\n"
            if kw.get("missing_keywords"):
                report_md += "\n**❌ 仍然缺乏的關鍵字:**\n"
                for k in kw.get("missing_keywords", []):
                    report_md += f"- `{k}`\n"
            report_md += "\n---\n"
            
        report_md += f"### 📝 修改日誌 (Changelog)\n{ai_result.get('changelog', '')}"
        
        return True, report_md
    except Exception as e:
        return False, f"⚠️ AI 執行過程發生錯誤: {e}"

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
            st.error(f"LaTeX 編譯失敗 (返回碼 {process.returncode})")
            with st.expander("查看編譯日誌"):
                st.text(stdout.decode('utf-8', errors='ignore'))
                st.text(stderr.decode('utf-8', errors='ignore'))
            return None
    except Exception as e:
        st.error(f"生成過程發生例外錯誤: {e}")
        return None

# ---------------------------------------------------------
# Streamlit UI 介面
# ---------------------------------------------------------
st.set_page_config(page_title="AI 履歷生成器", page_icon="🚀", layout="wide")

# --- 側邊欄 (Sidebar) 設定 API Key ---
with st.sidebar:
    st.header("⚙️ 設定 (Settings)")
    api_key_input = st.text_input("🔑 Google Gemini API Key", type="password", help="需要 API Key 才能使用 AI 潤飾功能")
    if api_key_input:
        st.session_state.api_key = api_key_input
    st.markdown("---")
    st.markdown("👉 [點此免費取得 Gemini API Key](https://aistudio.google.com/app/apikey)")

st.title("🚀 AI 履歷生成器 (AI-Powered Resume Builder)")
st.write("結合 Gemini AI 與 LaTeX，快速撰寫、排版並匯出高質感 PDF 履歷。")

tab1, tab2, tab3, tab4 = st.tabs(["1️⃣ 使用者基本資料", "2️⃣ AI 客製化", "3️⃣ AI 調整報告", "4️⃣ 下載履歷與預覽"])

# --- 1. 使用者基本資料 Tab ---
with tab1:
    st.header("👤 編輯您的基礎履歷資料")
    st.info("您可以在此直接編輯底層的 JSON 資料。修改後請務必點擊下方「儲存修改」。")
    
    json_str = json.dumps(st.session_state.resume_data, indent=4, ensure_ascii=False)
    edited_json = st.text_area("履歷 JSON 結構", value=json_str, height=500)
    
    if st.button("💾 儲存 JSON 修改", type="primary"):
        try:
            st.session_state.resume_data = json.loads(edited_json)
            st.success("JSON 資料已成功儲存！")
        except Exception as e:
            st.error(f"JSON 格式錯誤，請檢查語法: {e}")

# --- 2. AI 客製化 Tab ---
with tab2:
    st.header("🤖 根據 JD 自動優化履歷")
    col1, col2 = st.columns(2)
    enable_ats = col1.checkbox("開啟 ATS 關鍵字分析", value=True)
    check_visa = col2.checkbox("檢查簽證/Sponsorship 限制", value=True)
    
    jd_input = st.text_area("📄 貼上目標職缺的 Job Description (JD)", height=250)
    custom_prompt = st.text_area("🗣️ 您的特殊指令 (Optional)", value="請幫我把經歷修得更具侵略性與影響力，並著重在系統優化與微服務的關鍵字。")
    
    if st.button("🚀 開始執行 AI 優化與分析", type="primary"):
        if not jd_input:
            st.warning("請先貼上 JD 內容！")
        else:
            with st.spinner("AI 正在深度分析並進行 ATS 平移改寫，這可能需要 30~60 秒..."):
                success, report = ai_optimize_and_update(jd_input, custom_prompt, enable_ats, check_visa)
                st.session_state.ai_report = report
                if success:
                    st.success("優化完成！請前往「3️⃣ AI 調整報告」查看結果。")
                else:
                    st.error("優化中斷或發生錯誤，請查看報告細節。")

# --- 3. AI 調整報告 Tab ---
with tab3:
    st.header(" AI 執行結果與 ATS 報告")
    if st.session_state.ai_report:
        st.markdown(st.session_state.ai_report)
        st.info("💡 優化後的內容已自動套用至「使用者基本資料」中，您可以隨時前往修改或直接生成 PDF。")
    else:
        st.write("尚未執行 AI 優化。請先在「2️⃣ AI 客製化」填寫 JD 並執行。")

# --- 4. 預覽與下載 Tab ---
with tab4:
    st.header("🖨️ 生成與下載 PDF 履歷")
    st.write("您可以選擇上傳自己的 `.tex` 模板，或直接使用系統預設的模板進行編譯。")
    
    uploaded_tex = st.file_uploader("上傳自訂的 main.tex (選填)", type=["tex"])
    
    if st.button("編譯並產生 PDF 履歷", type="primary"):
        with st.spinner("正在雲端呼叫 LaTeX 引擎編譯中..."):
            tex_bytes = uploaded_tex.getvalue() if uploaded_tex else None
            pdf_path = generate_pdf_from_json(st.session_state.resume_data, tex_bytes)
            
            if pdf_path:
                st.success("✅ PDF 生成成功！")
                with open(pdf_path, "rb") as f:
                    st.download_button("📥 點此下載履歷 (resume.pdf)", f, file_name="resume.pdf", mime="application/pdf")