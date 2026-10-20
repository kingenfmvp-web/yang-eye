"""多因子：成長、品質、價值、籌碼、動能。每個換股日只用當時已公布的資料。

所有因子在每期選股池內轉成 0～1 的排名百分位（越大越好），缺值給 0.5（中性）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from yang_eye.data import CACHE

WEIGHTS = {"成長": 0.30, "品質": 0.20, "價值": 0.15, "籌碼": 0.20, "動能": 0.15}

# 季報公布期限：季末 → 最早可用日（Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31）；保守起見各加 1 天
_LAG = {3: (5, 16), 6: (8, 15), 9: (11, 15), 12: (4, 1)}


def available_from(quarter_end: pd.Timestamp) -> pd.Timestamp:
    m, d = _LAG[quarter_end.month]
    year = quarter_end.year + (1 if quarter_end.month == 12 else 0)
    return pd.Timestamp(year=year, month=m, day=d)


def _read(kind: str, sid: str) -> pd.DataFrame | None:
    path = CACHE / f"{kind}/{sid}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return None if df.empty else df


def per_panel(stock_ids: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """每日本益比與 ROE（≈ PBR / PER），寬表。"""
    pe, roe = {}, {}
    for sid in stock_ids:
        df = _read("per", sid)
        if df is None:
            continue
        df = df.assign(date=pd.to_datetime(df["date"])).set_index("date")
        pe[sid] = df["PER"].where(df["PER"] > 0)
        roe[sid] = (df["PBR"] / df["PER"]).where((df["PER"] > 0) & (df["PBR"] > 0))
    return pd.DataFrame(pe).sort_index(), pd.DataFrame(roe).sort_index()


def trust_flow(stock_ids: list[str]) -> pd.DataFrame:
    """投信每日買賣超（股），寬表。"""
    out = {}
    for sid in stock_ids:
        df = _read("inst", sid)
        if df is None:
            continue
        df = df[df["name"] == "Investment_Trust"]
        out[sid] = (df["buy"] - df["sell"]).set_axis(pd.to_datetime(df["date"]))
    return pd.DataFrame(out).sort_index()


def op_margin_change(stock_ids: list[str]) -> dict[str, pd.DataFrame]:
    """每檔：每季的近四季營業利益率，與一年前相比的變化，以及最早可用日。"""
    out = {}
    for sid in stock_ids:
        df = _read("fin", sid)
        if df is None:
            continue
        df = df[df["type"].isin(["Revenue", "OperatingIncome"])]
        q = df.pivot_table(index="date", columns="type", values="value", aggfunc="last")
        if not {"Revenue", "OperatingIncome"} <= set(q.columns):
            continue
        q.index = pd.to_datetime(q.index)
        q = q.sort_index()
        ttm = q.rolling(4, min_periods=4).sum()
        margin = ttm["OperatingIncome"] / ttm["Revenue"].where(ttm["Revenue"] > 0)
        chg = (margin - margin.shift(4)).dropna()
        out[sid] = pd.DataFrame({"chg": chg, "avail": [available_from(d) for d in chg.index]})
    return out


def _latest_before(panel: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    """d 之前（不含 d）最後一筆有值的資料。"""
    sub = panel.loc[: d - pd.Timedelta(days=1)]
    return sub.ffill().iloc[-1] if len(sub) else pd.Series(dtype=float)


def pct_rank(s: pd.Series, members: list[str], higher_is_better: bool = True) -> pd.Series:
    s = s.reindex(members)
    r = s.rank(pct=True, ascending=higher_is_better)
    return r.fillna(0.5)


def factor_scores(d: pd.Timestamp, members: list[str], close: pd.DataFrame, volume_shares: pd.DataFrame,
                  yoy3: pd.Series, pe: pd.DataFrame, roe: pd.DataFrame, trust: pd.DataFrame,
                  margin: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """回傳 members × {成長, 品質, 價值, 籌碼, 動能, 總分} 的排名分數。"""
    i = close.index.get_loc(d)
    # 成長：上個月公布的近 3 月營收年增率
    growth = pct_rank(yoy3, members)
    # 品質：ROE 與營業利益率變化各半
    roe_now = _latest_before(roe, d)
    chg = pd.Series({s: m.loc[m["avail"] <= d, "chg"].iloc[-1] for s, m in margin.items()
                     if s in members and (m["avail"] <= d).any()}, dtype=float)
    quality = (pct_rank(roe_now, members) + pct_rank(chg, members)) / 2
    # 價值：目前本益比在自己近 5 年的百分位，越低越便宜
    hist = pe.loc[d - pd.DateOffset(years=5): d - pd.Timedelta(days=1)]
    if len(hist):
        rel = (hist.rank(pct=True).iloc[-1]).where(hist.notna().sum() >= 250)
    else:
        rel = pd.Series(dtype=float)
    value = pct_rank(rel, members, higher_is_better=False)
    # 籌碼：投信近 20 日買超 ÷ 近 20 日成交量
    flow = trust.loc[: d - pd.Timedelta(days=1)].tail(20).sum()
    vol20 = volume_shares.iloc[max(0, i - 20):i].sum()
    chip = pct_rank(flow / vol20.where(vol20 > 0), members)
    # 動能：近 120 日報酬扣掉最近 20 日
    mom = close.iloc[max(0, i - 20)] / close.iloc[max(0, i - 120)] - 1
    momentum = pct_rank(mom, members)
    df = pd.DataFrame({"成長": growth, "品質": quality, "價值": value, "籌碼": chip, "動能": momentum})
    df["總分"] = sum(df[k] * w for k, w in WEIGHTS.items())
    return df


def spearman(a: pd.Series, b: pd.Series) -> float:
    ok = a.notna() & b.notna()
    if ok.sum() < 20:
        return np.nan
    return float(a[ok].rank().corr(b[ok].rank()))
