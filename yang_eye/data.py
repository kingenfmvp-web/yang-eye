"""資料層：FinMind（股價、除權息、月營收、報酬指數）＋ 證交所 OpenAPI（選股池）。

免費版拿不到 TaiwanStockPriceAdj，所以用原始股價＋除權息結果自己做向後還原。

所有下載結果都快取在 data/ 底下，重跑不會再消耗 API 額度。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_OPENAPI = "https://openapi.twse.com.tw/v1"


class QuotaExceeded(RuntimeError):
    pass


def _finmind(dataset: str, data_id: str | None = None, start_date: str | None = None) -> pd.DataFrame:
    params = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if start_date:
        params["start_date"] = start_date
    headers = {}
    if token := os.environ.get("FINMIND_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(4):
        r = requests.get(FINMIND_URL, params=params, headers=headers, timeout=60)
        if r.status_code == 402 or (r.status_code != 200 and "limit" in r.text.lower()):
            raise QuotaExceeded(f"FinMind 額度用完（{dataset} {data_id}），稍後重跑即可從快取續抓")
        if r.status_code == 200:
            body = r.json()
            if body.get("status") == 200:
                return pd.DataFrame(body["data"])
        time.sleep(2 ** attempt)
    raise RuntimeError(f"FinMind 失敗 {dataset} {data_id}: {r.status_code} {r.text[:200]}")


def _cached(name: str, fetch) -> pd.DataFrame:
    path = CACHE / f"{name}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    time.sleep(0.5)  # 對 API 客氣一點
    return df


def universe(top_n: int = 140) -> pd.DataFrame:
    """上市普通股依目前市值排序取前 top_n。注意：用今天的市值選，回測有存活者偏差。"""
    path = CACHE / f"universe_top{top_n}.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"stock_id": str})
    basic = requests.get(f"{TWSE_OPENAPI}/opendata/t187ap03_L", timeout=60).json()
    quotes = requests.get(f"{TWSE_OPENAPI}/exchangeReport/STOCK_DAY_ALL", timeout=60).json()
    shares = {b["公司代號"]: float(b["已發行普通股數或TDR原股發行股數"] or 0) for b in basic}
    names = {b["公司代號"]: b["公司簡稱"] for b in basic}
    rows = []
    for q in quotes:
        code = q["Code"]
        # 只留 4 碼普通股，排除 ETF（0 開頭）與 TDR（91 開頭）
        if len(code) != 4 or code.startswith(("0", "91")) or code not in shares:
            continue
        try:
            close = float(q["ClosingPrice"])
        except ValueError:
            continue
        rows.append({"stock_id": code, "name": names[code], "close": close,
                     "market_cap": shares[code] * close})
    df = (pd.DataFrame(rows).sort_values("market_cap", ascending=False)
          .head(top_n).reset_index(drop=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def prices(stock_id: str, start: str = "2013-01-01") -> pd.DataFrame:
    return _cached(f"price/{stock_id}",
                   lambda: _finmind("TaiwanStockPrice", stock_id, start))


def dividends(stock_id: str, start: str = "2013-01-01") -> pd.DataFrame:
    return _cached(f"dividend/{stock_id}",
                   lambda: _finmind("TaiwanStockDividendResult", stock_id, start))


def adjust_close(price: pd.DataFrame, div: pd.DataFrame) -> pd.Series:
    """向後還原：除權息日之前的價格乘上 參考價/前收 的累積因子。"""
    close = price.set_index(pd.to_datetime(price["date"]))["close"]
    close = close.where(close > 0).ffill()  # 無成交日價格為 0，沿用前一日
    factor = pd.Series(1.0, index=close.index)
    if not div.empty:
        d = div.assign(date=pd.to_datetime(div["date"]))
        d = d[(d["before_price"] > 0) & (d["after_price"] > 0)]
        for _, row in d.iterrows():
            if row["date"] in factor.index:
                factor[row["date"]] *= row["after_price"] / row["before_price"]
    mult = factor[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    return close * mult


def revenue(stock_id: str, start: str = "2011-01-01") -> pd.DataFrame:
    return _cached(f"revenue/{stock_id}",
                   lambda: _finmind("TaiwanStockMonthRevenue", stock_id, start))


def benchmark(start: str = "2013-01-01") -> pd.Series:
    df = _cached("benchmark_TAIEX_TR",
                 lambda: _finmind("TaiwanStockTotalReturnIndex", "TAIEX", start))
    return df.assign(date=pd.to_datetime(df["date"])).set_index("date")["price"]


def download_all(stock_ids: list[str]) -> list[str]:
    """抓所有股票的還原股價與月營收；額度用完會停下並回傳還沒抓的清單。"""
    pending = []
    for i, sid in enumerate(stock_ids):
        try:
            prices(sid)
            dividends(sid)
            revenue(sid)
        except QuotaExceeded as e:
            print(e)
            pending = stock_ids[i:]
            break
        print(f"[{i + 1}/{len(stock_ids)}] {sid} ok", flush=True)
    (CACHE / "pending.json").write_text(json.dumps(pending))
    return pending


def load_panel(stock_ids: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """回傳 (收盤價寬表, 成交量寬表[張], 月營收長表)。"""
    close, volume, revs = {}, {}, []
    for sid in stock_ids:
        paths = [CACHE / f"{k}/{sid}.parquet" for k in ("price", "dividend", "revenue")]
        if not all(x.exists() for x in paths):
            continue
        p = pd.read_parquet(paths[0])
        if p.empty:
            continue
        close[sid] = adjust_close(p, pd.read_parquet(paths[1]))
        volume[sid] = p.set_index(pd.to_datetime(p["date"]))["Trading_Volume"] / 1000
        revs.append(pd.read_parquet(paths[2]))
    close_df = pd.DataFrame(close).sort_index()
    volume_df = pd.DataFrame(volume).reindex(close_df.index)
    rev_df = pd.concat(revs, ignore_index=True) if revs else pd.DataFrame()
    return close_df, volume_df, rev_df
