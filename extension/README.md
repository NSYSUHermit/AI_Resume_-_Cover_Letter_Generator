# AI Resume Builder 側邊欄（Chrome 擴充功能）

在 Chrome 側邊欄開啟 <https://henry-ai-resume-builder.streamlit.app/>，並用一顆按鈕把
旁邊那個職缺頁的內容填進 Job description。

設計與技術背景見 [`../docs/superpowers/specs/2026-08-23-chrome-side-panel-design.md`](../docs/superpowers/specs/2026-08-23-chrome-side-panel-design.md)。

## 安裝

1. Chrome 開 `chrome://extensions`
2. 右上角打開「開發人員模式」
3. 點「載入未封裝項目」，選這個 `extension/` 資料夾
4. 把它釘到工具列（拼圖圖示 → 圖釘）

點工具列上的圖示就會開側邊欄。

## 使用

1. 在職缺頁（LinkedIn、Indeed、104…都行）點擴充功能圖示開側邊欄
2. 在側邊欄裡登入、貼上 Gemini API key
3. 切到 Generator
4. 點「抓取這頁的 JD」

整頁文字會被抓下來丟進 Job description —— 不做站別解析，哪些是職缺描述交給 Gemini 判斷。

## 發佈給別人

見 [`STORE_LISTING.md`](STORE_LISTING.md)：Chrome Web Store 每個欄位要填什麼、
權限使用說明的原文、送出步驟。用 **Unlisted（不公開）** 發佈 —— 不會出現在搜尋
結果，只有拿到連結的人裝得到，但一鍵安裝、會自動更新、沒有開發人員模式的警告列。

直接把資料夾傳給別人也可以，但對方每次開 Chrome 都會看到「請停用開發人員模式
擴充功能」的警告，而且不會自動更新。`.crx` 檔則完全行不通 —— Chrome 自 2018 年
起封鎖所有非商店來源的 `.crx` 安裝。

## 檔案

執行時（會被打包進 zip）：

| 檔案 | 職責 |
|---|---|
| `manifest.json` | MV3 宣告 |
| `background.js` | 開側邊欄；持續把 `streamlit_session` 從 `SameSite=Lax` 改寫成 `None` |
| `sidepanel.html` / `.css` | 工具列 + 裝著網站的 iframe |
| `sidepanel.js` | 抓取、轉送、剪貼簿退路、選用權限的要求 |
| `filler.js` | Content script，把文字填進 Streamlit 的 textarea |
| `icons/icon*.png` | 工具列圖示，沿用 app 自己的 `.sb-logo` 標記 |

開發用（不會進 zip）：

| 檔案 | 職責 |
|---|---|
| `package.py` | 產生可上傳的 zip（白名單制，不是忽略清單） |
| `icons/make_icons.py` | 重新產生圖示 |
| `PRIVACY.md` | 隱私權政策，審核必填的公開網址指向這裡 |
| `STORE_LISTING.md` | 商店列表文案與送審步驟 |

## 權限

讀取網頁的 `<all_urls>` 是**選用權限**：安裝時不會授予，第一次按下「抓取這頁的
JD」時 Chrome 才會詢問。拒絕的話，除了抓取按鈕以外的功能都照常運作。這樣審核好過
很多，隱私上本來也該如此。

## 三個已知的坑

**版面會很擠。** `app.py:1736` 有 `@media (max-width: 900px)` 的警告：窄螢幕下編輯器與
PDF 預覽不會正確排版。Chrome 側邊欄預設約 320–500px，所以那條警告在側邊欄裡會一直掛著，
而且它說的是實話。把側邊欄往左拉寬會好一些。要真正解決得改 `app.py`（放寬斷點，或做一個
側邊欄專用的單欄模式），不在這次範圍。

**側邊欄一關就登出。** Streamlit 的登入狀態只活在 `st.session_state`（`app.py:68`），
沒有 cookie 也沒有 token，所以重新整理就登出，而關閉側邊欄會銷毀 iframe，等同重新整理。
這是網站本身的性質，不是擴充功能造成的；修法要改 `app.py`，刻意不在這次範圍內。

**填不進去時會退到剪貼簿。** `filler.js` 能不能被注入到擴充功能頁面裡的 iframe，
是這個設計唯一沒把握的一點。收不到回應時，側邊欄會把整頁文字複製到剪貼簿並提示你
自己貼上 —— 這是設計好的第二條路，不是壞掉。

## 第一次開啟會很慢

Streamlit Cloud 的免費方案會讓 app 休眠，冷啟動要數十秒，這段時間側邊欄是一片空白。
不是壞掉，等一下就好。（我第一次測的時候就被這個騙過去，誤以為是 iframe 被擋。）

## 驗收清單

1. 點圖示會開側邊欄
2. 側邊欄裡的網站**有內容而不是空白**（cookie 改寫生效）
3. 網站在側邊欄裡能登入、能操作
4. 在職缺頁點「抓取這頁的 JD」，文字出現在 Job description 欄位
5. 若第 4 點失敗，工具列出現剪貼簿提示，貼上後內容正確

## 換網址

`background.js`、`sidepanel.js` 的 `APP_ORIGIN`／`APP_HOST`，以及 `manifest.json`
的 `host_permissions` 和 `content_scripts.matches` 各有一份網址，四處都要改。
