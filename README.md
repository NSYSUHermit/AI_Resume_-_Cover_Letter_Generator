# 🚀 AI-Powered Resume Builder

This is a cloud-based resume generation tool developed using **Streamlit**. It combines the powerful text processing capabilities of **Google Gemini AI** with the professional typesetting engine of **LuaLaTeX**.

👨‍💻 **Developed by [NSYSUHermit](https://github.com/NSYSUHermit)**

## ✨ Core Features

1. **Friendly UI & Data Protection**
   - An intuitive interface that separates your "Base Profile" from "AI-Optimized Results" to prevent accidental overwrites.
   - Manages data via standardized JSON format.

2. **AI Smart Collaboration & ATS Optimization**
   - Integrates Gemini API to provide one-click experience rewriting, keyword injection, and visa sponsorship screening.
   - Translates casual descriptions into professional, impactful bullet points.
   - Simulates ATS (Applicant Tracking System) logic to shift and inject keywords seamlessly.

3. **Cloud LaTeX Compilation**
   - Automatically binds JSON data to LaTeX templates using `Jinja2` in the background.
   - Calls LuaLaTeX to compile high-quality PDF resumes directly in the cloud.

## 🛠️ Tech Stack

- **Frontend/Backend**: Streamlit (Python)
- **AI Engine**: Google Generative AI (Gemini API)
- **Template Engine**: Jinja2
- **PDF Generation Engine**: TeX Live (LuaLaTeX)
- **Environment**: Streamlit Community Cloud + GitHub

## 📂 Project Structure

```text
.
├── app.py              # Main Streamlit application
├── main.tex            # Main LaTeX resume template
├── requirements.txt    # Python dependencies
├── packages.txt        # Ubuntu system dependencies (TeX environment)
└── README.md           # Documentation
```

## 🚀 部署指南 (Deployment Guide)

本專案針對 **Streamlit Community Cloud** 進行了最佳化配置：

1. 將本專案 Fork 或 Clone 到個人的 GitHub 儲存庫。
2. 前往 Streamlit Cloud，並連結你的 GitHub 帳號。
3. 選擇本專案的 Repository，設定主程式為 `app.py`。
4. 點擊 `Deploy`，Streamlit 會自動讀取 `packages.txt` 安裝 LuaLaTeX，並安裝 `requirements.txt` 中的 Python 套件。
5. 部署完成後，打開網頁，即可在**左側邊欄 (Sidebar) 輸入個人的 Gemini API Key** 來啟用 AI 功能！

## 📝 待辦事項 (Roadmap)

- [x] 定義履歷的 JSON 基礎資料結構。
- [x] 撰寫/尋找合適的 LaTeX 履歷模板 (`main.tex`)。
- [x] 實作 Streamlit UI 表單與 Gemini AI 潤飾功能。
- [x] 實作 JSON 到 LaTeX 的渲染與 PDF 編譯邏輯。