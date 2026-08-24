// Service worker：開側邊欄，並持續把 Streamlit Cloud 的 session cookie 從
// SameSite=Lax 改寫成 SameSite=None。
//
// 為什麼需要改寫：/?embed=true 不用 cookie 就回 200，但那只是 Streamlit Cloud
// 的外殼載入頁；外殼接著打的每一個 /_stcore/* 都需要 streamlit_session，而該
// cookie 是 SameSite=Lax，跨站 iframe 不會送出。chrome-extension:// 對
// streamlit.app 算跨站，所以側邊欄裡的每個後端請求都會 303 到 /-/login，畫面
// 永遠空白。實測見 docs/superpowers/specs/2026-08-23-chrome-side-panel-design.md。
//
// 不用 declarativeNetRequest 改寫 Set-Cookie：DNR 的 modifyHeaders 只能設固定
// 值，無法對既有 header 做正規式替換，而 session cookie 的值是動態的。MV3 也已
// 移除 blocking 版的 webRequest。chrome.cookies 則連 HttpOnly cookie 都讀得到。

const APP_HOST = 'henry-ai-resume-builder.streamlit.app';
const APP_ORIGIN = `https://${APP_HOST}`;

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((err) => console.error('[resume-panel] setPanelBehavior 失敗', err));

/** 把一個 cookie 原值重寫成 SameSite=None。回傳是否真的動到它。 */
async function relaxSameSite(cookie) {
  if (!cookie || cookie.sameSite === 'no_restriction') return false;

  const details = {
    url: APP_ORIGIN + (cookie.path || '/'),
    name: cookie.name,
    value: cookie.value,
    path: cookie.path || '/',
    httpOnly: cookie.httpOnly,
    // SameSite=None 一定要配 Secure，否則 Chrome 會直接拒絕這次寫入。
    // 這些 cookie 本來就帶 Secure，所以寫死 true 不會改變語意。
    secure: true,
    sameSite: 'no_restriction',
  };
  // host-only cookie 不能帶 domain：帶了會被存成 .domain（涵蓋子網域），
  // 那是「另一個」cookie，原本那個 Lax 的仍然留著擋路。
  if (!cookie.hostOnly) details.domain = cookie.domain;
  // 沒有 expirationDate 的是 session cookie，補上去會把它變成持久 cookie。
  if (!cookie.session) details.expirationDate = cookie.expirationDate;

  try {
    await chrome.cookies.set(details);
    return true;
  } catch (err) {
    console.error('[resume-panel] 重寫 cookie 失敗', cookie.name, err);
    return false;
  }
}

// Streamlit Cloud 在之後的導覽中還會重新種下 Lax 版本，所以這裡持續修正，
// 而不是只在側邊欄開啟時修一次。
chrome.cookies.onChanged.addListener(({ cookie, removed }) => {
  if (removed) return;
  if (cookie.domain.replace(/^\./, '') !== APP_HOST) return;
  // 已經是 None 就不再處理 —— 否則我們自己的寫入會再觸發這個 listener，無窮迴圈。
  if (cookie.sameSite === 'no_restriction') return;
  relaxSameSite(cookie);
});

/** 確保 cookie 存在且是 SameSite=None。側邊欄在載入 iframe 之前會先叫這個。 */
async function repairCookies() {
  // 先用擴充功能的身分打一次首頁，讓 Streamlit Cloud 跑完
  // /-/auth/app -> /-/login?payload=... 的 handshake 把 session cookie 種下來。
  // 沒有這一步，全新的瀏覽器狀態下根本沒有 cookie 可改寫。
  try {
    await fetch(`${APP_ORIGIN}/`, { credentials: 'include', redirect: 'follow' });
  } catch (err) {
    console.warn('[resume-panel] 暖身請求失敗（離線？）', err);
  }

  const cookies = await chrome.cookies.getAll({ domain: APP_HOST });
  let fixed = 0;
  for (const cookie of cookies) {
    if (await relaxSameSite(cookie)) fixed += 1;
  }
  return { total: cookies.length, fixed };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'REPAIR_COOKIES') return undefined;
  repairCookies().then(sendResponse, (err) => {
    console.error('[resume-panel] repairCookies 失敗', err);
    sendResponse({ total: 0, fixed: 0, error: String(err) });
  });
  return true; // 非同步回覆
});
