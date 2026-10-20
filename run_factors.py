"""多因子研究：各因子的 IC 與五分位報酬，以及多因子選股的回測。輸出 reports/factors_report.md。

權重事先固定（成長 30%、品質 20%、價值 15%、籌碼 20%、動能 15%），不依回測結果調整。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, factors, universe_pit
from yang_eye.strategy import rebalance_dates, revenue_signals, select, target_weights

TOP_N = 10
MAX_PER_INDUSTRY = 3
NAMES = list(factors.WEIGHTS) + ["總分"]


def main() -> None:
    pit = universe_pit.load()
    members_all = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members_all)
    close["0050"] = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    industry = universe_pit.industries()
    sig = revenue_signals(rev)
    pe, roe = factors.per_panel(members_all)
    trust = factors.trust_flow(members_all)
    margin = factors.op_margin_change(members_all)
    coverage = {"本益比": pe.shape[1], "三大法人": trust.shape[1], "損益表": len(margin)}
    avg_lots = volume.rolling(20, min_periods=15).mean()
    vol_shares = volume * 1000

    dates = [d for d in rebalance_dates(close.index) if d >= pd.Timestamp(START) and d in pit]
    weights = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    ic = {k: {} for k in NAMES}
    quint = []
    picks_log = {}
    for k, d in enumerate(dates):
        ok = (avg_lots.loc[d] > 1000) & (close.loc[d] > 0)
        members = [s for s in pit[d] if ok.get(s, False)]
        period = d.to_period("M") - 1
        yoy3 = sig["yoy3"].loc[period] if period in sig["yoy3"].index else pd.Series(dtype=float)
        sc = factors.factor_scores(d, members, close, vol_shares, yoy3, pe, roe, trust, margin)
        nxt = dates[k + 1] if k + 1 < len(dates) else close.index[-1]
        fwd = (close.loc[nxt, members] / close.loc[d, members] - 1)
        for name in NAMES:
            ic[name][d] = factors.spearman(sc[name], fwd)
        q = pd.qcut(sc["總分"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        quint.append(fwd.groupby(q, observed=True).mean().rename(d))
        ranked = sc.sort_values("總分", ascending=False)
        picks = select(ranked.assign(yoy3=ranked["總分"]), _p(), industry)
        weights.loc[d] = 0.0
        weights.loc[d, picks] = 1.0 / TOP_N
        picks_log[d] = picks

    ic_df = pd.DataFrame(ic)
    split = pd.Timestamp("2021-01-01")

    def ic_stats(s: pd.Series) -> dict:
        s = s.dropna()
        return {"平均 IC": f"{s.mean():.3f}", "t 值": f"{s.mean() / s.std() * np.sqrt(len(s)):.2f}",
                "IC>0 的月份": f"{(s > 0).mean():.0%}"}
    ic_table = pd.DataFrame({
        f"{name}｜{lab}": ic_stats(ic_df[name][mask])
        for name in NAMES
        for lab, mask in (("全期", ic_df.index >= START), ("2015–2020", ic_df.index < split), ("2021–", ic_df.index >= split))
    }).T
    qt = pd.DataFrame(quint)
    q_table = pd.DataFrame({
        "全期": qt.mean(), "2015–2020": qt[qt.index < split].mean(), "2021–": qt[qt.index >= split].mean()
    }).T.map(lambda x: f"{x:+.2%}")
    q_table.columns = [f"第{c}組" + ("（最低）" if c == 1 else "（最高）" if c == 5 else "") for c in q_table.columns]

    # 回測：多因子、v0.3，以及各自的核心衛星
    w3, _ = target_weights(close, volume, rev, V03, START, pit, industry)

    def core_sat(w: pd.DataFrame) -> pd.DataFrame:
        b = w * 0.5
        rows = w.notna().any(axis=1)
        b.loc[rows, "0050"] = b.loc[rows, "0050"].fillna(0) + 0.5
        return b
    values = {
        "多因子 前10檔": bt.run_vbt(close, weights),
        "v0.3 營收動能": bt.run_vbt(close, w3),
        "核心衛星：50% 0050 ＋ 50% 多因子": bt.run_vbt(close, core_sat(weights)),
        "核心衛星：50% 0050 ＋ 50% v0.3": bt.run_vbt(close, core_sat(w3)),
    }
    bench = data.benchmark()
    bench = bench[bench.index >= values["v0.3 營收動能"].index[0]]
    values["加權報酬指數（含息）"] = bench / bench.iloc[0] * 1_000_000
    end = values["v0.3 營收動能"].index[-1]
    perf = {lab: pd.DataFrame({k: fmt(bt.metrics(v.loc[a:b])) for k, v in values.items()}).T
            for lab, (a, b) in {"全期": (START, end), "2015–2020": (START, "2020-12-31"), "2021–至今": ("2021-01-01", end)}.items()}
    overlap = np.mean([len(set(picks_log[d]) & set(_v03_picks(w3, d))) for d in picks_log])
    names = universe_pit.names()
    latest = max(picks_log)

    lines = [
        "# 多因子研究",
        "",
        f"- 期間：{dates[0].date()} ~ {end.date()}，{len(dates)} 個換股月；選股池與 v0.2 起相同（時點正確，含下市股），另加 20 日均量 > 1000 張",
        "- 因子（每期在選股池內轉成排名百分位，缺值給中性 0.5）：",
        "  - **成長**：近 3 月營收年增率（上個月營收，10 日公告後才用）",
        "  - **品質**：ROE（≈ 股價淨值比 ÷ 本益比，前一交易日）與近四季營業利益率較一年前的變化（依季報公告期限才用）各半",
        "  - **價值**：目前本益比在自己近 5 年的百分位，越低越好；虧損（無本益比）視為中性",
        "  - **籌碼**：投信近 20 日買超股數 ÷ 近 20 日成交股數",
        "  - **動能**：近 120 日報酬，扣掉最近 20 日",
        f"- 總分權重事先固定：{'、'.join(f'{k} {v:.0%}' for k, v in factors.WEIGHTS.items())}",
        f"- 選股：總分前 {TOP_N} 檔，同產業最多 {MAX_PER_INDUSTRY} 檔，每檔 10%，每月換股；成本每邊 {bt.FEE_PER_SIDE:.4%}",
        f"- 資料覆蓋（選股池歷年 {len(members_all)} 檔）：" + "、".join(f"{k} {v} 檔" for k, v in coverage.items()),
        "",
        "## 1. 各因子的預測力（IC：因子排名與下個月報酬排名的相關係數）",
        "",
        "IC 平均值大於 0 且 t 值大於 2，才算有穩定的預測力。",
        "", ic_table.to_markdown(), "",
        "## 2. 依總分分五組，下個月的平均報酬", "", q_table.to_markdown(), "",
        "## 3. 回測", "",
    ]
    for lab, t in perf.items():
        lines += [f"### {lab}", "", t.to_markdown(), ""]
    lines += [f"- 多因子與 v0.3 平均每期重疊 {overlap:.1f} 檔",
              f"- 最新一期多因子選股（{latest.date()}）：" + "、".join(f"{s} {names.get(s, '')}" for s in picks_log[latest]),
              "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "factors_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def _p():
    from dataclasses import replace
    from yang_eye.strategy import RevenueMomentumParams
    return replace(RevenueMomentumParams(), top_n=TOP_N, max_per_industry=MAX_PER_INDUSTRY)


def _v03_picks(w3: pd.DataFrame, d: pd.Timestamp) -> list[str]:
    if d not in w3.index or w3.loc[d].isna().all():
        return []
    row = w3.loc[d]
    return row[row >= 0.0999].index.tolist()


if __name__ == "__main__":
    main()
