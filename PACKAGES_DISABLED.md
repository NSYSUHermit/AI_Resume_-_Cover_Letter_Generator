# 為什麼 packages.txt 現在叫 packages.txt.disabled

**停用日期：2026-09-07**

## 發生什麼事

Streamlit Cloud 基礎映像檔的 apt 來源裡有 Debian bullseye，而 bullseye 已經變成
`oldoldstable`。它的 security Release 檔在 **2026-09-07 21:13:04 UTC 過期**：

```
Suite:       oldoldstable-security
Date:        Mon, 31 Aug 2026 21:13:04 UTC
Valid-Until: Mon, 07 Sep 2026 21:13:04 UTC
```

只要 repo 裡有 `packages.txt`，Streamlit Cloud 就會跑 apt-get，於是每次部署都死在：

```
E: Release file for http://deb.debian.org/debian-security/dists/bullseye-security/InRelease
   is expired (invalid since 15min 0s). Updates for this repository will not be applied.
❗️ installer returned a non-zero exit code
```

那個 apt 來源在 Streamlit 的映像檔裡，不在本 repo，改不到。`packages.txt` 一旦不存在，
apt 階段整個被跳過，建置直接進到 pip，app 就能起來。

## 代價

`packages.txt` 裝的是 TeX Live（`texlive-luatex`、`texlive-fonts-extra`、
`texlive-latex-extra`），也就是 **PDF 產生會失效**。按 Generate PDF 會得到
`app.py` 的 `LATEX_MISSING_MESSAGE`，明確說明原因並指向 Word 下載。

仍然正常的：AI 優化、ATS 分析、Tracker、申請問答對話框，以及
**Word (.docx) 匯出** —— `docx_export.py` 從 JSON 直接產生檔案，完全不經過 LaTeX。

## 怎麼還原

等 Streamlit Cloud 把過期的 bullseye 來源從映像檔移除之後：

```bash
git mv packages.txt.disabled packages.txt
git rm PACKAGES_DISABLED.md
```

推上去、重新部署即可。驗證方式：Generate PDF 應該要真的產出 PDF，而不是顯示
`LATEX_MISSING_MESSAGE`。

## 怎麼判斷上游修好了沒

```bash
curl -sS http://deb.debian.org/debian-security/dists/bullseye-security/Release | grep Valid-Until
```

如果 `Valid-Until` 變成未來的時間，Debian 有重新簽署，還原就會成功。但真正的修法是
Streamlit 把那個 EOL 的來源從映像檔拿掉 —— bullseye 已經 EOL，那個 Release 檔未必
會再被更新。
