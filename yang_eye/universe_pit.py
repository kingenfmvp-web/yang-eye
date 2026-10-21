"""時點正確（point-in-time）選股池：消除存活者偏差。

候選名單＝FinMind 台股總覽中的上市普通股（含已停止交易者）＋下市櫃表中 2014 年後下市的普通股。
每個換股日只用「當時」看得到的資料：前 20 個交易日的平均成交金額取前 top_n 名，
且當時已有至少 120 個交易日的成交紀錄（排除剛上市的股票）。
後來下市、被併購、市值縮水的公司，只要當時夠大，就會被納入。

（原本想用證交所 MI_INDEX 全市場日資料，但證交所防火牆會封鎖雲端 IP，改用 FinMind 逐檔股價。）
"""
from __future__ import annotations

import json
import time

import pandas as pd

from yang_eye import data
from yang_eye.data import CACHE
from yang_eye.strategy import rebalance_dates


def is_common_stock(code: str) -> bool:
    return len(code) == 4 and code.isdigit() and not code.startswith(("0", "91"))


def _reference() -> tuple[pd.DataFrame, pd.DataFrame]:
    info = data._cached("TaiwanStockInfo", lambda: data._finmind("TaiwanStockInfo"))
    delist = data._cached("TaiwanStockDelisting", lambda: data._finmind("TaiwanStockDelisting"))
    return info, delist


def candidates(since: str = "2014-06-01", market: str = "twse") -> list[str]:
    """market＝"twse"（上市）或 "tpex"（上櫃）。"""
    info, delist = _reference()
    listed = info[(info["type"] == market) & info["stock_id"].map(is_common_stock)]["stock_id"]
    gone = delist[delist["stock_id"].map(is_common_stock) & (delist["date"] >= since)]["stock_id"]
    if market == "twse":
        # 下市櫃表沒有標市場別，不在總覽裡的一律歸到上市（多納入下市股只會讓結果更保守）
        gone = gone[~gone.isin(info["stock_id"]) | gone.isin(listed)]
    else:
        gone = gone[gone.isin(listed)]
    return sorted(set(listed) | set(gone))


def names() -> dict[str, str]:
    info, delist = _reference()
    out = dict(zip(delist["stock_id"], delist["stock_name"]))
    out.update(zip(info["stock_id"], info["stock_name"]))
    return out


UMBRELLA = {"電子工業", "化學生技醫療", "其他", "創新板股票", "創新版股票"}


def industries() -> dict[str, str]:
    """每檔股票的產業別。一檔有多個分類時取細類（半導體業），不取大類（電子工業）。

    注意：這是 FinMind 目前的分類，回測時用的是今天的產業別。
    """
    info, _ = _reference()
    out = {}
    for sid, g in info.groupby("stock_id"):
        cats = [c for c in g["industry_category"].unique() if c not in UMBRELLA]
        out[sid] = cats[0] if cats else g["industry_category"].iloc[0]
    return out


def _download(stock_ids: list[str], fetchers, label: str, wait_minutes: int = 10) -> None:
    """逐檔下載；額度用完就等一下再繼續，直到全部抓完（已快取的不耗額度）。"""
    i = 0
    while i < len(stock_ids):
        try:
            for f in fetchers:
                f(stock_ids[i])
            i += 1
            if i % 50 == 0 or i == len(stock_ids):
                print(f"{label} {i}/{len(stock_ids)}", flush=True)
        except data.QuotaExceeded as e:
            print(f"{e}；等 {wait_minutes} 分鐘", flush=True)
            time.sleep(wait_minutes * 60)


def trading_value(stock_ids: list[str]) -> pd.DataFrame:
    cols = {}
    for sid in stock_ids:
        path = CACHE / f"price/{sid}.parquet"
        if not path.exists():
            continue
        p = pd.read_parquet(path)
        if p.empty:
            continue
        p = p[p["close"] > 0]
        cols[sid] = p.set_index(pd.to_datetime(p["date"]))["Trading_money"]
    return pd.DataFrame(cols).sort_index()


def build(stock_ids: list[str], start: str = "2015-01-01", top_n: int = 140,
          lookback: int = 20, min_history: int = 120) -> dict[pd.Timestamp, list[str]]:
    value = trading_value(stock_ids)
    avg = value.rolling(lookback, min_periods=1).mean().shift(1)  # 只用換股日之前的資料
    history = value.notna().cumsum().shift(1)
    universe = {}
    for d in rebalance_dates(value.index):
        if d < pd.Timestamp(start):
            continue
        ok = avg.loc[d][history.loc[d] >= min_history].dropna()
        universe[d] = ok.sort_values(ascending=False).head(top_n).index.tolist()
    return universe


def save(universe: dict[pd.Timestamp, list[str]], name: str = "universe_pit") -> None:
    rows = [{"rebalance_date": d.date(), "rank": i + 1, "stock_id": s}
            for d, xs in universe.items() for i, s in enumerate(xs)]
    pd.DataFrame(rows).to_csv(CACHE / f"{name}.csv", index=False)


def load(name: str = "universe_pit") -> dict[pd.Timestamp, list[str]]:
    df = pd.read_csv(CACHE / f"{name}.csv", dtype={"stock_id": str})
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    return {d: g.sort_values("rank")["stock_id"].tolist() for d, g in df.groupby("rebalance_date")}


def run_all() -> None:
    ids = candidates()
    print(f"候選 {len(ids)} 檔", flush=True)
    _download(ids, [data.prices], "股價")
    universe = build(ids)
    save(universe)
    members = sorted({s for xs in universe.values() for s in xs})
    print(f"選股池 {len(universe)} 期，歷年成員 {len(members)} 檔", flush=True)
    _download(members, [data.dividends, data.revenue], "營收/除權息")
    (CACHE / "pit_done.json").write_text(json.dumps({"members": len(members)}))
    print("完成", flush=True)


if __name__ == "__main__":
    run_all()
