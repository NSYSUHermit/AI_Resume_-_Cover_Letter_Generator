# 部署到 Cloud Run

Streamlit Community Cloud 之外的另一條路，存在的理由見 `PACKAGES_DISABLED.md`：
它的基礎映像檔掛著一個 EOL 的 Debian apt 來源，只要 repo 有 `packages.txt` 就會讓
每次部署失敗，而那個來源不在本 repo，改不到。自己的映像檔就沒有這個問題。

**App 程式碼一行都不用改。** `init_firebase()` 讀 `st.secrets["firebase_service_account"]`，
而 `st.secrets` 讀的是 `.streamlit/secrets.toml`；Cloud Run 把 secret 掛成那個檔案就好。

## 前置

```bash
gcloud auth login
gcloud config set project <你的-GCP-專案>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 一、把 Firebase 憑證放進 Secret Manager

本機那份 `.streamlit/secrets.toml`（**已被 .gitignore 和 .dockerignore 排除，
不會進 repo 也不會進映像檔**）直接當作 secret 內容：

```bash
gcloud secrets create streamlit-secrets --data-file=.streamlit/secrets.toml
```

之後要更新：

```bash
gcloud secrets versions add streamlit-secrets --data-file=.streamlit/secrets.toml
```

## 二、建置並部署

```bash
gcloud run deploy ai-resume \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 900 \
  --update-secrets=/app/.streamlit/secrets.toml=streamlit-secrets:latest
```

參數說明：

| 參數 | 為什麼 |
|---|---|
| `--memory 2Gi` | LuaLaTeX 編譯吃記憶體，預設 512Mi 會被 OOM 砍掉 |
| `--cpu 2` | 編譯是 CPU-bound，1 vCPU 下每份 PDF 要等很久 |
| `--timeout 900` | 冷啟動要載入約 2GB 的映像檔 |
| `--allow-unauthenticated` | 公開網站；使用者驗證是 app 自己的 Firebase 帳密那層 |
| `--update-secrets` | 把 secret 掛成 `st.secrets` 預期的檔案路徑 |

`--source .` 會用本 repo 的 `Dockerfile` 在 Cloud Build 上建置，本機不用先 push 映像檔。

**架構要注意**：Cloud Build 產出的是 `linux/amd64`，這正是 Cloud Run 要的。但如果你在
Apple Silicon 的 Mac 上自己 `docker build` 再 push，預設會是 `arm64`，Cloud Run 起不來。
那條路要明確指定平台：

```bash
docker build --platform linux/amd64 -t <image> .
```

本機 `docker build` 只用來驗證 Dockerfile 正確（例如確認 LuaLaTeX 真的能編出履歷），
實際部署走 `--source .` 就不必操心這件事。

## 三、驗收

部署完成後 gcloud 會印出網址。要確認的是：

1. 網站載得出來、能登入
2. **按 Generate PDF 真的產出 PDF**，而不是 `LATEX_MISSING_MESSAGE`
3. Word 下載仍然正常
4. Tracker 讀寫正常（代表 secret 掛對了）

第 2 點是整個搬遷的目的，其他三項是確認沒有搬壞東西。

## 成本

Cloud Run 沒有流量時縮到零，只有處理請求時計費。以求職用的流量來說，通常落在免費額度內。
真正的成本是冷啟動時間——映像檔約 2GB，久沒人用之後第一個請求會等比較久。
不能接受的話設 `--min-instances 1`，代價是會開始持續計費。

## 之後改 code

```bash
gcloud run deploy ai-resume --source . --region asia-east1
```

secret 掛載和其他設定會沿用，不用重打。

## Streamlit Cloud 那邊怎麼辦

兩邊可以並存。等上游修好之後（判斷方式見 `PACKAGES_DISABLED.md`），
Streamlit Cloud 那份還原 `packages.txt` 就會恢復完整功能，可以留著當備援，
或直接關掉。
