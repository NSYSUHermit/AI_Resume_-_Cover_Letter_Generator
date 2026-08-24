# Chrome 側邊欄擴充功能 — 設計

日期：2026-08-23
分支：`fix/render-all-pages`（自 `main`）
線上網址：`https://henry-ai-resume-builder.streamlit.app/`

## 目標

使用者在瀏覽職缺頁時，能在 Chrome 側邊欄直接開啟這個網站，並用一顆按鈕把旁邊那頁的內容抓進 Job description 欄位。

擁有者的兩項明確指示：

1. **側邊欄裡就是整個網站本人**——登入、Optimize、PDF 預覽全都在裡面，不是重做一份精簡版。
2. **JD 抓取不做站別解析**——`document.body.innerText` 整頁文字全抓，交給 Gemini 自己判斷哪些是職缺描述。

## 範圍界線

`app.py` 一行都不改。這是擁有者在權衡後的裁決：先把側邊欄做出來驗證想法，Streamlit 端的改動之後再談。

因此下面「已知會痛但這次不修」的問題**留著**：

> Streamlit 的登入狀態只活在 `st.session_state`（`app.py:68` 的 `logged_in`），沒有 cookie 也沒有 token，所以重新整理就登出。Chrome 側邊欄一關閉，iframe 就被銷毀，等同重新整理。側邊欄是一天開關數十次的介面，所以這個原本感覺不到的小毛病會被放大。修法是 app 端發 session token 存進 Firestore、擴充功能寫成 cookie 自動認人——但那要改 `app.py`，不在這次範圍。

## iframe 嵌入的可行性

實測（`example.com` 注入 iframe 指向本站）的結果：

| 觀察 | 結果 |
|---|---|
| `X-Frame-Options` / `frame-ancestors` | **沒有**。iframe 確實跨網域導過去了（`contentWindow` 探測丟 SecurityError 可證） |
| `GET /?embed=true`（無 cookie） | `200`，但回的是 Streamlit Cloud 的外殼載入頁（HTML 內全是 `/-/build/assets/…`） |
| `GET /_stcore/health`（**帶** `streamlit_session`） | `200` |
| `GET /_stcore/health`（**不帶** cookie） | `303` → `/-/login?payload=…` |
| `streamlit_session` 的屬性 | `Secure; HttpOnly; **SameSite=Lax**` |
| **跨網域 iframe 的實際渲染** | **正常。app 完整跑起來。** |

一開始的觀察是「iframe 永遠空白」，據此推論成因是 `SameSite=Lax` 的 cookie 在跨站
iframe 不會送出、於是每個 `/_stcore/*` 都被踢去登入。**這個推論後來被推翻**：那個空白
是 app 冷啟動造成的（Streamlit Cloud 的免費方案會休眠，喚醒要數十秒）。等 app 醒來，
同一個跨網域 iframe 就正常渲染了。

上表關於 cookie 的量測本身是真的，只是它不是空白畫面的成因。

### 仍然保留 cookie 改寫，當保險

`background.js` 仍然用 `chrome.cookies` 把 `streamlit_session` 重寫成
`sameSite: 'no_restriction'`（該 cookie 本來就是 `Secure`，符合 `SameSite=None` 的前提；
`chrome.cookies` 在有 host permission 時連 HttpOnly cookie 都讀得到）。

理由是**沒有證明它不需要**，而不是證明了它需要：`chrome-extension://` 的頂層情境跟
`https://example.com` 不完全相同，而失敗的代價（側邊欄一片空白）遠大於這段程式碼的成本。
它是非致命的 —— 失敗只會在工具列留一行警告，不會擋住載入。

不用 `declarativeNetRequest` 改寫 `Set-Cookie`，因為 DNR 的 `modifyHeaders` 只能設定固定值，
無法對既有 header 做正規式替換，而 session cookie 的值是動態的。MV3 也已移除 blocking 版的
`webRequest`。Streamlit Cloud 之後仍可能重新種下 Lax 版本，所以 service worker 掛
`chrome.cookies.onChanged` 持續修正，而不是只在開啟時修一次。

## `?embed=true` 會把 Streamlit 的 header 變成透明的空殼

量測同一個 app 在兩種網址下的 `[data-testid="stHeader"]`：

| | `backgroundColor` | 子元素 |
|---|---|---|
| 一般網址 | `rgb(248, 250, 252)` | 有 `stToolbar` |
| **`?embed=true`** | **`rgba(0, 0, 0, 0)`** | **無** |

`#gp-status-strip` 被釘在 `top: 3.75rem`，那個偏移是為了讓開 Streamlit 的工具列。
embed 模式下工具列不存在、header 又透明，那 60px 就變成一扇窗，捲上來的內容
（卡片邊框、metric 標籤、標題）全部從橫桿上方穿出去。

修法是我們自己把那條帶子畫上：`[data-testid="stHeader"] { background: var(--bg) !important; }`。
在一般網址下是 no-op（`var(--bg)` 就是 Streamlit 自己用的 `#f8fafc`），在 embed 下把窗關上。

**這個效果沒辦法用 `elementsFromPoint` 驗證** —— embed 模式的 header 同時帶著
`pointer-events: none`，命中測試無論它有沒有被畫都會直接走過去。只能截圖看。

## 已知會很醜：側邊欄比 app 的最小寬度還窄

`app.py:1736` 有 `@media (max-width: 900px)` 會顯示 `#small-screen-notice`：
「This app is built for a desktop browser. On a narrow screen the editor and PDF preview
will not lay out correctly.」

Chrome 側邊欄預設約 320–500px，拉到最寬也只有視窗的一半。所以**這個警告在側邊欄裡會一直掛著**，
而且它說的是實話 —— 多欄版面與固定高度的 PDF iframe 在那個寬度下確實會亂。

這次不處理，因為兩種解法都要改 `app.py`：放寬那個斷點，或加一個側邊欄專用的單欄精簡模式。
先把擴充功能做出來，看實際用起來有多痛再決定。

## 架構

```
Chrome 側邊欄 (chrome-extension://…/sidepanel.html)
├── 工具列（約 44px）
│   └── [抓取這頁的 JD]  [↻ 重載]  [↗ 新分頁]
└── <iframe src="https://henry-ai-resume-builder.streamlit.app/?embed=true">
        ← 網站本人
```

點下按鈕之後的資料流：

1. `sidepanel.js` 用 `chrome.tabs.query({ active: true, lastFocusedWindow: true })` 找到旁邊那個職缺分頁
2. `chrome.scripting.executeScript` 注入 `document.body.innerText` — 整頁文字全抓
3. `iframe.contentWindow.postMessage(...)` 把文字送給跑在 iframe 內的 content script
4. `filler.js` 找到 JD 輸入框，塞值並觸發事件，Streamlit 當作是使用者打的

側邊欄沒有 tabId，所以第 3 步不能用 `chrome.tabs.sendMessage`。`postMessage` 是唯一可用的橋——content script 雖在隔離世界，但與頁面共用 `window`，收得到 `message` 事件。

### Streamlit Cloud 的巢狀 iframe

實測發現線上站台的結構比預期多一層：

```
https://henry-ai-resume-builder.streamlit.app/        ← Streamlit Cloud 外殼，沒有任何 app 內容
├── iframe /~/+/                                       ← 真正的 app
│     sandbox="allow-forms allow-modals allow-popups
│              allow-popups-to-escape-sandbox
│              allow-same-origin allow-scripts allow-downloads"
└── iframe statuspage.io/embed/frame                   ← 第三方
```

兩個後果：

1. manifest 的 `matches: ".../*"` 加 `all_frames: true` 已經涵蓋 `/~/+/`，不用改。
2. **`postMessage` 送到最外層是到不了欄位的**。`filler.js` 因此同時是填值器也是轉送器：這一層找不到欄位就往下一層轉送，ack 再往上傳回去。

轉送**只能送給同源的子 frame**。這是必要的過濾而不是保守：外殼頁掛著一個
statuspage.io 的 iframe，用萬用字元轉送等於把使用者抓下來的整頁內容送給第三方。

### 定位錨點

`app.py:2729` 的 JD textarea 帶有 `placeholder="Paste the job description here..."`，所以選擇器用：

```js
textarea[placeholder^="Paste the job description"]
```

比抓 class 或 `data-testid` 穩定得多，因為那串字是本專案自己控制的。線上實測確認相符，且該元素的 `aria-label` 是 `"Job description"`。

### 填值手法：`change` 事件不是多餘的

Streamlit 的 textarea 是 React 受控元件，直接改 `.value` 會被 React 的 value tracker 判定成「沒變」而吃掉，所以要走原生 setter 再自己發事件。

但**標準的 `input` + `blur` 在這裡不夠**。實測方法是攔 `WebSocket.prototype.send`：

| 手法 | 送出的 WebSocket frame |
|---|---|
| 真實滑鼠點擊（正對照） | 1 |
| setter + `input` + `blur` | **0** |
| setter + `input` + `change` + `blur` | 1 |

只發 `input` 的話，值只停在 DOM 裡，伺服器完全不知情。最終手法：

```js
const setter = Object.getOwnPropertyDescriptor(
  HTMLTextAreaElement.prototype, 'value').set;
field.focus();
setter.call(field, text);
field.dispatchEvent(new Event('input',  { bubbles: true }));
field.dispatchEvent(new Event('change', { bubbles: true }));
field.blur();   // st.text_area 是 blur 或 Ctrl+Enter 才送出，不是每次按鍵
```

端對端驗證：填完切到 Career Profile 再切回 Generator（widget 被卸載又重建），文字從 `st.session_state.jd_text` 回來了 —— 證明伺服器確實收到。

## 已評估但排除的做法

**網址參數**（`?embed=true&jd=<編碼文字>` + `st.query_params`）——整頁文字動輒 20–80KB，nginx 預設 header buffer 8KB 就 414，得砍到 4KB 以內，跟「全部截取」直接衝突。而且要改 `app.py`。

**postMessage + Streamlit 自訂元件**——最正規，但要蓋一個 bidirectional custom component（含 build 目錄），而且要改 `app.py`。

## 退路：剪貼簿

Content script 能否注入到「擴充功能頁面內的 iframe」是這個設計唯一沒有把握的一點——側邊欄沒有 tabId，只能靠 manifest 的宣告式注入，無法用 `executeScript` 補救。

所以 `sidepanel.js` 送出 `postMessage` 後等 ack，逾時（800ms）就退到剪貼簿：把整頁文字寫進剪貼簿，工具列提示使用者在 JD 欄按一次貼上。

這是刻意設計的退路，不是錯誤處理。即使注入永遠不成功，這個擴充功能仍然是好用的產品。

## 檔案

```
extension/
├── manifest.json     # MV3
├── background.js     # service worker：開側邊欄、持續修正 cookie
├── sidepanel.html    # 工具列 + iframe
├── sidepanel.css
├── sidepanel.js      # 抓取、轉送、退路、cookie 修復
└── filler.js         # content script，跑在 iframe 內的 Streamlit 頁上
```

## 權限

| 權限 | 用途 |
|---|---|
| `sidePanel` | 開側邊欄 |
| `scripting` | 注入抓取文字的程式碼到職缺分頁 |
| `tabs` | 找出旁邊那個作用中的分頁 |
| `cookies` | 重寫 `streamlit_session` 的 SameSite |
| `clipboardWrite` | 退路 |
| `host_permissions: <all_urls>` | 職缺頁可能是任何網站。`activeTab` 不夠用——它只在點擊擴充功能圖示的當下對「那個」分頁授權，使用者切到另一個職缺頁就失效了 |
| `host_permissions: *.streamlit.app` | cookie 修復與 content script |

## 測試

這次不引入 JS 測試工具鏈。本專案的 `tests/` 是 pytest + Streamlit `AppTest`，而這個擴充功能沒有任何 Python 面；為一個約 200 行的擴充功能架一套 JS 測試環境不划算。

驗證方式是手動的，而且有明確的判準——見下方驗收清單。

## 驗收清單

1. 載入未封裝擴充功能後，點圖示會開啟側邊欄
2. 側邊欄裡的網站**有內容而不是空白**（cookie 修復生效）
3. 網站在側邊欄裡能登入、能操作
4. 在職缺頁點「抓取這頁的 JD」，文字出現在 Job description 欄位
5. 若第 4 點失敗，工具列出現剪貼簿提示，且貼上後內容正確
