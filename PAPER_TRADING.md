# 陽之眼模擬帳戶：每日更新流程

儀表板（帳本所在地）：https://claude.ai/artifact/U9eXqyCDsCEGPDoVqrXBRy

帳本是儀表板裡的六個資料來源，每個都是一個 JSON 檔（儀表板的 asset）：

| 資料來源 id | 內容 |
|---|---|
| `account` | 帳戶摘要（一列）：起始日、現金、淨值、上次/下次換股 |
| `nav` | 每日淨值：模擬帳戶、選股池等權重、加權報酬指數 |
| `holdings` | 目前持股：股數、成本、收盤價、市值、權重、損益 |
| `trades` | 所有交易：日期、買賣、股數、價格、手續費、證交稅 |
| `ew_basket` | 等權重對照組的成分與單位數 |
| `value_snapshots` | 最近 30 個交易日的上市普通股成交金額快照（選股池用） |

## 每個交易日的隔天早上（排程：台北時間週二至週六 10:10）

證交所 OpenAPI 的全市場行情隔天早上才發布，所以每次處理的是**前一個交易日**；引擎一律處理 OpenAPI 上最新的那一天，不會漏日。

1. **準備程式**：repo `kingenfmvp-web/yang-eye` clone 到 `/home/user/yang-eye`，
   `python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt`。
2. **下載帳本**：對六個 id 各做一次 `ArtifactData get`（collection `datasets`），
   記下 `source.url`（形如 `/_blob/<32 碼 id>`）與 `version`。
   用 Artifact `read`，`url` 為儀表板、`path` 為那 32 碼 id，存下後改名為 `ledger/<資料來源 id>.json`。
3. **執行**：`.venv/bin/python -m yang_eye.paper ledger/`
   - 印出「已經更新過，略過」：沒有新資料（假日或已跑過）。**只上傳 `account.json`**（第 4、5 步只做 account 這一個），讓儀表板顯示最後檢查時間；其他五個不動。
   - 結束碼 3（資料尚未更新）：30 分鐘後重跑，最多 3 次；仍失敗就結束並回報。
   - FinMind 額度用完時程式會等 10 分鐘重試，連續 3 次仍用完就以結束碼 3 結束，照上一條規則重跑。
4. **上傳**：六個檔案各用 Artifact `publish` + `asset: true` + `file_path` 上傳（JSON 一次一個）。
   再用一次 `ArtifactData batch` 更新六個 `datasets/<id>`：
   `source: {kind: "file", url: <新的 /_blob/...>, name: "<id>.json"}`、
   `updated: {at: <ISO 時間>, by: "Claude（陽之眼模擬引擎）"}`，每筆帶上第 2 步的 `if_version`。
5. **清理**：batch 成功後，用 Artifact `delete`（`url` 儀表板、`path` 舊的 32 碼 id）刪掉六個舊 asset。
6. **回報**：一行摘要，即程式最後一行（日期、三個組合的淨值、持股數、新交易筆數）。
   若當天有換股，列出買進與賣出的股票。

程式不需要 commit；這個流程只改儀表板裡的帳本。

### AI 主題集中度（只記錄，不影響選股）

引擎每次估值時，依 `yang_eye/themes.json`（ToAlpha 產業輪動頁的 AI 供應鏈分群）標出每檔衛星持股的子產業，
並在 account 記下 `ai_weight`（AI 供應鏈占淨值）、`ai_count`、`top_theme`／`top_theme_weight`，
nav 的模擬帳戶列也記 `ai_weight` 留下歷史。分群會變，約每月換股前手動執行
`.venv/bin/python -m scripts.update_themes` 後 commit 更新；排程不跑這支。

## 建立新帳本（只做一次，已於 2026-10-20 完成）

`.venv/bin/python -m yang_eye.paper ledger/ --init <起始日>`
需要本機有回測時下載的 `data/price/` 快取，用來補建倉前 20 天的成交金額快照；
第一次換股發生在之後的第一次正常執行。

## 盤前參考（排程：台北時間週一至週五 08:10）

1. 準備程式（同上）。
2. 執行 `.venv/bin/python -m yang_eye.premarket ledger/premarket.json`
   - 結束碼 3：美股資料還沒更新或 FinMind 額度用完，20 分鐘後重跑一次；仍失敗就結束並回報。
3. 用 `ArtifactData get` 讀 `datasets/premarket` 拿 `source.url` 與 `version`；
   上傳 `premarket.json`（Artifact `publish` + `asset: true`），
   `update` `datasets/premarket` 的 `source.url`、`source.name`、`updated`（帶 `if_version`），
   再刪掉舊的 asset。
4. 回報：程式印出的四行（費半、那斯達克、台積電 ADR、0050 預估開盤跳空）。
