"""美股隔夜行情對台股的影響：大盤層級的統計，以及營收動能策略改成「隔天開盤買」的回測。

台股 d 日開盤前，最近一次收盤的美股交易日是 d 之前最後一個美股日（台北時間凌晨 4–5 點收盤）。
輸出 reports/us_overnight_report.md。
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import vectorbt as vbt

from run_backtest import REPORTS, START, fmt
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import target_weights

US = {"費半 ^SOX": "_SOX", "那斯達克 ^IXIC": "_IXIC", "台積電 ADR": "TSM"}


def us_returns() -> pd.DataFrame:
    out = {}
    for label, f in US.items():
        df = pd.read_parquet(data.CACHE / f"us/{f}.parquet")
        s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["Adj_Close"]
        out[label] = s.pct_change()
    return pd.DataFrame(out)


def overnight_for(tw_days: pd.DatetimeIndex, us: pd.DataFrame) -> pd.DataFrame:
    """台股每個交易日開盤前，可看到的最近一晚美股報酬（美股日期 < 台股日期）。"""
    us = us.dropna(how="all")
    pos = us.index.searchsorted(tw_days, side="left") - 1
    rows = us.iloc[np.clip(pos, 0, None)].to_numpy().copy()
    rows[pos < 0] = np.nan
    return pd.DataFrame(rows, index=tw_days, columns=us.columns)


def adjusted_open(stock_ids: list[str], close_adj: pd.DataFrame) -> pd.DataFrame:
    """開盤價套用與收盤價相同的還原因子。"""
    cols = {}
    for sid in stock_ids:
        p = pd.read_parquet(data.CACHE / f"price/{sid}.parquet")
        if p.empty:
            continue
        p = p.set_index(pd.to_datetime(p["date"]))
        raw_close = p["close"].where(p["close"] > 0)
        factor = (close_adj[sid] / raw_close).reindex(p.index)
        cols[sid] = (p["open"].where(p["open"] > 0) * factor)
    return pd.DataFrame(cols).reindex(close_adj.index)


def market_study(us: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = pd.read_parquet(data.CACHE / "price/0050.parquet")
    p = p[(p["close"] > 0) & (p["open"] > 0)].assign(date=lambda x: pd.to_datetime(x["date"])).set_index("date")
    div = pd.read_parquet(data.CACHE / "dividend/0050.parquet")
    ex = set(pd.to_datetime(div["date"]))
    df = pd.DataFrame({"gap": p["open"] / p["close"].shift(1) - 1, "intraday": p["close"] / p["open"] - 1})
    df = df[~df.index.isin(ex)].loc[START:]  # 除息日的跳空是假的，排除
    df = df[(df["gap"].abs() < 0.08) & (df["intraday"].abs() < 0.11)]  # 排除分割（2025 年 1 拆 4）造成的假跳空
    on = overnight_for(df.index, us)
    corr = pd.DataFrame({c: {"與隔天開盤跳空的相關係數": df["gap"].corr(on[c]),
                             "與隔天開盤→收盤的相關係數": df["intraday"].corr(on[c])} for c in on.columns}).T
    bins = pd.cut(on["費半 ^SOX"], [-1, -0.03, -0.015, 0, 0.015, 0.03, 1],
                  labels=["≤ -3%", "-3% ~ -1.5%", "-1.5% ~ 0", "0 ~ +1.5%", "+1.5% ~ +3%", "≥ +3%"])
    g = df.groupby(bins, observed=True)
    bucket = pd.DataFrame({"天數": g.size(),
                           "隔天開盤跳空（平均）": g["gap"].mean().map(lambda x: f"{x:+.2%}"),
                           "開盤→收盤（平均）": g["intraday"].mean().map(lambda x: f"{x:+.2%}"),
                           "開盤→收盤 上漲機率": g["intraday"].apply(lambda x: f"{(x > 0).mean():.0%}")})
    return corr, bucket


def delayed(weights: pd.DataFrame, block: pd.Series, max_delay: int = 3) -> pd.DataFrame:
    """換股單往後延到第一個 block 為 False 的交易日（最多延 max_delay 天）。"""
    out = pd.DataFrame(np.nan, index=weights.index, columns=weights.columns)
    idx = list(weights.index)
    for d in weights.dropna(how="all").index:
        i = idx.index(d)
        j = i
        while j < len(idx) - 1 and j - i < max_delay and block.iloc[j]:
            j += 1
        out.iloc[j] = weights.loc[d]
    return out


def run_open(close: pd.DataFrame, open_: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    pf = vbt.Portfolio.from_orders(close=close.ffill(), price=open_.fillna(close.ffill()), size=weights,
                                   size_type="targetpercent", group_by=True, cash_sharing=True,
                                   call_seq="auto", fees=bt.FEE_PER_SIDE, init_cash=1_000_000, freq="1D")
    start = weights.dropna(how="all").index[0]
    v = pf.value()
    return v[v.index >= start]


def main() -> None:
    us = us_returns()
    corr, bucket = market_study(us)

    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    w, _ = target_weights(close, volume, rev, V03, START, pit, universe_pit.industries())
    open_ = adjusted_open(list(close.columns), close)
    sox = overnight_for(close.index, us)["費半 ^SOX"].fillna(0)

    next_open = w.shift(1)  # 換股日收盤後才確定名單，隔天早上開盤下單
    values = {
        "換股日收盤買（目前做法）": bt.run_vbt(close, w),
        "隔天開盤買": run_open(close, open_, next_open),
        "隔天開盤買；前一晚費半跌 ≥2% 就延後": run_open(close, open_, delayed(next_open, sox <= -0.02)),
        "隔天開盤買；前一晚費半漲 ≥2% 就延後（不追高）": run_open(close, open_, delayed(next_open, sox >= 0.02)),
    }
    table = pd.DataFrame({k: fmt(bt.metrics(v)) for k, v in values.items()}).T
    gaps = (open_ / close.shift(1) - 1)[next_open.notna().any(axis=1)]
    held_gap = (gaps * next_open.dropna(how="all").gt(0)).sum(axis=1) / next_open.dropna(how="all").gt(0).sum(axis=1)

    lines = [
        "# 美股隔夜行情與台股：大盤統計＋營收動能的執行時點",
        "",
        f"- 期間：{START} ~ {close.index[-1].date()}；美股資料來自 FinMind（還原收盤），台股大盤以 0050 代表（排除除息日）",
        "- 台股每天開盤前看得到的是前一晚的美股收盤（台北時間凌晨 4–5 點）",
        "",
        "## 1. 前一晚美股能預測什麼", "",
        corr.map(lambda x: f"{x:.2f}").to_markdown(), "",
        "## 2. 依前一晚費半漲跌分組（0050）", "", bucket.to_markdown(), "",
        "## 3. 營收動能 v0.3 主方案：換股的執行時點", "",
        table.to_markdown(), "",
        f"- 換股隔天，新名單股票的平均開盤跳空：{held_gap.mean():+.2%}（相對前一天收盤）",
        "- 第 3、4 列是延後規則的探索，不是事先決定的方案；延後最多 3 個交易日",
        "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。",
    ]
    (REPORTS / "us_overnight_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
