# Chrome Web Store 上架資料

把下面每一段直接貼進 Chrome Web Store 開發人員主控台的對應欄位。
上架流程本身見本檔最後的「送出步驟」。

---

## Item name（項目名稱，最多 75 字元）

```
AI Resume Builder 側邊欄
```

## Summary（簡短說明，最多 132 字元）

```
在側邊欄開啟 AI Resume Builder，一鍵把眼前的職缺描述帶進履歷產生器，不用切分頁複製貼上。
```

## Description（詳細說明）

```
看職缺和改履歷本來是兩件要一直切分頁的事。這個擴充功能把 AI Resume Builder 放進
Chrome 的側邊欄，讓它和職缺頁並排，再加一顆按鈕把眼前那頁的內容直接送進 Job
description 欄位。

功能
• 在側邊欄開啟完整的 AI Resume Builder，登入、優化、PDF 預覽都在裡面
• 一鍵抓取目前分頁的職缺描述並自動填入
• 不做站別解析 —— 整頁文字交給 AI 自己判斷，所以任何求職網站都能用
• 填不進去時自動改為複製到剪貼簿，功能不會因此中斷

需要準備
• 一個 AI Resume Builder 帳號（在 app 內免費註冊）
• 你自己的 Google Gemini API 金鑰（app 內填寫，免費取得）

隱私
這個擴充功能不儲存任何東西。沒有資料庫、沒有分析追蹤、沒有自己的伺服器。只有在你
按下抓取按鈕的當下才會讀取網頁，讀到的文字只會進到 AI Resume Builder，不會送到
其他任何地方。讀取網頁的權限是選用的，安裝時不會授予，第一次按下按鈕時 Chrome 才
會詢問你。

原始碼公開：
https://github.com/NSYSUHermit/AI_Resume_-_Cover_Letter_Generator/tree/main/extension
```

## Category

`Productivity`（生產力工具）

## Language

`Chinese (Traditional)`

## Privacy policy URL

```
https://github.com/NSYSUHermit/AI_Resume_-_Cover_Letter_Generator/blob/main/extension/PRIVACY.md
```

> 這個網址要能公開開啟才會過審。推之前先確認 repo 是 public；若是 private，
> 改用 GitHub Pages 或任何公開網頁貼上 `PRIVACY.md` 的內容。

## Visibility

選 **Unlisted（不公開）**。不會出現在商店搜尋結果，只有拿到連結的人裝得到，
但仍是正規安裝：一鍵完成、沒有開發人員模式警告、會自動更新。

---

## Single purpose（單一用途說明）

審核必填。照抄：

```
The extension has one purpose: to open the AI Resume Builder web app in Chrome's
side panel and transfer the text of the job posting the user is currently
reading into that app's job-description field.
```

## Permission justifications（權限使用說明）

每一項權限都要單獨填寫理由。照抄：

**`sidePanel`**
```
The extension's entire function is to display the AI Resume Builder web app in
Chrome's side panel alongside a job posting. Without this permission there is no
product.
```

**`tabs`**
```
When the user clicks the grab button in the side panel, the extension needs to
know which tab the user is currently reading in order to grab the job posting
from the correct page. Only the active tab's identity and URL are used, and only
at the moment of the click.
```

**`scripting`**
```
Used to read the visible text (document.body.innerText) of the job posting the
user is reading, so it can be placed into the app's job-description field. It is
injected only in direct response to the user clicking the grab button, never in
the background.
```

**`cookies`**
```
The web app is served by Streamlit Cloud, which sets its session cookie with
SameSite=Lax. A Lax cookie is not sent from a cross-site iframe, so every request
the app makes from inside the side panel is redirected to a login page and the
panel renders blank. The extension rewrites only that one attribute, on only its
own app's domain (henry-ai-resume-builder.streamlit.app), so the app can load.
No cookie is ever read for its contents or transmitted anywhere.
```

**`clipboardWrite`**
```
Fallback path. If the grabbed text cannot be inserted into the app's input field
directly, the extension copies it to the clipboard instead and tells the user to
paste it, so the feature degrades to something usable rather than failing.
```

**`host_permissions` — the app's own domains**
```
henry-ai-resume-builder.streamlit.app is the app the side panel displays;
share.streamlit.io is the Streamlit Cloud endpoint its session handshake
redirects through. Both are required for the panel to load the app at all.
```

**`optional_host_permissions` — `<all_urls>`**
```
Job postings are published on many different sites (LinkedIn, Indeed, 104,
company career pages, ...), so the page the user wants to grab from cannot be
enumerated in advance. This is declared as an OPTIONAL permission: it is not
granted at install time. Chrome prompts for it the first time the user presses
the grab button, and the extension's other features work without it.
```

## Data usage disclosures（資料使用聲明）

在 Privacy practices 分頁勾選：

- **Does your item collect user data?** → **Yes**
- 資料類型只勾 → **Website content**
  （抓到的職缺文字。不要勾其他項：這個擴充功能不碰個人識別資訊、
  健康資訊、財務資訊、認證資訊、位置或使用者活動）

三項聲明全部勾選（都屬實）：
- ☑ 不會將使用者資料販售給第三方
- ☑ 不會將使用者資料用於與項目單一用途無關的目的
- ☑ 不會將使用者資料用於判定信用度或放貸用途

---

## 截圖（至少 1 張，1280×800 或 640×400）

**這一張必須你自己截，不能由我代勞** —— 商店列表的截圖必須是產品實際的樣子，
合成一張假的會誤導安裝者。

拍法：

1. 開一個職缺頁（LinkedIn、104 都行）
2. 點擴充功能圖示打開側邊欄，把它往左拉寬一點
3. 登入、切到 Generator，按一次「抓取這頁的 JD」，讓 Job description 欄位有內容
4. 截整個瀏覽器視窗，裁成 1280×800

這一張要同時看得到職缺頁和側邊欄，因為那正是這個產品的價值主張。

---

## 送出步驟

1. 到 <https://chrome.google.com/webstore/devconsole> 註冊開發人員帳號
   （**US$5 一次性費用**，不是年費）
2. 執行 `python3 package.py` 產生 `dist/ai-resume-sidepanel-0.1.0.zip`
3. 主控台按 **Add new item**，上傳那個 zip
4. 填入本檔上面的每一段
5. Visibility 選 **Unlisted**
6. 送出審核。要求 `<all_urls>` 的項目通常需要**數天到兩週**；因為這裡已經降級成
   optional 權限，會比列為必要權限順利得多
7. 過審後把商店連結傳給朋友即可

## 之後要更新版本時

`manifest.json` 的 `version` 一定要往上加（例如 `0.1.0` → `0.1.1`），
否則主控台會拒絕上傳。重新執行 `package.py`，上傳新的 zip。
朋友端會自動更新，不用做任何事。
