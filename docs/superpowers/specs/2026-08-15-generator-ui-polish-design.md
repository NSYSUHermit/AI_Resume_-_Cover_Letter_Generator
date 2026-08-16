# Generator 版面精修 — 設計與實作計畫

日期：2026-08-15
分支：`feat/generator-ui-polish`（自 `main` @ `4d2ff0b`）
前置：三視圖資訊架構重構（PR #2，已合併）

## 目標

使用者對合併後的 Generator 版面提出八項調整。本文件把它們拆成可實作的變更，並記錄兩個必須偏離字面需求的技術理由。

## 使用者需求與可行性分類

| # | 需求 | 判定 |
|---|---|---|
| 1 | 生成後有可直接編輯內容的 draft table | 原生 `st.data_editor` |
| 2 | 右欄只有 PDF 預覽本身 | 版面調整 |
| 3 | 預覽左上角切換 Resume / Cover Letter | 原生 `st.segmented_control` |
| 4 | 預覽右上角下載按鈕 | 版面調整 |
| 5 | 畫面太空白 | CSS 密度 + 四項具體調整 |
| 6 | 進度條改成中央上方懸浮 bar | CSS `position: fixed` |
| 7 | 小人一路走到最後一步的動畫 | 自包含 SVG + CSS |
| 8 | 中間可拖曳調整左右寬度 | **Streamlit 做不到** |

### 需求 8 的裁決：分段控制取代拖曳

`st.columns` 的比例在 render 當下固定，Streamlit 沒有拖曳 API。真正的拖曳需要一個雙向的 React custom component（node 建置鏈、打包進 repo、拉長 Streamlit Cloud 的 build 時間），或是用 JS 改寫 Streamlit 內部 DOM——後者依賴內部 class name，而本專案已被平台自動升級咬過兩次（見 `requirements.txt` 的註解）。

使用者裁決：改用三段預設比例的 `st.segmented_control`，放在 Generator 右上角。

```python
PANEL_RATIOS = {
    "Wide preview":   (4, 6),
    "Even":           (5, 5),
    "Wide workspace": (7, 3),
}
```

預設 `Even`。選擇存進 `st.session_state.panel_ratio`，一次點擊即到位，零 DOM 依賴。

## 兩個必須偏離字面需求的地方

### 一、未優化前的預覽必須快取，不能急切編譯

需求是「未優化前右欄就先放目前履歷的預覽」。直覺作法是每次進 Generator 就呼叫 `generate_preview_pdf_bytes(resume_data, ...)`——但那會 `subprocess.run(['lualatex', ...])`，是本 app 最昂貴的動作，在 Streamlit Cloud 的共用 CPU 上每次 rerun 都付一次數秒的代價，等於用一個裝飾性需求換掉整個 app 的反應速度。

作法：把 base 履歷的預覽包進 `@st.cache_data`，以 `resume_snapshot(resume_data)`（回傳 JSON 字串，可雜湊）加上樣板名稱與段落順序當 key。

```python
@st.cache_data(show_spinner=False, max_entries=8)
def base_preview_pdf(snapshot, template_name, block_order):
    """Base 履歷的預覽。

    以 snapshot 字串當 key，履歷沒變就不會重新編譯。lualatex 要跑好幾秒，
    在每次 rerun 都編譯一次會讓整個 app 失去反應。
    """
    return generate_preview_pdf_bytes(json.loads(snapshot), template_name, block_order)
```

第一次進 Generator 付一次編譯成本，之後只要履歷沒改就是免費。履歷為空時直接跳過，顯示空狀態而非編譯一份空白 PDF。

### 二、生成過程保留真實里程碑，只換視覺

需求是「生成過程的動畫很怪」。目前 `ui_feedback.py` 的 `run_ai_call` 用 `st.status` 串流**真實的里程碑**（"Reading the saved job description..." 等），它的 docstring 明確記載這是刻意的設計：不用假進度條，讓使用者看到真的階段落地。

把它換成純裝飾動畫是資訊上的降級。作法是保留訊息、換掉視覺：面板改為緊湊樣式，左側放與懸浮 bar 同一個小人 SVG，做原地踏步動畫，右側是最新的里程碑文字。

註：AI 呼叫是同步阻塞的，整份 script 在呼叫期間不會重跑，因此懸浮 bar 本身無法在生成中改變狀態——`st.status` 是唯一會在該期間串流更新的元件。這是保留它的第二個理由。

## 懸浮進度條

固定於視窗頂端置中，位於 Streamlit 自身工具列之下。四個站點取自既有的 `workspace.application_progress()`，判斷邏輯不重寫。

小人的水平位置 = 最後一個已完成階段的索引。腿部用兩組路徑以 CSS `steps()` 交替顯示做出走路循環，另加輕微的上下擺動。全部是自包含的 SVG 與 keyframes，不觸及任何 Streamlit 內部 class name。

版面上必須為固定定位的 bar 在主容器頂端保留空間，否則會蓋住內容。

## 密度調整（使用者選定四項全做）

1. **全域縮小間距與內邊距** — 區塊間距、container padding、標題上下距離。
2. **未優化前右欄顯示 base 履歷預覽** — 見上節的快取規定。
3. **JD 輸入框變矮** — 由 260px 降至 140px，讓 draft table 不必捲動就看得到。
4. **左欄加入快速統計卡片** — 幾段經歷、ATS 分數、已投遞筆數，填掉 Source of Truth 上方的空白。

## 右欄最終形態

只有 PDF 本身，加上兩個控制項：

- 左上：`st.segmented_control` 切換 Resume / Cover Letter
- 右上：下載按鈕（維持既有的自動記錄接線與去重守衛，不得更動）

`render_export_settings`（樣板選擇、段落順序、Generate PDF）從右欄移到左欄底部。ATS 分頁一併移到左欄的 draft table 之下。

## 不得更動的既有行為

- `autosave_profile()` 必須是 `app.py` 最後一個語句。
- JD 與 Custom Strategy 鏡射進 durable session key 的寫法（規格層級的不可動項，已有回歸測試保護）。
- `edit_opt_dialog()` 的呼叫點在任何 fragment 之外。
- `render_export_settings` 產生 PDF 後用 app-scope `st.rerun()`。
- 下載時的自動記錄與 `tracked_application_id` 去重守衛，含三個手動匯入點的重設。
- `render_preview` 的 `Render all pages` 預設 `False`。
- `workspace.py` 不得 import streamlit。

## 任務拆解

**Task 1 — 懸浮進度條與小人動畫**
新增 CSS 至 `app.py` 既有的樣式表（742-923 行）與一個 `render_floating_progress()` 函式；移除 `render_generator_panel` 內的垂直進度清單。進度資料沿用 `workspace.application_progress()`。

**Task 2 — 右欄改為純 PDF**
左上切換、右上下載、Export Settings 與 ATS 移出至左欄，未優化時顯示快取的 base 履歷預覽。下載路徑的記錄接線不得更動。

**Task 3 — Draft table 與左欄密度**
優化結果改用 `st.data_editor` 呈現為可直接編輯的表格；JD 框降至 140px；加入快速統計卡片。

**Task 4 — 比例分段控制、全域密度、生成中的視覺**
`st.segmented_control` 三段比例；全域間距 CSS；`ui_feedback.run_ai_call` 改為緊湊面板配踏步小人，訊息內容不變。

## 驗證

既有 35 項測試必須維持通過——它們涵蓋導航、JD 保存、Tracker 去重與手動匯入重設，這些都是本次版面調整容易誤傷的地方。

新增涵蓋：
- 比例分段控制切換後 `panel_ratio` 正確變更且不拋例外。
- 未優化時 Generator 右欄渲染不呼叫 lualatex 超過一次（以 cache 命中驗證）。
- Draft table 編輯後寫回 `optimized_resume_data`。

無法本機驗證（需真實瀏覽器）：懸浮 bar 的實際定位與小人動畫的視覺表現、`position: fixed` 是否與 Streamlit 工具列衝突。列為部署後確認項。
