"""算法一：營收動能。

月營收法定公告期限是次月 10 日，所以 m 月營收只能在 m+1 月 10 日之後使用。
我們在每月「第一個 >= 11 日的交易日」收盤換股，避免偷看未來。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RevenueMomentumParams:
    min_yoy3: float = 0.20        # 近 3 月營收年增率門檻
    require_new_high: bool = True  # 當月營收需為近 12 月新高
    require_accel: bool = True     # 年增率需加速
    min_avg_volume_lots: float = 1000  # 近 20 日均量（張）
    top_n: int = 10
    rebalance_day: int = 11
    max_per_industry: int | None = None  # v0.3：同產業最多幾檔（None＝不限）
    fill: str | None = None  # v0.3：選不滿時空位怎麼放："ew"＝選股池等權重、ETF 代號（如 "0050"）、None＝留現金
    regime_ma: int | None = None  # v0.4：大盤低於 N 日均線時降低持股（None＝不用濾網）
    regime_exposure: float = 0.5  # v0.4：濾網觸發時的總持股比例
    regime_daily: bool = False  # v0.4：True＝每天檢查，大盤一穿越均線就調整；False＝只在換股日檢查
    trailing_stop: float | None = None  # v0.5：選出的股票從買進後最高收盤回落此比例，隔天收盤賣出，資金留現金到下次換股
    max_ret60: float | None = None  # v0.5：選股時排除近 60 日漲幅超過此比例的過熱股
    trust_mode: str | None = None  # v0.6：投信買超的用法："rank"＝與營收各半排序、"filter"＝須投信淨買超 > 0


def market_exposure(market: pd.Series, p: RevenueMomentumParams) -> pd.Series:
    """每天的目標總持股比例；用前一天的收盤判斷，避免偷看當天。"""
    ma = market.rolling(p.regime_ma, min_periods=p.regime_ma).mean()
    below = (market < ma).shift(1).fillna(False).astype(bool)
    return below.map({True: p.regime_exposure, False: 1.0})


def revenue_signals(rev: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """把月營收長表轉成以「營收月份」為索引的訊號寬表。"""
    rev = rev.assign(period=pd.PeriodIndex.from_fields(
        year=rev["revenue_year"], month=rev["revenue_month"], freq="M"))
    wide = (rev.pivot_table(index="period", columns="stock_id", values="revenue", aggfunc="last")
            .sort_index())
    wide = wide.reindex(pd.period_range(wide.index.min(), wide.index.max(), freq="M"))
    wide = wide.where(wide > 0)

    r3 = wide.rolling(3).sum()
    yoy3 = r3 / r3.shift(12) - 1
    yoy1 = wide / wide.shift(12) - 1
    accel = yoy1 - yoy1.shift(1).rolling(3).mean()
    new_high = wide >= wide.rolling(12).max()
    return {"yoy3": yoy3, "yoy1": yoy1, "accel": accel, "new_high": new_high}


def rebalance_dates(trading_days: pd.DatetimeIndex, day: int = 11) -> pd.DatetimeIndex:
    s = pd.Series(trading_days, index=trading_days)
    s = s[s.dt.day >= day]
    return pd.DatetimeIndex(s.groupby(s.index.to_period("M")).first().values)


def select(df: pd.DataFrame, p: RevenueMomentumParams, industry: dict[str, str] | None) -> list[str]:
    """依 3 月營收 YoY 由高到低挑，同產業超過上限就跳過。沒有產業別的股票各自算一類。"""
    ranked = df.sort_values("yoy3", ascending=False).index
    if p.max_per_industry is None or industry is None:
        return ranked[:p.top_n].tolist()
    picks, count = [], {}
    for sid in ranked:
        ind = industry.get(sid, f"?{sid}")
        if count.get(ind, 0) >= p.max_per_industry:
            continue
        picks.append(sid)
        count[ind] = count.get(ind, 0) + 1
        if len(picks) == p.top_n:
            break
    return picks


def target_weights(close: pd.DataFrame, volume: pd.DataFrame, rev: pd.DataFrame,
                   p: RevenueMomentumParams, start: str = "2015-01-01",
                   universe: dict[pd.Timestamp, list[str]] | None = None,
                   industry: dict[str, str] | None = None,
                   market: pd.Series | None = None,
                   trust_ratio: pd.DataFrame | None = None
                   ) -> tuple[pd.DataFrame, dict[pd.Timestamp, list[str]]]:
    """回傳每個換股日的目標權重（其餘日期 NaN）與每期持股清單。

    universe 給定時，每期只能從該期的時點正確選股池中挑。
    """
    sig = revenue_signals(rev)
    avg_vol = volume.rolling(20, min_periods=15).mean()
    dates = rebalance_dates(close.index, p.rebalance_day)
    dates = dates[dates >= pd.Timestamp(start)]

    weights = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    picks_log = {}
    for d in dates:
        period = d.to_period("M") - 1  # 這天能用的最新營收是上個月的
        if period not in sig["yoy3"].index:
            continue
        df = pd.DataFrame({k: v.loc[period] for k, v in sig.items()})
        df = df.reindex(close.columns)
        df["vol"] = avg_vol.loc[d]
        df["tradable"] = close.loc[d].notna() & (close.loc[d] > 0)

        mask = (df["yoy3"] > p.min_yoy3) & (df["vol"] > p.min_avg_volume_lots) & df["tradable"]
        if universe is not None:
            mask &= df.index.isin(universe.get(d, []))
        if p.require_new_high:
            mask &= df["new_high"].fillna(False).astype(bool)
        if p.require_accel:
            mask &= df["accel"] > 0
        if p.max_ret60 is not None:
            i = close.index.get_loc(d)
            ret60 = close.iloc[i] / close.iloc[max(0, i - 60)] - 1
            mask &= ~(ret60 > p.max_ret60)
        cand = df[mask]
        if p.trust_mode and trust_ratio is not None:
            tr = trust_ratio.loc[:d].iloc[-1].reindex(cand.index) if len(trust_ratio.loc[:d]) else pd.Series(dtype=float)
            if p.trust_mode == "filter":
                cand = cand[tr.reindex(cand.index) > 0]
            elif p.trust_mode == "rank" and len(cand):
                # 營收年增率與投信買超在候選股內各自排名，平均後當排序依據
                key = (cand["yoy3"].rank(pct=True) + tr.rank(pct=True).fillna(0.5)) / 2
                cand = cand.assign(yoy3=key)
        picks = select(cand, p, industry)

        # 每檔固定 1/top_n（不放大單檔部位）；選不滿的空位依 p.fill 處理
        weights.loc[d] = 0.0
        weights.loc[d, picks] = 1.0 / p.top_n
        spare = 1.0 - len(picks) / p.top_n
        if spare > 0 and p.fill == "ew":
            pool = (df["vol"] > p.min_avg_volume_lots) & df["tradable"]
            if universe is not None:
                pool &= df.index.isin(universe.get(d, []))
            pool = pool[pool].index.difference(picks)
            if len(pool):
                weights.loc[d, pool] += spare / len(pool)
        elif spare > 0 and p.fill and p.fill in close.columns and close.loc[d, p.fill] > 0:
            weights.loc[d, p.fill] += spare
        picks_log[d] = picks

    if p.trailing_stop:
        weights = apply_trailing_stop(weights, picks_log, close, p.trailing_stop)

    if p.regime_ma and market is not None:
        expo = market_exposure(market, p).reindex(close.index).ffill().fillna(1.0)
        base = weights.ffill()  # 最近一次換股的目標權重
        if p.regime_daily:  # 換股日之外，曝險變動的那天也調整一次
            flips = expo.ne(expo.shift(1)) & base.notna().any(axis=1)
            weights.loc[flips] = base.loc[flips]
        weights = weights.mul(expo, axis=0)
    return weights, picks_log


def apply_trailing_stop(weights: pd.DataFrame, picks_log: dict[pd.Timestamp, list[str]],
                        close: pd.DataFrame, pct: float) -> pd.DataFrame:
    """在換股日之間加入停損單：只有被停損的那一欄有值（0），其他欄 NaN 代表不動。

    最高價從連續持有的第一天算起；用前一天收盤判斷，當天收盤賣出，避免偷看。
    """
    weights = weights.copy()
    dates = sorted(picks_log)
    entry: dict[str, pd.Timestamp] = {}
    for k, d in enumerate(dates):
        end = dates[k + 1] if k + 1 < len(dates) else close.index[-1] + pd.Timedelta(days=1)
        entry = {s: entry.get(s, d) for s in picks_log[d]}  # 續抱的股票沿用原本的買進日
        period = close.index[(close.index > d) & (close.index < end)]
        for s in picks_log[d]:
            px = close[s].ffill()
            peak = px.loc[entry[s]:].cummax()
            dd = (px / peak - 1).shift(1).reindex(period)
            hit = dd[dd <= -pct]
            if len(hit):
                weights.loc[hit.index[0], s] = 0.0
                entry.pop(s, None)  # 停損後下次換股若再選到，重新起算
    return weights


def equal_weight_universe(close: pd.DataFrame, volume: pd.DataFrame, weights: pd.DataFrame,
                          min_avg_volume_lots: float = 1000,
                          universe: dict[pd.Timestamp, list[str]] | None = None) -> pd.DataFrame:
    """對照組：同樣換股日、同樣流動性門檻，持有選股池內全部股票等權重。"""
    avg_vol = volume.rolling(20, min_periods=15).mean()
    ew = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for d in weights.dropna(how="all").index:
        ok = (avg_vol.loc[d] > min_avg_volume_lots) & (close.loc[d] > 0)
        if universe is not None:
            ok &= ok.index.isin(universe.get(d, []))
        ew.loc[d] = 0.0
        ew.loc[d, ok[ok].index] = 1.0 / ok.sum()
    return ew
