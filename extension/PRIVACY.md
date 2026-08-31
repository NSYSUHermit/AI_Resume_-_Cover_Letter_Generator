# Privacy Policy — AI Resume Builder 側邊欄

Last updated: 2026-08-23

## What this extension does

It opens [AI Resume Builder](https://henry-ai-resume-builder.streamlit.app/) in
Chrome's side panel, and adds one button that copies the text of the job posting
you are currently reading into that app's "Job description" field.

## What it reads, and when

**Only when you click "抓取這頁的 JD".** Nothing is read in the background, and
no page is touched until you press that button.

When you do press it, the extension reads the visible text of the tab you are
looking at (`document.body.innerText`) and puts it into the Job description
field of the app running in the side panel.

That text then follows exactly the same path as text you would have pasted in
by hand: the app sends it to Google Gemini using **your own** Gemini API key,
which you supply inside the app.

## What it stores

**Nothing.** The extension keeps no database, uses no `chrome.storage`, and
writes no files. It has no server of its own, no analytics, no telemetry, and no
crash reporting. Close the side panel and nothing about your browsing survives
in the extension.

The one exception, and it is not storage of your data: the extension rewrites
the `SameSite` attribute of the app's own session cookie on
`henry-ai-resume-builder.streamlit.app` so the app can render inside the side
panel. It reads and rewrites only that domain's cookies, changes only that one
attribute, and never transmits a cookie anywhere.

## What it sends, and to whom

| Destination | What | When |
|---|---|---|
| `henry-ai-resume-builder.streamlit.app` | The job-posting text you asked it to grab | Only on your click |
| Google Gemini (via that app, with your own API key) | The same text, plus the resume data you entered in the app | Only when you run the app's own AI features |

Nothing is sent anywhere else. There is no third-party recipient, no ad network,
and no data broker. Your data is not sold, and it is not used to train anything.

## Permissions, and why each is needed

| Permission | Why |
|---|---|
| `sidePanel` | To open the app in Chrome's side panel — the entire point of the extension |
| `tabs` | To identify which tab you are reading, so the button grabs the right page |
| `scripting` | To read the visible text of that tab, on your click |
| `cookies` | To let the app render inside the side panel (see above); scoped to the app's own domain |
| `clipboardWrite` | Fallback path: if the text cannot be inserted into the field directly, it is copied to your clipboard so you can paste it |
| `<all_urls>` (optional) | Job postings live on many different sites, so the page you want to grab could be any of them. This is an **optional** permission: it is not granted at install, and Chrome asks you for it the first time you press the grab button. Decline it and everything except the grab button still works. |

## Your control

- The grab button never runs on its own. No click, no reading.
- The `<all_urls>` permission can be revoked at any time in
  `chrome://extensions` → this extension → Site access.
- Removing the extension removes everything it had; there is no account and
  nothing to delete on any server.

## Source code

This extension is open source. Everything described above can be verified by
reading it:
<https://github.com/NSYSUHermit/AI_Resume_-_Cover_Letter_Generator/tree/main/extension>

## Contact

Questions or concerns: open an issue at
<https://github.com/NSYSUHermit/AI_Resume_-_Cover_Letter_Generator/issues>
