# 三視圖資訊架構重構 — 設計文件

日期：2026-08-15
狀態：已與使用者確認設計方向，待實作

## 問題

`app.py` 目前用一條五格導航列（`WORKSPACES`, app.py:994）當作主導航：

```python
WORKSPACES = [
    ("Source",  "Source",   len(resume_data["experience"]) > 0),
    ("Target",  "Target",   len(jd_text) > 50),
    ("ATS",     "Analysis", optimized_resume_data is not None),
    ("Review",  "Review",   resume_preview_bytes is not None),
    ("Tracker", "Tracker",  logged_in),
]
```

這條 bar 同時承擔兩種不相容的角色：

- `Source` 與 `Tracker` 是**目的地** — 使用者會主動想去的地方。
- `Target` / `ATS` / `Review` 是**同一件事的三個階段** — 它們的 `done` 條件（JD 是否夠長、有無優化結果、有無 PDF bytes）描述的是「這一份投遞做到哪了」，不是位置。

把階段當成導航，使用者每投一份工作就必須手動點過四到五格，而且下一份工作要整輪重來。這是使用者回報「一直切換很不喜歡」的直接成因。

## 目標

1. 導航收斂成三個真正的目的地。
2. 投遞進度從導航列抽離，改為右側常駐狀態面板。
3. 預覽與 ATS 回饋在編輯過程中持續可見，不需切換視圖。
4. 使用者設定（API key、進階工具、Reset、登出）收進 sidebar 底部的帳號區塊。

## 非目標

- 瀏覽器 extension（已討論，另立規格，實作順序在本次重構之後）。
- 更換部署平台或移除 LaTeX 依賴（另議）。
- 視覺上完全複刻參考設計稿。見〈已接受的 Streamlit 限制〉。

## 資訊架構

導航三項，放在 sidebar。`active_view` 存的是右欄的內部值，顯示文字是左欄的標籤：

| 顯示標籤 | `active_view` 值 | 內容 | 來源 |
|---|---|---|---|
| **Career Profile** | `Profile` | base 履歷的 PDF 匯入與表單編輯 | 現在的 `Source` 視圖 |
| **Generator** | `Generator` | 主要工作區，見下 | 現在的 `Target` + `ATS` + `Review` |
| **Tracker** | `Tracker` | 投遞紀錄與面試進度 | 現在的 `Tracker` 視圖，不動 |

首次進入的預設視圖依 base 履歷是否為空決定：空的落在 `Profile`（新使用者要先建資料），有內容則落在 `Generator`（回訪使用者要的是投下一份）。判斷直接用現有的 `resume_is_empty()`。目前寫死預設 `Source` 對回訪使用者是多一次點擊。

`Career Profile` 保留兩個入口：sidebar 常駐項目，以及 Generator 頁面上方 `Source of Truth` 區塊裡的捷徑。兩者導向同一個視圖。

## Generator 版面

`st.columns([6, 4])`，左為工作區、右為常駐面板。

### 左欄（工作區，由上而下）

1. **Source of Truth 區塊** — 顯示目前 base 履歷的摘要（幾段經歷、幾個學歷）與 `Edit Career Profile →` 捷徑。
2. **Job Description** — 即現有的 `jd_text` 輸入，維持既有的 durable key 寫法（`jd_input_{base_editor_key}` 鏡射回 `st.session_state.jd_text`），這個模式是為了修正切換視圖時 JD 被清空的問題，不能動。
3. **Custom Strategy** — 收進 `st.expander`，預設收合。多數使用者不會改。
4. **Optimize 主按鈕**。
5. **優化結果操作區** — `Edit Optimized JSON` 按鈕。此按鈕呼叫 `edit_opt_dialog()`，必須留在任何 fragment 之外，因為編輯結果要傳播到整份 script。

### 右欄（常駐面板，`@st.fragment`）

1. **投遞進度**（垂直清單，純狀態顯示，不可點）
   - JD 已貼上 — `len(jd_text) > 50`
   - 已優化 — `optimized_resume_data is not None`
   - PDF 已產生 — `resume_preview_bytes is not None`
   - 已記錄到 Tracker — `tracked_application_id is not None`（新狀態，見下）

   前三項直接沿用 `WORKSPACES` 現有的判斷式，邏輯不重寫。

2. **Export Settings** — 現有的 `render_export_settings` fragment（Template 下拉、Order 多選、Generate PDF 按鈕），移入右欄。

3. **Preview / ATS 分頁** — `st.tabs`
   - Preview：現有的 `render_preview` fragment，保留其中的 `Resume / Cover Letter` 切換與 `Render all pages` 預設關閉的行為。
   - ATS：現在 `ATS` 視圖的分析內容。

4. **下載按鈕**與自動記錄，見下節。

未優化前，右欄仍然顯示（不是隱藏或跳警告）：進度條照常呈現未完成狀態，Preview 區顯示空狀態文字，取代目前 `Review` 視圖裡的 `st.warning("Optimize first.")`。

## 狀態與資料流變更

### `active_view`

值域從 `{Source, Target, ATS, Review, Tracker}` 縮為 `{Profile, Generator, Tracker}`。需連帶修改：

- 預設值（目前 `"Source"`）。
- `WORKSPACES` 常數與 `nav_cols` 迴圈，改為 sidebar 導航。
- **`set_result_banner` 的 `actions` 參數帶的是目標視圖名稱**（例如 app.py 中 PDF 匯入成功後的 `actions=[("Add a job description", "Target")]`）。`render_result_banner` 會把它寫進 `st.session_state.active_view`。所有這類字面值都必須一起更新，否則點下去會導向不存在的視圖，畫面變成空白。

### Tracker 自動記錄（含去重）

目前行為（`render_preview`）：

```python
sync = st.checkbox("Sync to Tracker", value=True) if logged_in else False
st.download_button(..., on_click=sync_application_to_tracker if sync and ch=="Resume" else None)
```

改為下載時自動記錄，移除 checkbox。**但必須同時加去重保護。**

`save_application`（firebase_dashboard.py:130）以 `db.collection(...).document()` 產生隨機 doc ID，沒有任何去重。目前的 checkbox 加上「僅 Resume 觸發」的條件，是意外擋住了重複寫入。一旦改成自動，使用者下載兩次、或先後下載履歷與求職信，就會產生多筆重複紀錄。

作法：

- 新增 session 狀態 `tracked_application_id`。
- 下載觸發同步前先檢查此值，已存在則跳過寫入。
- `clear_generated_outputs()` 內重設為 `None` — 一次新的優化代表一份新的投遞。
- 讓求職信的下載也能觸發記錄（去重保護之後就安全了），使用者只下載求職信時不再漏記。

### 進階工具的去處

`show_advanced_tools` 目前控制三處面板：Source 的 `Advanced JSON Import`、ATS 的 `Manual Result Import`、Review 的 `Manual Data Import`。重構後：

- `Advanced JSON Import` 留在 Career Profile。
- 另外兩個併入 Generator 左欄底部的單一進階 expander。
- 開關本身從 sidebar 移到帳號／設定區塊。

### Sidebar

只保留：品牌區塊、三項導航、底部帳號區塊。

帳號區塊未登入時顯示登入／註冊表單入口；已登入時顯示使用者信箱與可展開的設定（API key、進階工具開關、Reset All Data、登出）。登入表單不可收進摺疊區，未登入的使用者需要看見明顯入口。

### 不可更動的既有行為

- `autosave_profile()` 必須維持在 script 最後執行，這樣寫回 Firestore 的才是本次 run 的編輯結果。
- JD 與 Custom Strategy 鏡射進 durable session key 的寫法。
- `edit_opt_dialog()` 呼叫點留在 fragment 之外。
- `render_export_settings` 產生 PDF 後用 app-scope `st.rerun()`，讓同層的 preview fragment 取得新 bytes；fragment-scope rerun 到不了。

## 已接受的 Streamlit 限制

參考設計稿並非 Streamlit 產物，以下三點不實作，屬於刻意取捨：

1. **帳號區塊不釘在 sidebar 底部。** Streamlit sidebar 是正常文件流，釘底需要依賴其內部 class name 做 CSS hack。本專案已經被平台自動升級 Python 版本咬過一次（見 requirements.txt 的註解），不再疊加依賴內部 DOM 的脆弱實作。改為放在 sidebar 自然順序的最下方。
2. **不做子項目縮排的分組導航。** 只有三個項目，不需要分組。
3. **右欄無法真正免於重繪。** `@st.fragment` 只限制 fragment 內部互動的 rerun 範圍；使用者在左欄輸入時整份 script 仍會重跑。要盯住的是 PDF 不要在每次按鍵重新光柵化 — `Render all pages` 預設關閉的既有行為必須一併帶進新版面。

## 驗證項目

實作完成後須逐項確認：

- [ ] 三項導航皆可正常切換，且切換後 JD 與 Custom Strategy 內容不遺失。
- [ ] 全新 session（無 base 履歷）落在 Career Profile；已有履歷的使用者登入後落在 Generator。
- [ ] 由 PDF 匯入履歷後，結果橫幅的動作按鈕導向 Generator（不是已不存在的 `Target`）。
- [ ] 未優化時 Generator 右欄正常顯示進度與空狀態，不出現例外。
- [ ] 優化後右欄 Preview 與 ATS 兩個分頁都有內容。
- [ ] 連續下載履歷與求職信各一次，Tracker 只新增**一筆**紀錄。
- [ ] 重新執行一次 Optimize 後再下載，Tracker 新增第二筆。
- [ ] 未登入狀態下下載不報錯，也不嘗試寫入 Firestore。
- [ ] 登出後再登入，profile 正常載入且不被 autosave 覆寫成空值。

## 後續

本次重構完成後，再進行瀏覽器 extension（擷取 JD → 帶入 Generator）。三視圖架構讓 extension 的落點單一明確，因此順序上必須在後。
