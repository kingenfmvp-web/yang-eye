"""回測：vectorbt 主引擎 ＋ 一個簡單的 pandas 引擎交叉驗證。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt

# 手續費 0.1425% ×2 ＋ 證交稅 0.3% = 一趟 0.585%；vectorbt 只吃對稱費率，拆成每邊 0.2925%
FEE_PER_SIDE = (0.001425 * 2 + 0.003) / 2


def run_vbt(close: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    pf = vbt.Portfolio.from_orders(
        close=close.ffill(),
        size=weights,
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        call_seq="auto",
        fees=FEE_PER_SIDE,
        init_cash=1_000_000,
        freq="1D",
    )
    start = weights.dropna(how="all").index[0]
    v = pf.value()
    return v[v.index >= start]


def run_simple(close: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    """逐日讓權重隨價格漂移，換股日在收盤調整到目標權重並依換手率扣成本。"""
    rets = close.ffill().pct_change().fillna(0).to_numpy()
    target = weights.to_numpy()
    is_reb = ~np.isnan(target).all(axis=1)
    cur = np.zeros(target.shape[1])
    out = np.zeros(len(rets))
    for i in range(len(rets)):
        cash = 1 - cur.sum()
        grown = cur * (1 + rets[i])
        total = grown.sum() + cash
        cur = grown / total
        r = total - 1
        if is_reb[i]:  # NaN 的欄位不動（停損單只調整單一欄）
            mask = ~np.isnan(target[i])
            new = cur.copy()
            new[mask] = target[i][mask]
            r -= np.abs(new - cur).sum() * FEE_PER_SIDE * (1 + r)
            cur = new
        out[i] = r
    port_ret = pd.Series(out, index=weights.index)
    start = weights.dropna(how="all").index[0]
    port_ret = port_ret[port_ret.index >= start]
    return 1_000_000 * (1 + port_ret).cumprod()


def metrics(value: pd.Series) -> dict:
    r = value.pct_change().dropna()
    years = (value.index[-1] - value.index[0]).days / 365.25
    cagr = (value.iloc[-1] / value.iloc[0]) ** (1 / years) - 1
    dd = value / value.cummax() - 1
    monthly = value.resample("ME").last().pct_change().dropna()
    return {
        "年化報酬": cagr,
        "年化波動": r.std() * np.sqrt(252),
        "Sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan,
        "最大回撤": dd.min(),
        "月勝率": (monthly > 0).mean(),
        "總報酬": value.iloc[-1] / value.iloc[0] - 1,
    }


def yearly_returns(values: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame({k: v.resample("YE").last().pct_change().fillna(
        v.resample("YE").last().iloc[0] / v.iloc[0] - 1) for k, v in values.items()})
