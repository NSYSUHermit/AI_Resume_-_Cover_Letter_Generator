import streamlit as st
import google.generativeai as genai
import jinja2
import subprocess
import os

# ---------------------------------------------------------
# 初始化 Session State (JSON 資料結構)
# ---------------------------------------------------------
if "resume_data" not in st.session_state:
    st.session_state.resume_data = {
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "+1 234 567 8900",
        "linkedin": "linkedin.com/in/janedoe",
        "github": "github.com/janedoe",
        "summary": "A highly motivated software engineer with experience in developing scalable web applications.",
        "education": [
            {"school": "State University", "degree": "B.S. in Computer Science", "location": "New York, NY", "duration": "Aug 2018 - May 2022"}
        ],
        "experience": [
            {
                "company": "Tech Solutions Inc.",
                "title": "Software Engineer",
                "location": "San Francisco, CA",
                "duration": "Jun 2022 - Present",
                "details": [
                    "Developed and maintained microservices using Python and FastAPI.",
                    "Improved database query performance by 30%."
                ]
            }
        ],
        "skills": [
            {"category": "Programming Languages", "items": "Python, JavaScript, SQL, C++"}
        ]
    }

# ---------------------------------------------------------
# AI 潤飾功能邏輯
# ---------------------------------------------------------
def polish_experience(draft_text):
    try:
        api_key = st.session_state.get("api_key", "")
        if not api_key:
            st.error("👈 請在左側欄位 (Sidebar) 中輸入您的 GEMINI API KEY")
            return []
            
        genai.configure(api_key=api_key)
        # 使用最新 gemini-1.5-flash 模型，速度快且效果好
        model = genai.GenerativeModel('gemini-1.5-flash') 
        
        prompt = f"""
        You are an expert resume writer. I will give you a rough draft of my work experience.
        Please rewrite it into 2 to 4 professional, impactful, action-oriented bullet points suitable for a resume.
        Focus on achievements and metrics where possible.
        
        Draft:
        {draft_text}
        
        Output ONLY the bullet points, each starting with a hyphen (-) and separated by a new line. Do not include any intro or outro text.
        """
        
        response = model.generate_content(prompt)
        # 處理回傳文字，移除開頭的 '-' 與多餘空白
        bullets = [line.strip().lstrip('-').strip() for line in response.text.split('\n') if line.strip()]
        return bullets
    except Exception as e:
        st.error(f"AI 潤飾發生錯誤: {e}")
        return []

# ---------------------------------------------------------
# PDF 生成邏輯 (Jinja2 + LuaLaTeX)
# ---------------------------------------------------------
def generate_pdf_from_json(data):
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
        template = latex_jinja_env.get_template('main.tex')
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

tab1, tab2, tab3, tab4, tab5 = st.tabs(["基本資料", "學歷", "工作經歷", "技能", "預覽與下載"])

# --- 基本資料 Tab ---
with tab1:
    st.header("👤 基本資料 (Basic Info)")
    col1, col2 = st.columns(2)
    st.session_state.resume_data["name"] = col1.text_input("全名", st.session_state.resume_data["name"])
    st.session_state.resume_data["email"] = col2.text_input("Email", st.session_state.resume_data["email"])
    st.session_state.resume_data["phone"] = col1.text_input("電話", st.session_state.resume_data["phone"])
    st.session_state.resume_data["linkedin"] = col2.text_input("LinkedIn 網址", st.session_state.resume_data["linkedin"])
    st.session_state.resume_data["github"] = col1.text_input("GitHub 網址", st.session_state.resume_data["github"])
    st.session_state.resume_data["summary"] = st.text_area("個人簡介 (Summary)", st.session_state.resume_data["summary"])

# --- 學歷 Tab ---
with tab2:
    st.header("🎓 學歷 (Education)")
    # 為了簡化展示，目前綁定第一筆學歷。若需多筆可擴充動態新增按鈕。
    edu = st.session_state.resume_data["education"][0]
    edu["school"] = st.text_input("學校名稱", edu["school"])
    edu["degree"] = st.text_input("學位", edu["degree"])
    edu["location"] = st.text_input("地點", edu["location"])
    edu["duration"] = st.text_input("就讀期間", edu["duration"])

# --- 工作經歷 Tab ---
with tab3:
    st.header("💼 工作經歷 (Experience)")
    exp = st.session_state.resume_data["experience"][0]
    col1, col2 = st.columns(2)
    exp["company"] = col1.text_input("公司名稱", exp["company"])
    exp["title"] = col2.text_input("職稱", exp["title"])
    exp["location"] = col1.text_input("地點", exp["location"], key="exp_loc")
    exp["duration"] = col2.text_input("任職期間", exp["duration"], key="exp_dur")
    
    st.subheader("工作內容描述 (AI 協作)")
    draft = st.text_area("在這裡用白話文描述你的工作內容（例如：我負責寫Python爬蟲，幫公司提升了效率）")
    if st.button("✨ 讓 AI 幫我潤飾成專業條列式"):
        if draft:
            with st.spinner("Gemini AI 正在思考中..."):
                polished_bullets = polish_experience(draft)
                if polished_bullets:
                    exp["details"] = polished_bullets
                    st.success("潤飾成功！已自動更新至履歷資料中。")
    
    exp["details"] = st.text_area("工作經歷條列 (請用換行分隔)", "\n".join(exp["details"])).split("\n")

# --- 預覽與下載 Tab ---
with tab5:
    st.header("🖨️ 生成 PDF")
    if st.button("編譯並產生 PDF 履歷", type="primary"):
        with st.spinner("正在雲端呼叫 LaTeX 引擎編譯中..."):
            pdf_path = generate_pdf_from_json(st.session_state.resume_data)
            if pdf_path:
                st.success("✅ PDF 生成成功！")
                with open(pdf_path, "rb") as f:
                    st.download_button("📥 點此下載履歷 (resume.pdf)", f, file_name="resume.pdf", mime="application/pdf")