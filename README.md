# yang-eye
陽之眼絕密計畫

用 AI 與量化方法研究台股：營收動能選股、無存活者偏差的回測，以及前瞻模擬帳戶。

## 結構
```
yang_eye/data.py       資料層：FinMind（股價、除權息、月營收、報酬指數）＋證交所 OpenAPI（選股池）
yang_eye/strategy.py   算法一：營收動能（含營收公告時間差處理）
yang_eye/backtest.py   vectorbt 主引擎＋簡易引擎交叉驗證、績效指標
yang_eye/universe_pit.py  時點正確選股池（含已下市股票），消除存活者偏差
yang_eye/paper.py      模擬帳戶引擎（帳本存在儀表板，流程見 PAPER_TRADING.md）
dashboard/index.html   模擬帳戶儀表板頁面
run_backtest.py        產生 reports/ 底下的報告、淨值圖、歷史選股清單
docs/finmind_llms*.txt FinMind 官方資料字典（給 AI 查欄位用）
data/                  API 快取（重跑不耗額度）
```

## 使用
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 選用：註冊 FinMind 後設定 token，額度 300 → 600 次/小時
export FINMIND_TOKEN=...
.venv/bin/python -m yang_eye.universe_pit   # 下載全部候選股並建立時點正確選股池
.venv/bin/python run_backtest.py            # 產生 v0.1 vs v0.2 回測報告
```
免費額度用完時下載會自動停下，過一小時重跑同一行即可從快取續抓。

## 已知限制
- v0.1 選股池用「今天」的市值前 140 大，有存活者偏差；v0.2 改用每期當時的成交金額排名並納入已下市股票
- 只涵蓋上市（TWSE），未含上櫃
- 還原價只處理除權息，沒處理減資與分割（報告會列出疑似事件）
- 成本未計滑價；收盤成交假設
- 研究用途，不構成投資建議
