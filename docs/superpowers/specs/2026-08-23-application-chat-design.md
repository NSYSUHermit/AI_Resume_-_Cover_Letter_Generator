# 申請問答對話框 — 設計

日期：2026-08-23
分支：`main`（未提交）

## 需求

使用者在填申請表單時會遇到自由作答的問題（「為什麼想來我們公司」、「描述一個你主導的專案」）。
需要一個對話框，帶著**個人 profile 與本次生成結果**當上下文，幫忙草擬答案。

擁有者的三項明確指示：

1. 放在 **Generator 左欄**（生成/調整側），不是預覽側
2. 上下文是個人資料 + 本次生成
3. 位置在 **draft table 之後**

## 範圍裁決

**對話只活在本次 session**（`st.session_state`），重新整理就消失。不寫 Firestore、不綁定投遞紀錄。

這跟 app 現有的行為一致：`logged_in`（`app.py:68`）與優化結果本來就不跨重整存活。
另一個選項是綁定 application 存進 Firestore，Tracker 裡可回看，但要登入、要新資料結構——
擁有者裁決先不做。

## 職責切分

`ai.py` 的模組 docstring 寫明它不碰 `session_state`，好讓同一套提示詞日後能被別的前端重用。
新功能照這個契約，也照它既有的 `build_*_prompt` / 呼叫函式分離模式：

| 函式 | 職責 |
|---|---|
| `APPLICATION_CHAT_RULES` | 具名常數的接地規則 |
| `MAX_CHAT_HISTORY = 20` | 歷史上限 |
| `build_application_chat_prompt(...)` | 純字串組裝，不連網，可單獨斷言 |
| `answer_application_question(...)` | 一輪對話，回 `(ok, text)` |
| `_generate_text(api_key, parts, temperature=0.3)` | 新 helper |

`_generate_text` 必須跟 `_generate_json` 分開，因為後者把 `response_mime_type` 釘死在
`application/json`——那對一段要貼進申請表單的散文完全是錯的。temperature 也不同：
0.1 適合從文件抽結構，寫關於自己的段落則過於呆板。

`answer_application_question` 回報錯誤而不是像 `predict_interview_questions` 那樣吞掉。
那個吞掉只是少顯示一個沒人要求的面板；對話框回不出東西又不解釋，就只是壞了，
而且呼叫端需要有東西可以放進泡泡裡。

## 提示詞：功能的本體

其餘都是管線。接地規則：

1. 只能用提供的資料作答
2. **需要的事實不在資料裡時不准編造**——講明缺哪一項並反問。絕不虛構雇主、職稱、日期、期間、數字、工具、技術
3. 優化後履歷已涵蓋的部分沿用其措辭，讓答案跟招募方正在讀的那份對得上
4. 用提問的語言回答
5. 預設輸出是可直接貼進表單的草稿，不是「你該怎麼回答」的建議

第 2 條是這個功能值不值得信任的分水嶺。求職申請上一個編造的數字不是品質瑕疵，
是掛著使用者名字送出去的假陳述，而且要到面試官追問那個數字時才會爆。

與 `EVIDENCE_RULES`（rewrite 用的）是同一個原則、不同表面，刻意不共用：
`EVIDENCE_RULES` 是寫給 JSON 轉換的（「記進 suggested_metrics」對一輪對話毫無意義），
而對話的第 2 條必須指出一個 rewrite 沒有對應物的補救動作（反問使用者）。合併會讓兩者都變鈍。

沒有優化結果時，該區塊填的是 `(none yet - the candidate has not run an optimization
for this job)` 而不是留空：空白區塊會誘導模型以為履歷載入失敗，明講則告訴它這是要繞過的正常狀態。

## UI

`render_application_chat()`，位於 Draft Table / Edit Optimized JSON 兩顆按鈕之後、
手動匯入工具之前。

**不以 `if optimized_resume_data` 為條件**。profile 加 JD 本身就能回答申請表單的許多問題
（「為什麼選這家」、「可到職時間」），而且加了條件反而會在新手最需要幫助時把它藏起來。

- 無 API key → `st.chat_input(disabled=True)` 加提示。每則回答都是一次 Gemini 往返，
  開著的輸入框只是誘使使用者打完一段話再吃錯誤
- **不用 `ui_feedback.run_ai_call`**：它會畫 `st.status` 面板或接管呼叫端的按鈕佔位，
  兩種形狀都不適合聊天泡泡；它的存在意義是串流真實里程碑，而這裡只有一次往返，
  所以單純的 `st.spinner` 才是誠實的
- 失敗訊息也寫進對話紀錄，不只顯示一次。下一次 rerun 會從 `session_state` 重畫，
  沒記錄的失敗會蒸發，留下使用者盯著自己沒被回答的問題
- `clear_generated_outputs()` 會清空對話——一次 Optimize 就是一次投遞，
  跟 `tracked_application_id` 同一條規則

### Streamlit 限制查證

`st.chat_input` 在 1.61.1 支援 inline 模式（原始碼：「can also be used inline by nesting it
inside any layout container (container, columns, tabs, sidebar, etc)」）。
用 AppTest 實測過同時放在 `st.columns` 與 `st.expander` 內皆無例外。只有 `st.form` 內不行。

## 測試

`tests/test_application_chat.py`，11 項。切分方式對應功能的兩半：

- **提示詞**（不連網）：四個接地來源都有到位、不准編造那條規則被釘住、缺優化結果時的措辭、歷史上限
- **接線**（AppTest）：只在 Generator 出現、無 key 時 disabled、一問一答都進紀錄、
  失敗也留紀錄、`clear_generated_outputs()` 會清空

不准編造那條規則被單獨釘成一個測試。其餘都可以自由改寫，那條不行。

## 未以瀏覽器驗證

AppTest 從不渲染真實 DOM，而本機跑不起這個 app（`init_firebase()` 需要 secrets）。
所以「對話泡泡在 400px 側邊欄裡長什麼樣」沒有被驗證過，部署後需人工確認一次。
