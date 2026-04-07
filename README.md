# 🚀 AI-Powered Resume Builder

This is a cloud-based resume generation tool developed using **Streamlit**. It combines the powerful text processing capabilities of **Google Gemini AI** with the professional typesetting engine of **LuaLaTeX**.

👨‍💻 **Developed by [NSYSUHermit](https://github.com/NSYSUHermit)**
[Resume Builder](https://airesume-coverlettergenerator-oe32fupxk6xsnzybjnpecv.streamlit.app/)

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
- **Database & Auth**: Firebase (Firestore)
- **PDF Generation Engine**: TeX Live (LuaLaTeX) + embedded Lua scripting
- **Environment**: Streamlit Community Cloud + GitHub

## 🏗️ 系統架構與資料流 (Architecture & Data Flow)

### 1. 系統架構 (System Architecture)
本專案採用 **Server-side Rendering (SSR) 單體式架構**，以 Python/Streamlit 作為核心大腦，串接各項外部服務：
- **前端展示層 (Frontend)**：使用 `streamlit` 建立多頁籤 (Tabs) 介面，涵蓋履歷編輯、AI 最佳化、ATS 分析、PDF 輸出與求職追蹤。整合 `streamlit-ace` 提供語法高亮的 JSON 編輯器。
- **後端邏輯層 (Backend)**：依賴 `st.session_state` 暫存狀態。呼叫 `google.generativeai` (Gemini) 解析 Job Description (JD) 進行 ATS 關鍵字比對、簽證預檢與履歷重寫。
- **資料持久層 (Database)**：透過 `firebase_admin` 串接 Firestore，實作基於密碼雜湊的身分驗證系統、儲存使用者的 JSON 履歷與投遞歷史 (Dashboard)。

### 2. 核心資料流 (Data Flow)
- **階段一：初始化與資料同步**。使用者登入後，系統從 Firestore 拉取 `base_resume` (JSON) 並寫入前端的 Ace Editor 與系統狀態中。
- **階段二：AI 優化與 ATS 分析**。輸入目標職缺 (JD) 後，系統先進行簽證預檢 (Visa Check)，接著組合 Base Resume 與 JD 交給 Gemini 進行履歷重寫，並回傳優化後的履歷與 ATS 命中率。
- **階段三：LaTeX 編譯與 PDF 匯出**。系統將選定的 JSON 資料寫入本地 `ml_resume.json`，並呼叫底層 `lualatex` 命令。LaTeX 編譯期間，內嵌的 Lua 腳本 (`\begin{luacode*}`) 會動態讀取該 JSON 並注入至 LaTeX 排版中。
- **階段四：求職追蹤**。下載 PDF 時若勾選同步至 Firebase，會將該次投遞的公司、日期與履歷版本寫入 Firestore。儀表板 (Dashboard) 會即時查詢並計算 Conversion Rate 與渲染進度。

## 📂 Project Structure

```text
.
├── app.py                   # Main Streamlit application
├── firebase_dashboard.py    # Firebase Auth & Job Tracking Dashboard logic
├── main.tex                 # Main LaTeX resume template
├── elsa_main.tex            # Alternative LaTeX resume template
├── requirements.txt         # Python dependencies
├── packages.txt             # Ubuntu system dependencies (TeX environment)
└── README.md                # Documentation
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