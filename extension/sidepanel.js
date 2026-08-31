// 側邊欄本體：工具列 + 一個裝著整個網站的 iframe。
//
// 抓取流程：
//   1. 找到旁邊那個作用中的分頁
//   2. 注入 document.body.innerText —— 整頁文字全抓，不做站別解析
//   3. postMessage 給跑在 iframe 內的 filler.js
//   4. 等 ack；逾時就退到剪貼簿
//
// 第 3 步不能用 chrome.tabs.sendMessage：側邊欄不是分頁，它裡面的 iframe 沒有
// tabId。postMessage 是唯一可用的橋 —— content script 雖在隔離世界，但與頁面
// 共用 window，收得到 message 事件。

const APP_ORIGIN = 'https://henry-ai-resume-builder.streamlit.app';
const APP_URL = `${APP_ORIGIN}/?embed=true`;

// 訊息要走兩跳：Streamlit Cloud 的外殼頁 -> 真正的 app（/~/+/ 那層 iframe）。
// filler.js 在外層等子層 700ms，所以這裡必須比它寬鬆。真正的失敗模式是
// 「content script 根本沒被注入」，那會永遠等不到，拉長只是白等。
const ACK_TIMEOUT_MS = 2500;

const frame = document.getElementById('app');
const statusEl = document.getElementById('status');
const grabBtn = document.getElementById('grab');
const reloadBtn = document.getElementById('reload');
const popoutBtn = document.getElementById('popout');

// Whether the user has granted the optional <all_urls> permission that reading
// a job page needs. Cached at boot specifically so the click handler can test
// it WITHOUT awaiting: chrome.permissions.request() must run inside a user
// gesture, and an await before it loses that gesture ("This function must be
// called during a user gesture"). So the async check happens here, once, and
// the click path stays synchronous up to the request itself.
let canReadPages = false;

function setStatus(text, tone = 'info') {
  if (!text) {
    statusEl.hidden = true;
    return;
  }
  statusEl.textContent = text;
  statusEl.dataset.tone = tone;
  statusEl.hidden = false;
}

// ---------------------------------------------------------------------------
// 開機
// ---------------------------------------------------------------------------

async function boot() {
  setStatus('載入中…第一次開啟要等 app 從休眠醒來，可能數十秒。');

  // Read once here so grab() can branch on it synchronously. Failure is not
  // fatal: a false value only means the first grab asks for permission again.
  try {
    canReadPages = await chrome.permissions.contains({ origins: ['<all_urls>'] });
  } catch (err) {
    console.warn('[resume-panel] 權限狀態查詢失敗', err);
  }

  // 保險，不是必要條件：跨網域 iframe 實測是可以正常渲染的，但擴充功能的頂層
  // 情境跟一般網頁不完全相同，而失敗的代價是側邊欄一片空白。所以先把
  // streamlit_session 改寫成 SameSite=None 再載入，且失敗不擋流程。
  try {
    const result = await chrome.runtime.sendMessage({ type: 'REPAIR_COOKIES' });
    if (result?.error) console.warn('[resume-panel] cookie 保險失敗', result.error);
  } catch (err) {
    console.warn('[resume-panel] cookie 保險失敗', err);
  }

  frame.addEventListener('load', () => setStatus(''), { once: true });
  frame.src = APP_URL;
}

// ---------------------------------------------------------------------------
// 抓取
// ---------------------------------------------------------------------------

/** 旁邊那個瀏覽器視窗裡作用中的分頁。側邊欄本身不是分頁，所以 lastFocusedWindow
 *  指的就是使用者正在看的那個視窗。 */
async function activeJobTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab?.id) throw new Error('找不到作用中的分頁。');
  if (/^(chrome|edge|about|devtools|chrome-extension):/i.test(tab.url || '')) {
    throw new Error('這個分頁不是一般網頁，抓不到內容。');
  }
  if (tab.url?.startsWith(APP_ORIGIN)) {
    throw new Error('旁邊那頁就是這個網站本身，沒有 JD 可以抓。');
  }
  return tab;
}

async function scrapePageText(tabId) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId },
    // 刻意只抓純文字整頁 —— 站別解析交給 Gemini，不在這裡維護一堆選擇器。
    func: () => document.body.innerText,
  });
  return (injection?.result || '').trim();
}

/** 把文字送進 iframe。回傳 filler.js 的回覆，或逾時的 null。 */
function deliverToApp(text) {
  return new Promise((resolve) => {
    if (!frame.contentWindow) {
      resolve(null);
      return;
    }
    const nonce = crypto.randomUUID();
    const timer = setTimeout(() => {
      window.removeEventListener('message', onAck);
      resolve(null);
    }, ACK_TIMEOUT_MS);

    function onAck(event) {
      if (event.origin !== APP_ORIGIN) return;
      if (event.data?.type !== 'RESUME_PANEL_FILLED' || event.data.nonce !== nonce) return;
      clearTimeout(timer);
      window.removeEventListener('message', onAck);
      resolve(event.data);
    }

    window.addEventListener('message', onAck);
    frame.contentWindow.postMessage({ type: 'RESUME_PANEL_FILL_JD', nonce, text }, APP_ORIGIN);
  });
}

// 退路不是錯誤處理，是刻意設計的第二條路：就算 content script 永遠注入不進去，
// 「按鈕幫你把整頁複製好」仍然比手動選取整頁再複製好用。
async function fallbackToClipboard(text, why) {
  try {
    await navigator.clipboard.writeText(text);
    setStatus(`${why}已複製 ${text.length.toLocaleString()} 字到剪貼簿 —— 請在 Job description 欄按貼上。`, 'warn');
  } catch (err) {
    setStatus(`${why}而且連剪貼簿也失敗了：${err.message || err}`, 'error');
  }
}

async function grab() {
  // Before anything async - see canReadPages' declaration for why the order
  // here is load-bearing rather than stylistic.
  if (!canReadPages) {
    setStatus('等待權限授權…');
    try {
      canReadPages = await chrome.permissions.request({ origins: ['<all_urls>'] });
    } catch (err) {
      setStatus(`無法要求權限：${err.message || err}`, 'error');
      return;
    }
    if (!canReadPages) {
      setStatus('沒有讀取網頁的權限就抓不到 JD。再按一次可以重新授權。', 'warn');
      return;
    }
  }

  grabBtn.disabled = true;
  try {
    const tab = await activeJobTab();
    setStatus(`從「${tab.title || tab.url}」抓取中…`);

    const text = await scrapePageText(tab.id);
    if (!text) {
      setStatus('那一頁抓不到任何文字。', 'warn');
      return;
    }

    const ack = await deliverToApp(text);
    if (ack?.ok) {
      setStatus(`已填入 ${text.length.toLocaleString()} 字。`, 'ok');
      return;
    }
    if (ack?.reason === 'no-field') {
      await fallbackToClipboard(text, '找不到 Job description 欄位（要先登入並切到 Generator）——');
      return;
    }
    await fallbackToClipboard(text, '填不進網站裡 ——');
  } catch (err) {
    setStatus(err.message || String(err), 'error');
  } finally {
    grabBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------

grabBtn.addEventListener('click', grab);

reloadBtn.addEventListener('click', () => {
  setStatus('');
  boot();
});

popoutBtn.addEventListener('click', () => {
  chrome.tabs.create({ url: `${APP_ORIGIN}/` });
});

boot();
