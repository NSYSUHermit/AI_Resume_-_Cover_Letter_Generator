// Content script，跑在 Streamlit 頁面上。收側邊欄送來的整頁文字，填進
// Job description 欄位。
//
// 這支同時扮演兩個角色，因為 Streamlit Cloud 把真正的 app 又包了一層 iframe：
//
//   https://…streamlit.app/        ← Streamlit Cloud 的外殼，沒有 JD 欄位
//   └── https://…streamlit.app/~/+/  ← 真正的 app（sandbox + allow-same-origin）
//
// manifest 的 matches 涵蓋兩層（`/*` + all_frames），所以這支會被注入兩次：
// 外層找不到欄位就往下轉送，內層負責真的填。
//
// 這支能不能被注入到「擴充功能頁面內的 iframe」是整個設計唯一沒把握的一點：
// 側邊欄沒有 tabId，只能靠 manifest 的宣告式注入，無法用
// chrome.scripting.executeScript 補救。收不到 ack 時，側邊欄會退到剪貼簿。

const FILL_REQUEST = 'RESUME_PANEL_FILL_JD';
const FILL_RESPONSE = 'RESUME_PANEL_FILLED';

// app.py:2729 的 st.text_area 帶著這個 placeholder。用它當錨點比抓 class 或
// data-testid 穩定得多 —— 那串字是本專案自己寫的，Streamlit 改版動不到。
// 已對線上站台實測確認：aria-label="Job description"、placeholder 相符。
const JD_SELECTOR = 'textarea[placeholder^="Paste the job description"]';

// 子層沒人回應時，外層自己回覆的時限。子層是同步處理完就回，所以這只是留給
// 一次 postMessage 往返；真正的失敗模式是「子層根本沒被注入」，那會永遠等不到。
const RELAY_TIMEOUT_MS = 700;

const pendingRelays = new Map(); // nonce -> { reply, timer }

window.addEventListener('message', (event) => {
  if (!event.data || typeof event.data !== 'object') return;
  // 只收自家側邊欄（unpacked 的 id 每次載入可能不同，所以比對 scheme）或
  // 同源的上下層 frame。
  const trusted =
    event.origin.startsWith('chrome-extension://') || event.origin === location.origin;
  if (!trusted) return;

  if (event.data.type === FILL_REQUEST) handleFillRequest(event);
  else if (event.data.type === FILL_RESPONSE) handleChildResponse(event.data);
});

function handleFillRequest(event) {
  const { nonce, text } = event.data;
  const reply = (payload) => {
    try {
      event.source?.postMessage({ type: FILL_RESPONSE, nonce, ...payload }, event.origin);
    } catch (err) {
      console.error('[resume-panel] 回覆失敗', err);
    }
  };

  const outcome = fillJobDescription(text);
  if (outcome.ok) {
    reply(outcome);
    return;
  }

  const children = relayTargets();
  if (children.length === 0) {
    reply(outcome);
    return;
  }

  // 這一層沒有欄位，往下一層轉送，並在子層沒回應時自己認賠。
  const timer = setTimeout(() => {
    pendingRelays.delete(nonce);
    reply(outcome);
  }, RELAY_TIMEOUT_MS);
  pendingRelays.set(nonce, { reply, timer });

  for (const child of children) {
    try {
      child.contentWindow?.postMessage(event.data, location.origin);
    } catch (err) {
      console.error('[resume-panel] 轉送失敗', err);
    }
  }
}

function handleChildResponse(data) {
  const relay = pendingRelays.get(data.nonce);
  if (!relay) return;
  clearTimeout(relay.timer);
  pendingRelays.delete(data.nonce);
  const { type, nonce, ...payload } = data;
  relay.reply(payload);
}

/** 只轉送給同源的子 frame。
 *
 *  這個過濾是必要的而不是保守：Streamlit Cloud 的外殼頁還掛了一個
 *  statuspage.io 的 iframe，用萬用字元轉送等於把使用者抓下來的整頁內容
 *  送給第三方。 */
function relayTargets() {
  return [...document.querySelectorAll('iframe')].filter((frame) => {
    try {
      return new URL(frame.src, location.href).origin === location.origin;
    } catch {
      return false;
    }
  });
}

function fillJobDescription(text) {
  const field = document.querySelector(JD_SELECTOR);
  // JD 欄位只在 Generator 視圖才存在；外層的 Streamlit Cloud 外殼也永遠找不到。
  if (!field) return { ok: false, reason: 'no-field' };

  // Streamlit 的 textarea 是 React 受控元件：直接改 .value 會被 React 的
  // value tracker 判定成「沒變」而吃掉，所以要走原生 setter 再自己發事件。
  const nativeSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    'value',
  ).set;

  field.focus();
  nativeSetter.call(field, text);
  field.dispatchEvent(new Event('input', { bubbles: true }));
  // change 不是多餘的。對線上站台實測過：只發 input 再 blur，WebSocket 一個
  // frame 都不會送出（值只停在 DOM 裡，伺服器完全不知情）；補上 change 之後
  // 才真的送出。驗證方式是填完切到 Career Profile 再切回 Generator，文字會從
  // st.session_state.jd_text 回來。
  field.dispatchEvent(new Event('change', { bubbles: true }));
  // st.text_area 是 blur 或 Ctrl+Enter 才把值送回伺服器，不是每次按鍵。
  field.blur();

  field.scrollIntoView({ block: 'center', behavior: 'smooth' });
  return { ok: true };
}
