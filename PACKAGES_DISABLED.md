# packages.txt / LuaLaTeX 部署狀態

## 現況：packages.txt 已停用

**2026-09-07 23:14 UTC** 試過還原（commit 16bcd02），建置再次失敗，app 整個掛掉，
幾分鐘後退回停用狀態。也就是說當時 Streamlit 的映像檔仍然掛著那個過期的 apt 來源。

下次要再試之前，先確認上游狀態（見下方指令），不要盲目重試 —— 每試一次 app 就會
下線幾分鐘。

## 已知故障：Debian bullseye EOL

Streamlit Cloud 基礎映像檔的 apt 來源裡有 Debian bullseye，而 bullseye 已是
`oldoldstable`，它的 security Release 檔在 **2026-09-07 21:13:04 UTC 過期**：

```
Suite:       oldoldstable-security
Date:        Mon, 31 Aug 2026 21:13:04 UTC
Valid-Until: Mon, 07 Sep 2026 21:13:04 UTC
```

只要 repo 有 `packages.txt`，Streamlit Cloud 就會跑 apt-get，於是部署死在：

```
E: Release file for http://deb.debian.org/debian-security/dists/bullseye-security/InRelease
   is expired (invalid since 15min 0s). Updates for this repository will not be applied.
❗️ installer returned a non-zero exit code
```

失敗需要**兩個條件同時成立**：Debian 那邊過期，而且 Streamlit 的映像檔還列著那個來源。
第二個條件從外部看不到，只有實際建置才知道。

## 如果建置又掛了

暫時停用，讓 app 至少活著：

```bash
git mv packages.txt packages.txt.disabled
```

代價是 PDF 產生失效（按 Generate PDF 會顯示 `app.py` 的 `LATEX_MISSING_MESSAGE`）。
仍然正常：AI 優化、ATS 分析、Tracker、申請問答對話框，以及 **Word (.docx) 匯出**
（`docx_export.py` 從 JSON 直接產檔，不經過 LaTeX）。

## 怎麼確認上游狀態

```bash
curl -sS http://deb.debian.org/debian-security/dists/bullseye-security/Release | grep Valid-Until
```

`Valid-Until` 變成未來時間 = Debian 重新簽署了。但真正的修法是 Streamlit 把這個 EOL
來源從映像檔移除 —— bullseye 已 EOL，那個 Release 檔未必會再更新。

## 長期解法

離開 Streamlit Cloud，改用能自己控制映像檔的地方（Cloud Run / Render / Fly）。
用自己的 Dockerfile 裝 texlive，上游一個 EOL 的 apt 來源就再也不能讓整個 app 停擺。
