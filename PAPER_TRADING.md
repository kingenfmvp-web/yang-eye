# 陽之眼模擬帳戶：每日更新流程

帳本存在儀表板 https://claude.ai/artifact/U9eXqyCDsCEGPDoVqrXBRy 的六個資料來源（都是 JSON 檔）：

| 資料來源 id | 內容 |
|---|---|
| `account` | 帳戶摘要（一列）：起始日、現金、淨值、上次/下次換股 |
| `nav` | 每日淨值：模擬帳戶、選股池等權重、加權報酬指數 |
| `holdings` | 目前持股：股數、成本、收盤價、市值、權重、損益 |
| `trades` | 所有交易：日期、買賣、股數、價格、手續費、證交稅 |
| `ew_basket` | 等權重對照組的成分與單位數 |
| `value_snapshots` | 最近 30 個交易日的全市場成交金額快照（選股池用） |

## 每個交易日收盤後（台北時間 18:30 以後）

1. 下載帳本：Artifact `read`，`url` 為上面的儀表板，`paths` 為六個資料來源目前的檔案路徑
   （先用 `ArtifactData` 讀 `datasets/<id>` 拿到 `source.url`），存到 `ledger/` 資料夾，檔名 `<id>.json`。
2. 執行：`.venv/bin/python -m yang_eye.paper ledger/`
   - 已經更新過的日期會自動略過；FinMind 額度用完會自動等待。
3. 上傳：把六個檔案用 Artifact `publish` + `asset: true` 上傳，再用 `ArtifactData` `batch`
   更新每個 `datasets/<id>` 的 `source.url`、`source.name`、`updated: {at, by}`。

## 建立新帳本（只做一次）

`.venv/bin/python -m yang_eye.paper ledger/ --init <起始日>`
需要本機有回測時下載的 `data/price/` 快取，用來補建倉前 20 天的成交金額快照。
