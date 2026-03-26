# 🚀 AI 履歷生成器 (AI-Powered Resume Builder)

這是一個基於 **Streamlit** 開發的雲端履歷生成工具。結合了 **Google Gemini AI** 的強大文字處理能力，以及 **LuaLaTeX** 的專業排版引擎，讓使用者能透過友善的網頁介面，輕鬆撰寫、優化並匯出高質感的 PDF 履歷。

## ✨ 核心功能 (Core Features)

1. **友善的使用者介面 (Friendly UI)**
   - 直覺的表單設計，讓使用者輕鬆輸入履歷資料（個人資訊、學歷、經歷、技能等）。
   - 將資料轉換為標準化的 JSON 格式進行管理。

2. **AI 智能協作 (AI Collaboration)**
   - 整合 Gemini API，提供一鍵「經歷潤飾」、「關鍵字優化」或「翻譯」功能。
   - 幫助使用者將口語化的經歷轉換為專業、具吸引力的職場描述。

3. **雲端高品質排版 (Cloud LaTeX Compilation)**
   - 背景自動透過 `Jinja2` 將 JSON 資料注入至預先設計好的 LaTeX 模板。
   - 雲端無縫呼叫 LuaLaTeX 進行編譯，直接生成高質感的 PDF 供使用者下載。

## 🛠️ 技術架構 (Tech Stack)

- **前端/後端框架**: Streamlit (Python)
- **AI 引擎**: Google Generative AI (Gemini API)
- **資料模板綁定**: Jinja2
- **PDF 生成引擎**: TeX Live (LuaLaTeX)
- **部署環境**: Streamlit Community Cloud + GitHub

## 📂 專案檔案結構 (Project Structure)

```text
.
├── app.py              # Streamlit 網頁主程式（UI 介面、AI 互動與 PDF 生成邏輯）
├── main.tex            # LaTeX 履歷主模板（使用 Jinja2 語法標記變數）
├── requirements.txt    # Python 依賴套件 (streamlit, google-generativeai, jinja2)
├── packages.txt        # Ubuntu 系統依賴套件（告訴 Streamlit Cloud 安裝 TeX 環境）
└── README.md           # 專案說明文件
```

## 🚀 部署指南 (Deployment Guide)

本專案針對 **Streamlit Community Cloud** 進行了最佳化配置：

1. 將本專案 Fork 或 Clone 到個人的 GitHub 儲存庫。
2. 前往 Streamlit Cloud，並連結你的 GitHub 帳號。
3. 選擇本專案的 Repository，設定主程式為 `app.py`。
4. **重要**：在部署設定的 `Advanced settings` -> `Secrets` 中加入你的 Gemini API Key：
   ```toml
   GEMINI_API_KEY = "你的_API_KEY_填在這裡"
   ```
5. 點擊 `Deploy`，Streamlit 會自動讀取 `packages.txt` 安裝 LuaLaTeX，並安裝 `requirements.txt` 中的 Python 套件。

## 📝 待辦事項 (Roadmap)

- [x] 定義履歷的 JSON 基礎資料結構。
- [x] 撰寫/尋找合適的 LaTeX 履歷模板 (`main.tex`)。
- [x] 實作 Streamlit UI 表單與 Gemini AI 潤飾功能。
- [x] 實作 JSON 到 LaTeX 的渲染與 PDF 編譯邏輯。