# 三視圖資訊架構重構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `app.py` 的五格步驟式導航收斂成三個目的地（Career Profile / Generator / Tracker），投遞進度改為 Generator 右側常駐面板。

**Architecture:** 導航與進度的判斷邏輯抽到新的 `workspace.py`（純函式、不 import streamlit）以便單元測試；`app.py` 只負責把這些決定畫出來。Generator 用 `st.columns([6, 4])` 分成左工作區與右常駐面板，既有的 `render_export_settings` / `render_preview` 兩個 fragment 原封不動搬進右欄。

**Tech Stack:** Streamlit 1.61.1、pytest、Streamlit `AppTest`（`streamlit.testing.v1`）、Firestore（`firebase-admin`）。

## Global Constraints

- `workspace.py` **不得** import streamlit。它的存在理由就是能在不執行 UI 的情況下被測試。
- 介面文案一律英文，與現有 UI 一致（`Source of Truth`、`Optimize Resume` 等）。程式註解沿用現有中英混用習慣。
- `autosave_profile()` 必須維持在 `app.py` 最後一行執行。
- JD 與 Custom Strategy 必須維持鏡射進 durable session key（`jd_input_{base_editor_key}` → `st.session_state.jd_text`）的寫法。這是為了修正切換視圖時 JD 被清空的既有 bug。
- `edit_opt_dialog()` 的呼叫點必須留在任何 `@st.fragment` 之外。
- `render_export_settings` 產生 PDF 後必須用 app-scope `st.rerun()`，fragment-scope 到不了同層的 preview fragment。
- 每個 Task 結尾都要 commit。

---

### Task 1: 建立 workspace.py 與測試基礎

**Files:**
- Create: `workspace.py`
- Create: `tests/test_workspace.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Consumes: 無（第一個任務）
- Produces:
  - `workspace.PROFILE = "Profile"`、`workspace.GENERATOR = "Generator"`、`workspace.TRACKER = "Tracker"`
  - `workspace.VIEWS` — tuple of `(view_value, label, icon)`
  - `workspace.initial_view(resume_is_empty) -> str`
  - `workspace.application_progress(jd_text, has_optimized, has_pdf, is_tracked) -> list[tuple[str, bool]]`

- [ ] **Step 1: 把本機 streamlit 對齊 requirements 的釘選版本**

本機目前是 1.37.1，`app.py` 用到的 `st.button(icon=...)` 需要 1.42+，所以現在本機**跑不起來 app.py**，後續所有 `AppTest` 步驟都會失敗。先修這個。

```bash
pip install "streamlit==1.61.1" pytest
```

驗證：

```bash
python3 -c "import streamlit; print(streamlit.__version__)"
```

Expected: `1.61.1`

- [ ] **Step 2: 建立 requirements-dev.txt**

pytest 只在本機需要，不能放進 `requirements.txt` — 那份是 Streamlit Community Cloud 部署時安裝的清單，多裝東西只會拖慢 build。

```
# 本機開發用。部署不會讀這份。
-r requirements.txt
pytest==8.3.4
```

- [ ] **Step 3: 寫失敗的測試**

Create `tests/test_workspace.py`:

```python
import workspace


def test_new_user_lands_on_profile():
    assert workspace.initial_view(resume_is_empty=True) == workspace.PROFILE


def test_returning_user_lands_on_generator():
    assert workspace.initial_view(resume_is_empty=False) == workspace.GENERATOR


def test_views_are_exactly_three_in_order():
    assert [view for view, _, _ in workspace.VIEWS] == [
        workspace.PROFILE,
        workspace.GENERATOR,
        workspace.TRACKER,
    ]


def test_progress_starts_all_incomplete():
    steps = workspace.application_progress(
        jd_text="", has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert [done for _, done in steps] == [False, False, False, False]


def test_short_jd_does_not_count_as_added():
    steps = workspace.application_progress(
        jd_text="too short", has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert steps[0][1] is False


def test_long_jd_counts_as_added():
    steps = workspace.application_progress(
        jd_text="x" * 51, has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert steps[0][1] is True


def test_missing_jd_is_treated_as_empty():
    steps = workspace.application_progress(
        jd_text=None, has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert steps[0][1] is False


def test_progress_labels_are_in_application_order():
    steps = workspace.application_progress(
        jd_text="", has_optimized=False, has_pdf=False, is_tracked=False
    )
    assert [label for label, _ in steps] == [
        "Job description added",
        "Resume optimized",
        "PDF generated",
        "Saved to tracker",
    ]


def test_all_four_stages_can_be_complete():
    steps = workspace.application_progress(
        jd_text="x" * 51, has_optimized=True, has_pdf=True, is_tracked=True
    )
    assert all(done for _, done in steps)
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `python3 -m pytest tests/test_workspace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workspace'`

- [ ] **Step 5: 寫最小實作**

Create `workspace.py`:

```python
"""Pure decision logic for the three-view workspace.

This lives outside app.py because app.py is a top-level Streamlit script:
importing it executes the entire UI, so none of the rules below could be
tested in place. Nothing here may import streamlit.
"""

PROFILE = "Profile"
GENERATOR = "Generator"
TRACKER = "Tracker"

# (active_view value, sidebar label, material icon)
VIEWS = (
    (PROFILE, "Career Profile", ":material/person:"),
    (GENERATOR, "Generator", ":material/auto_awesome:"),
    (TRACKER, "Tracker", ":material/monitoring:"),
)

# Matches the threshold the old workspace bar used: a couple of words pasted by
# accident is not a job description.
_JD_MIN_LENGTH = 50


def initial_view(resume_is_empty):
    """Where a session lands before the user navigates anywhere.

    New users have nothing to generate from, so they start on the profile.
    Returning users came back to send another application.
    """
    return PROFILE if resume_is_empty else GENERATOR


def application_progress(jd_text, has_optimized, has_pdf, is_tracked):
    """The four stages of one application, as (label, done) pairs.

    Returned in the order they happen; the caller just renders the list.
    """
    return [
        ("Job description added", len(jd_text or "") > _JD_MIN_LENGTH),
        ("Resume optimized", bool(has_optimized)),
        ("PDF generated", bool(has_pdf)),
        ("Saved to tracker", bool(is_tracked)),
    ]
```

- [ ] **Step 6: 執行測試確認通過**

Run: `python3 -m pytest tests/test_workspace.py -v`
Expected: PASS，8 passed

- [ ] **Step 7: Commit**

```bash
git add workspace.py tests/test_workspace.py requirements-dev.txt
git commit -m "feat: 抽出 workspace 導航與進度判斷邏輯

app.py 是 top-level Streamlit script，import 就會執行整個 UI，
判斷邏輯留在裡面無法測試。抽成純函式模組。"
```

---

### Task 2: Tracker 去重守衛

這是本次重構風險最高的一段。`save_application`（firebase_dashboard.py:130）用 `db.collection(...).document()` 產生隨機 doc id，**沒有任何去重**。目前 `render_preview` 裡的 `Sync to Tracker` checkbox 加上「只有下載 Resume 才觸發」的條件，是意外擋住了重複寫入。把 checkbox 拿掉之前，必須先有這個守衛。

**Files:**
- Modify: `workspace.py`
- Modify: `tests/test_workspace.py`

**Interfaces:**
- Consumes: Task 1 的 `workspace` 模組
- Produces: `workspace.should_record_application(is_tracked, logged_in) -> bool`

- [ ] **Step 1: 寫失敗的測試**

追加到 `tests/test_workspace.py` 末尾：

```python
def test_logged_out_user_never_records():
    assert workspace.should_record_application(is_tracked=False, logged_in=False) is False


def test_first_download_records():
    assert workspace.should_record_application(is_tracked=False, logged_in=True) is True


def test_second_download_does_not_record_again():
    assert workspace.should_record_application(is_tracked=True, logged_in=True) is False


def test_logged_out_user_with_stale_flag_still_does_not_record():
    assert workspace.should_record_application(is_tracked=True, logged_in=False) is False
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python3 -m pytest tests/test_workspace.py -v`
Expected: FAIL — `AttributeError: module 'workspace' has no attribute 'should_record_application'`

- [ ] **Step 3: 寫最小實作**

追加到 `workspace.py` 末尾：

```python
def should_record_application(is_tracked, logged_in):
    """Whether a download should write a new tracker row.

    save_application() writes with an auto-generated document id and does no
    deduplication at all, so without this guard a user who downloads the resume
    and then the cover letter — or who just downloads twice — gets one tracker
    row per click. One optimize run is one application.
    """
    return bool(logged_in) and not is_tracked
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m pytest tests/test_workspace.py -v`
Expected: PASS，12 passed

- [ ] **Step 5: Commit**

```bash
git add workspace.py tests/test_workspace.py
git commit -m "feat: 加上 Tracker 記錄去重守衛

save_application 用隨機 doc id 且不去重，現有的 Sync to Tracker
checkbox 是意外擋住重複寫入。改成自動同步前先補這個保護。"
```

---

### Task 3: sidebar 三項導航

**Files:**
- Modify: `app.py:81`（`active_view` 預設值）
- Modify: `app.py:517`、`app.py:1057`（banner actions 的目標視圖名稱）
- Modify: `app.py:775` 起（sidebar）
- Modify: `app.py:994-1019`（移除 `WORKSPACES` 橫向導航列）
- Modify: `app.py:1026`、`1088`、`1169`、`1324`、`1357`（視圖判斷字面值）
- Create: `tests/test_app_smoke.py`

**Interfaces:**
- Consumes: `workspace.VIEWS`、`workspace.initial_view`、`workspace.PROFILE/GENERATOR/TRACKER`
- Produces: `st.session_state.active_view` 值域收斂為 `{"Profile", "Generator", "Tracker"}`

- [ ] **Step 1: 寫失敗的 smoke test**

Create `tests/test_app_smoke.py`:

```python
from streamlit.testing.v1 import AppTest


def run_app():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    return at


def test_app_runs_without_exception():
    at = run_app()
    assert not at.exception


def test_sidebar_has_exactly_three_nav_buttons():
    at = run_app()
    nav_keys = [b.key for b in at.sidebar.button if b.key and b.key.startswith("nav_")]
    assert nav_keys == ["nav_Profile", "nav_Generator", "nav_Tracker"]


def test_empty_profile_lands_on_career_profile():
    at = run_app()
    assert at.session_state.active_view == "Profile"


def test_clicking_tracker_switches_view():
    at = run_app()
    at.sidebar.button(key="nav_Tracker").click().run()
    assert at.session_state.active_view == "Tracker"


def test_clicking_generator_switches_view():
    at = run_app()
    at.sidebar.button(key="nav_Generator").click().run()
    assert at.session_state.active_view == "Generator"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python3 -m pytest tests/test_app_smoke.py -v`
Expected: FAIL — 導航按鈕還在主畫面不在 sidebar，`nav_keys` 會是 `[]`；`active_view` 是 `"Source"`。

- [ ] **Step 3: 匯入 workspace 並改預設視圖**

在 `app.py` 既有的 import 區塊加入：

```python
import workspace
```

把 `app.py:81` 這行：

```python
if "active_view" not in st.session_state: st.session_state.active_view = "Source"
```

改成（注意：必須放在 `resume_data` 初始化**之後**，因為要讀它）：

```python
if "active_view" not in st.session_state:
    st.session_state.active_view = workspace.initial_view(
        resume_is_empty(st.session_state.resume_data)
    )
```

- [ ] **Step 4: 登入成功後重算落點**

session_state 初始化時使用者還沒登入，`resume_data` 一定是空的，所以上一步對回訪使用者永遠算出 `Profile`。在 sidebar 登入處理的 `mark_profile_synced()` 之前補上：

```python
st.session_state.active_view = workspace.initial_view(
    resume_is_empty(st.session_state.resume_data)
)
```

- [ ] **Step 5: 移除橫向導航列，改成 sidebar 導航**

刪掉 `app.py:994-1019` 的 `WORKSPACES` 常數與 `nav_cols` 迴圈（連同其下的 `st.markdown("---")`），只保留：

```python
active_view = st.session_state.active_view
```

在 sidebar 的品牌區塊（`st.caption("Resume, cover letter, and application tracking.")`）之後插入：

```python
    st.caption("WORKSPACE")
    for view, label, icon in workspace.VIEWS:
        if st.button(
            label,
            key=f"nav_{view}",
            use_container_width=True,
            type="primary" if st.session_state.active_view == view else "secondary",
            icon=icon,
        ):
            st.session_state.active_view = view
            # Rerun rather than falling through: the sidebar has already drawn
            # itself for the previous view, so without this the highlight and
            # the content below would disagree until the next interaction.
            st.rerun()
    st.markdown("---")
```

- [ ] **Step 6: 把設定收進 sidebar 底部的帳號區塊**

sidebar 現有順序是：品牌 → 登入區 → API Settings → 進階工具開關 → Reset All Data → 署名。改成：品牌 → **導航** → 分隔線 → 帳號區塊（登入區 / 已登入資訊）→ 設定 expander → 署名。

把 `API Settings`、`Show advanced import tools`、`Reset All Data` 三段包進一個 expander，放在帳號區塊之下：

```python
    with st.expander("Settings"):
        st.markdown("**API Settings**")
        if st.session_state.api_key:
            st.success("Gemini key connected")
            if st.button("Change key", use_container_width=True):
                st.session_state.api_key = ""
                st.rerun()
        else:
            st.caption("Add your Gemini key in the main panel to turn on the AI features.")

        st.checkbox(
            "Show advanced import tools",
            key="show_advanced_tools",
            help="Paste raw JSON in and out of the app. Not needed for normal use.",
        )

        # Deferred: session_state cannot be written for a key whose widget has
        # already been instantiated this run.
        if st.button("Reset All Data", use_container_width=True, type="secondary"):
            st.session_state.pending_reset = True
            st.rerun()
```

登入／註冊表單**不要**放進這個 expander — 未登入的使用者需要看到明顯入口。它留在 expander 上方。

- [ ] **Step 7: 更新視圖判斷字面值**

五處視圖判斷改成三處：

```python
if active_view == workspace.PROFILE:      # 原 "Source"
if active_view == workspace.GENERATOR:    # 原 "Target"，Task 4 會把 ATS/Review 併進來
if active_view == workspace.TRACKER:      # 原 "Tracker"
```

原本的 `if active_view == "ATS":` 與 `if active_view == "Review":` 兩個區塊**先改成 `workspace.GENERATOR`**，讓它們暫時跟 Target 一起渲染。Task 4、5 才會真正整併版面。這樣每個 Task 結束時 app 都是能跑的。

- [ ] **Step 8: 更新 banner actions**

`app.py:517`：

```python
        actions=[("See ATS breakdown", "ATS"), ("Generate PDF", "Review")],
```

這兩個目標視圖都不存在了，而且重構後 ATS 與 PDF 都在 Generator 右欄、使用者已經看得到。整個 `actions` 參數移除：

```python
        actions=[],
```

`app.py:1057`：

```python
                    actions=[("Add a job description", "Target")],
```

改成：

```python
                    actions=[("Add a job description", workspace.GENERATOR)],
```

- [ ] **Step 9: 執行測試確認通過**

Run: `python3 -m pytest tests/ -v`
Expected: PASS，全部通過（12 + 5 = 17 passed）

- [ ] **Step 10: Commit**

```bash
git add app.py tests/test_app_smoke.py
git commit -m "refactor: 導航從五格步驟列改成 sidebar 三個目的地

Source/Tracker 是目的地，Target/ATS/Review 是同一件事的階段。
把階段當導航是使用者一直切換的成因。設定收進帳號區塊的 expander。"
```

---

### Task 4: Generator 左欄

**Files:**
- Modify: `app.py`（Generator 區塊）

**Interfaces:**
- Consumes: `workspace.PROFILE`、`workspace.GENERATOR`、既有的 `resume_is_empty()`、`edit_opt_dialog()`
- Produces: `render_generator_workspace()` — 直接畫在當前 container，回傳 `(jd, strategy)` 兩個字串供同函式內的優化按鈕使用

原 Career Profile 視圖裡的 `Advanced JSON Import` **留在原地不動**，本任務只搬 ATS 與 Review 的兩個 manual import。

- [ ] **Step 1: 抽出左欄函式**

在 Generator 區塊之前新增（**不加 `@st.fragment`** — Optimize 按鈕需要 app-scope rerun 讓右欄跟著更新）：

```python
def render_generator_workspace():
    """Generator 的左欄：資料來源、JD、策略、優化按鈕。"""
    with st.container(border=True):
        st.markdown("**Source of Truth**")
        data = st.session_state.resume_data
        if resume_is_empty(data):
            st.caption("Your Career Profile is empty. Build it first — every rewrite starts from it.")
        else:
            st.caption(
                f"Career Profile  ·  {len(data.get('experience') or [])} roles"
                f"  ·  {len(data.get('education') or [])} schools"
            )
        if st.button("Edit Career Profile", use_container_width=True, icon=":material/arrow_forward:"):
            st.session_state.active_view = workspace.PROFILE
            st.rerun()
```

- [ ] **Step 2: 把 JD 與策略搬進來**

接在同一個函式內，沿用現有的 durable key 寫法（**不可改動**，這是修過的 bug）：

```python
    st.markdown("**Target & Strategy**")
    jd = st.text_area(
        "Job description",
        value=st.session_state.jd_text,
        height=260,
        key=f"jd_input_{st.session_state.base_editor_key}",
        placeholder="Paste the job description here...",
    )
    with st.expander("Custom Strategy"):
        strategy = st.text_area(
            "Strategy",
            value=st.session_state.custom_prompt,
            height=200,
            key=f"cp_input_{st.session_state.base_editor_key}",
            label_visibility="collapsed",
        )
    st.session_state.jd_text = jd
    st.session_state.custom_prompt = strategy
    return jd, strategy
```

- [ ] **Step 3: 搬入優化按鈕與 Copy Prompt**

原 Target 視圖從 `if not st.session_state.api_key:` 那行起，到 `components.html(...)` 呼叫結束為止（`app.py:1116-1168` 一帶，以 `c1, c2 = st.columns(2)` 為錨點）整段搬進 `render_generator_workspace()` 結尾，程式碼一字不改 — `jd`、`strategy` 在函式內已經是區域變數，名稱與原本相同。

搬完後函式最後一行是：

```python
    return jd, strategy
```

- [ ] **Step 4: 搬入 Edit Optimized JSON**

原 Review 視圖裡這段搬到左欄，接在優化按鈕之後：

```python
    if st.session_state.optimized_resume_data:
        if optimized_result_is_stale():
            st.warning("Source JSON has changed since the current optimized result was created. Re-run Optimize Resume before generating a new PDF.")
        # The dialog stays outside the fragment: editing the resume has to
        # propagate to the whole script, not just this box.
        if st.button("Edit Optimized JSON", use_container_width=True):
            edit_opt_dialog()
```

`render_generator_workspace()` 本身沒有 `@st.fragment`，所以這個呼叫點自動符合「留在 fragment 之外」的約束。

- [ ] **Step 5: 搬入進階工具**

原 ATS 視圖的 `Manual Result Import` 與原 Review 視圖的 `Manual Data Import`，兩個 expander 併到左欄最下方，維持 `if st.session_state.get("show_advanced_tools"):` 的條件包裹。Career Profile 的 `Advanced JSON Import` 不要動。

- [ ] **Step 6: 接上 Generator 區塊**

```python
if active_view == workspace.GENERATOR:
    render_generator_workspace()
```

（右欄在 Task 5 才加。）

- [ ] **Step 7: 執行測試確認沒壞**

Run: `python3 -m pytest tests/ -v`
Expected: PASS，17 passed

手動確認：

```bash
streamlit run app.py
```

在 Generator 貼入超過 50 字的 JD，切到 Career Profile 再切回來，**JD 內容必須還在**。

- [ ] **Step 8: Commit**

```bash
git add app.py
git commit -m "refactor: Target/ATS/Review 的輸入面併成 Generator 左欄"
```

---

### Task 5: Generator 右欄常駐面板

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `workspace.application_progress`、`TOKENS`（已由 `from theme import TOKENS, FONT_STACK` 匯入）、既有的 `render_export_settings()`、`render_preview()`
- Produces:
  - `render_generator_panel()` — 畫右欄，無回傳值
  - `render_ats_analysis()` — 從原 ATS 視圖抽出的分析內容，無回傳值，呼叫端負責判斷有無優化結果

- [ ] **Step 1: 寫進度面板**

```python
def render_generator_panel():
    """Generator 的右欄：進度、輸出設定、預覽與 ATS。"""
    st.caption("THIS APPLICATION")
    for label, done in workspace.application_progress(
        jd_text=st.session_state.jd_text,
        has_optimized=st.session_state.optimized_resume_data is not None,
        has_pdf=st.session_state.resume_preview_bytes is not None,
        is_tracked=st.session_state.get("tracked_application_id") is not None,
    ):
        icon = "check_circle" if done else "radio_button_unchecked"
        colour = TOKENS["success"] if done else TOKENS["muted"]
        st.markdown(
            f":material/{icon}: <span style='color:{colour}'>{label}</span>",
            unsafe_allow_html=True,
        )
    st.markdown("---")
```

`TOKENS` 已經在 `app.py` 由 `from theme import TOKENS, FONT_STACK` 匯入，`success` 與 `muted` 兩個 key 都存在，不需另外處理。

- [ ] **Step 2: 讓 Generate PDF 在沒有優化結果時停用**

`render_export_settings()` 裡的 Generate PDF 按鈕原本靠 Review 視圖外層的 `if st.session_state.optimized_resume_data:` 保護。右欄現在永遠顯示，那層保護不見了，按下去會在 `d.get('target_company')` 炸掉。按鈕改成：

```python
        if st.button(
            "Generate PDF",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.optimized_resume_data is None,
        ):
```

- [ ] **Step 3: 加上 Preview / ATS 分頁**

接在 `render_generator_panel()` 內：

```python
    render_export_settings()

    preview_tab, ats_tab = st.tabs(["Preview", "ATS"])
    with preview_tab:
        render_preview()
    with ats_tab:
        if st.session_state.optimized_resume_data:
            render_ats_analysis()
        else:
            st.caption("Optimize a resume to see how it scores against the job description.")
```

原 ATS 視圖裡 `if st.session_state.optimized_resume_data:` 之後的分析內容，抽成 `render_ats_analysis()` 函式。

- [ ] **Step 4: 接上左右欄**

```python
if active_view == workspace.GENERATOR:
    left, right = st.columns([6, 4])
    with left:
        render_generator_workspace()
    with right:
        render_generator_panel()
```

`edit_opt_dialog()` 的呼叫點確認仍在 fragment 之外。

- [ ] **Step 5: 執行測試**

Run: `python3 -m pytest tests/ -v`
Expected: PASS，17 passed

- [ ] **Step 6: 手動確認空狀態**

```bash
streamlit run app.py
```

全新 session 進 Generator：右欄要正常顯示四項未完成的進度、Generate PDF 呈停用、ATS 分頁顯示空狀態文字，**不可出現例外**。

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: Generator 右欄常駐面板，進度與預覽不再需要切換視圖"
```

---

### Task 6: Tracker 自動記錄與驗收

**Files:**
- Modify: `app.py`（`clear_generated_outputs`、`sync_application_to_tracker`、`render_preview`）

**Interfaces:**
- Consumes: `workspace.should_record_application`
- Produces: `st.session_state.tracked_application_id`

- [ ] **Step 1: 新增 session 狀態**

在 session 初始化區塊（`app.py:60-80` 那批）加入：

```python
# 一次 optimize 就是一份投遞。save_application 不去重，靠這個值擋住重複寫入。
if "tracked_application_id" not in st.session_state: st.session_state.tracked_application_id = None
```

- [ ] **Step 2: 重新優化時重設**

`clear_generated_outputs()` 內加入：

```python
    st.session_state.tracked_application_id = None
```

- [ ] **Step 3: 讓同步函式帶上守衛**

`sync_application_to_tracker()` 改成：

```python
def sync_application_to_tracker():
    if not workspace.should_record_application(
        is_tracked=st.session_state.tracked_application_id is not None,
        logged_in=st.session_state.logged_in,
    ):
        return
    tracker_db = get_db()
    if tracker_db is None:
        st.error("Tracker is unavailable until Firebase secrets are configured.")
        return
    save_application(
        tracker_db,
        st.session_state.user_email,
        st.session_state.optimized_resume_data.get('target_company'),
        st.session_state.optimized_resume_data,
        st.session_state.get('jd_text', ""),
    )
    # 記下來就好，值本身只是「已記錄」的旗標。
    st.session_state.tracked_application_id = st.session_state.optimized_resume_data.get('target_company') or "recorded"
```

- [ ] **Step 4: 移除 checkbox，履歷與求職信都觸發**

`render_preview()` 內原本這兩行：

```python
            sync = st.checkbox("Sync to Tracker", value=True) if st.session_state.logged_in else False
            st.download_button(f"Download {dl['name']}", dl["bytes"], dl["name"], use_container_width=True, on_click=sync_application_to_tracker if sync and ch=="Resume" else None)
```

改成：

```python
            st.download_button(
                f"Download {dl['name']}",
                dl["bytes"],
                dl["name"],
                use_container_width=True,
                on_click=sync_application_to_tracker,
            )
            if st.session_state.logged_in:
                st.caption("Downloading records this application in the tracker.")
```

守衛已經處理未登入與重複兩種情況，這裡不需要再判斷。

- [ ] **Step 5: 執行測試**

Run: `python3 -m pytest tests/ -v`
Expected: PASS，17 passed

- [ ] **Step 6: 逐項手動驗收**

`streamlit run app.py`，用真的 Firebase secrets 跑過規格裡的驗證清單：

- [ ] 三項導航皆可切換，切換後 JD 與 Custom Strategy 不遺失
- [ ] 全新 session（無 base 履歷）落在 Career Profile
- [ ] 已有履歷的使用者登入後落在 Generator
- [ ] 由 PDF 匯入履歷後，橫幅的「Add a job description」導向 Generator
- [ ] 未優化時 Generator 右欄正常顯示，不出現例外
- [ ] 優化後 Preview 與 ATS 兩個分頁都有內容
- [ ] **連續下載履歷與求職信各一次，Tracker 只新增一筆**
- [ ] **重新 Optimize 後再下載，Tracker 新增第二筆**
- [ ] 未登入下載不報錯，也不寫入 Firestore
- [ ] 登出後再登入，profile 正常載入且沒被 autosave 覆寫成空值

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: 下載時自動記錄投遞，一次 optimize 只記一筆

移除 Sync to Tracker checkbox。求職信下載現在也會記錄，
去重守衛確保不會因為下載兩份檔案而產生兩筆紀錄。"
```

---

## 已知會留下的限制

以下三點是設計時就決定不做的，實作時不要試圖繞過：

1. **帳號區塊不釘在 sidebar 底部** — Streamlit sidebar 是正常文件流，釘底需要依賴其內部 class name 做 CSS hack。本專案已被平台自動升級 Python 版本咬過一次（見 `requirements.txt` 註解），不再疊加依賴內部 DOM 的脆弱實作。
2. **不做子項目縮排的分組導航** — 只有三個項目，不需要分組。
3. **右欄無法真正免於重繪** — `@st.fragment` 只限制 fragment 內部互動的 rerun 範圍。使用者在左欄輸入時整份 script 仍會重跑。要盯的是 PDF 不要每次按鍵重新光柵化，`render_preview` 裡 `Render all pages` 預設關閉的行為必須保留。

## 後續

本重構完成後才做瀏覽器 extension（擷取 JD → 帶入 Generator）。三視圖架構讓 extension 的落點單一明確，順序上必須在後。
