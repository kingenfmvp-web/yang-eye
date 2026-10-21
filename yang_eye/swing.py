"""波段策略：每天收盤後產生訊號，隔天開盤買進，持有固定天數後於收盤賣出。

資金分成 hold 份，每天的新一批（cohort）用一份；每批等權重最多 top_n 檔，選不滿留現金。
開盤即接近漲停（≥ 前收 +9.5%）視為買不到，跳過。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from yang_eye.backtest import FEE_PER_SIDE


@dataclass(frozen=True)
class SwingRule:
    name: str
    hold: int
    top_n: int = 10


def universe_mask(index: pd.DatetimeIndex, columns: pd.Index, pit: dict[pd.Timestamp, list[str]]) -> pd.DataFrame:
    """每個交易日適用的選股池：最近一次（含當天之前）換股日的成員。"""
    mask = pd.DataFrame(np.nan, index=index, columns=columns)
    for d, xs in pit.items():
        if d in mask.index:
            mask.loc[d] = 0.0
            mask.loc[d, [s for s in xs if s in columns]] = 1.0
    return mask.ffill().fillna(0.0).astype(bool)


def signals_trust(trust: pd.DataFrame, vol_shares: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """H1：投信連 3 日買超，分數 = 3 日買超 ÷ 20 日均量（股）。"""
    t = trust.reindex(index=eligible.index, columns=eligible.columns).fillna(0.0)
    streak = (t > 0).rolling(3).sum() == 3
    avg = vol_shares.rolling(20, min_periods=15).mean()
    score = t.rolling(3).sum() / avg.where(avg > 0)
    return score.where(streak & eligible)


def signals_breakout(close: pd.DataFrame, vol_shares: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """H2：收盤創 60 日新高且量 ≥ 前 20 日均量 2 倍，分數 = 量比。"""
    high60 = close.rolling(60, min_periods=60).max()
    ratio = vol_shares / vol_shares.rolling(20, min_periods=15).mean().shift(1)
    ok = (close >= high60) & (ratio >= 2) & eligible
    return ratio.where(ok)


def signals_reversal(close: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """H3：近 5 日跌最多，分數 = -5 日報酬（跌越多分數越高）；排除 -50% 以下的異常值。"""
    r5 = close / close.shift(5) - 1
    return (-r5).where(eligible & (r5 > -0.5) & (r5 < 0))


def run(scores: pd.DataFrame, close: pd.DataFrame, open_: pd.DataFrame, rule: SwingRule,
        start: str, with_cost: bool = True) -> tuple[pd.Series, pd.DataFrame]:
    """回傳每日報酬，以及每一批的明細（訊號日、檔數、該批淨報酬）。"""
    idx = close.index
    c = close.ffill().to_numpy()
    o = open_.to_numpy()
    sc = scores.to_numpy()
    n_days, _ = c.shape
    daily = np.zeros(n_days)
    cohorts = []
    w = 1.0 / rule.hold
    cost = FEE_PER_SIDE if with_cost else 0.0
    start_i = idx.searchsorted(pd.Timestamp(start))
    for t in range(max(start_i, 60), n_days - 1):
        row = sc[t]
        cand = np.where(~np.isnan(row))[0]
        if len(cand) == 0:
            continue
        cand = cand[np.argsort(-row[cand])]
        e = t + 1
        picks = [j for j in cand if o[e, j] > 0 and not np.isnan(o[e, j]) and o[e, j] < c[t, j] * 1.095][: rule.top_n]
        if not picks:
            continue
        x = min(t + rule.hold, n_days - 1)  # 最後一天收盤賣出
        frac = len(picks) / rule.top_n  # 選不滿的部分留現金
        p = np.array(picks)
        # 進場當天：開盤買到收盤；之後每天收盤對收盤
        daily[e] += w * frac * (np.mean(c[e, p] / o[e, p] - 1) - cost)
        for d in range(e + 1, x + 1):
            daily[d] += w * frac * np.mean(c[d, p] / c[d - 1, p] - 1)
        daily[x] -= w * frac * cost
        gross = np.mean(c[x, p] / o[e, p] - 1)
        cohorts.append({"signal_date": idx[t], "n": len(picks), "ret": gross - 2 * cost})
    s = pd.Series(daily, index=idx)
    return s[s.index >= pd.Timestamp(start)], pd.DataFrame(cohorts)


def cohort_stats(cohorts: pd.DataFrame, hold: int) -> dict:
    """每批淨報酬的統計；t 值只用每隔 hold 天的不重疊批次，避免重疊造成高估。"""
    if cohorts.empty:
        return {"批數": 0}
    r = cohorts["ret"]
    sub = r.iloc[::hold]
    t = sub.mean() / sub.std() * np.sqrt(len(sub)) if sub.std() > 0 else np.nan
    return {"批數": len(r), "每批平均淨報酬": f"{r.mean():+.2%}", "勝率": f"{(r > 0).mean():.0%}",
            "t 值（不重疊）": f"{t:.2f}", "平均檔數": f"{cohorts['n'].mean():.1f}"}
