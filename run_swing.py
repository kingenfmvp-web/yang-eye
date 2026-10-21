"""波段策略研究：三個事先決定的假設（投信認養、帶量突破、短期反轉）。輸出 reports/swing_report.md。"""
from __future__ import annotations

import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_us_overnight import adjusted_open
from yang_eye import backtest as bt
from yang_eye import data, factors, swing, universe_pit

RULES = {
    "H1 投信認養（連3日買超，持有10天）": swing.SwingRule("trust", hold=10),
    "H2 帶量突破（60日新高＋量2倍，持有10天）": swing.SwingRule("breakout", hold=10),
    "H3 短期反轉（5日跌最多，持有5天）": swing.SwingRule("reversal", hold=5),
}


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, _ = data.load_panel(members)
    open_ = adjusted_open(list(close.columns), close)
    vol_shares = volume * 1000
    avg_lots = volume.rolling(20, min_periods=15).mean()
    eligible = swing.universe_mask(close.index, close.columns, pit) & (avg_lots > 1000) & (close > 0)
    trust = factors.trust_flow(members)

    scores = {
        "trust": swing.signals_trust(trust, vol_shares, eligible),
        "breakout": swing.signals_breakout(close, vol_shares, eligible),
        "reversal": swing.signals_reversal(close, eligible),
    }
    bench = data.benchmark()
    values, gross_values, stats, turnover = {}, {}, {}, {}
    for label, rule in RULES.items():
        r, coh = swing.run(scores[rule.name], close, open_, rule, START, with_cost=True)
        rg, _ = swing.run(scores[rule.name], close, open_, rule, START, with_cost=False)
        values[label] = 1_000_000 * (1 + r).cumprod()
        gross_values[label] = 1_000_000 * (1 + rg).cumprod()
        stats[label] = {
            "全期": swing.cohort_stats(coh, rule.hold),
            "2015–2020": swing.cohort_stats(coh[coh["signal_date"] < "2021-01-01"], rule.hold),
            "2021–": swing.cohort_stats(coh[coh["signal_date"] >= "2021-01-01"], rule.hold),
        }
        years = (r.index[-1] - r.index[0]).days / 365.25
        turnover[label] = len(coh) * coh["n"].mean() / years if len(coh) else 0
    b = bench[bench.index >= values[next(iter(values))].index[0]]
    values["加權報酬指數（含息）"] = b / b.iloc[0] * 1_000_000

    end = close.index[-1]
    perf = {lab: pd.DataFrame({k: fmt(bt.metrics(v.loc[a:z])) for k, v in values.items()}).T
            for lab, (a, z) in {"全期": (START, end), "2015–2020": (START, "2020-12-31"),
                                "2021–至今": ("2021-01-01", end)}.items()}
    cost_tbl = pd.DataFrame({k: {"扣成本前 年化": f"{bt.metrics(gross_values[k])['年化報酬']:.1%}",
                                 "扣成本後 年化": f"{bt.metrics(values[k])['年化報酬']:.1%}",
                                 "每年交易檔次（約）": f"{turnover[k]:,.0f}"} for k in RULES}).T
    stat_rows = []
    for label, by in stats.items():
        for per, s in by.items():
            stat_rows.append({"策略": label, "期間": per, **s})

    lines = [
        "# 波段策略研究",
        "",
        f"- 期間：{START} ~ {end.date()}；選股池＝當時成交金額前 140 名（含後來下市股），20 日均量 > 1000 張",
        "- 三個假設與參數都在回測前決定，不依結果調整：",
        "  - **H1 投信認養**：投信連續 3 天買超，依 3 日買超 ÷ 20 日均量排名，取前 10，持有 10 個交易日",
        "  - **H2 帶量突破**：收盤創 60 日新高且成交量 ≥ 前 20 日均量 2 倍，依量比排名，取前 10，持有 10 個交易日",
        "  - **H3 短期反轉**：近 5 日跌最多的前 10 檔，持有 5 個交易日",
        "- 執行：訊號日收盤後決定，**隔天開盤買進**，持有期最後一天收盤賣出；開盤 ≥ 前收 +9.5% 視為買不到",
        f"- 資金：分成「持有天數」份，每天新的一批用一份，每批等權重、選不滿留現金；成本每邊 {bt.FEE_PER_SIDE:.4%}（一買一賣 0.585%），未計滑價",
        "",
        "## 1. 每一批的表現（扣成本）", "",
        "t 值只用不重疊的批次計算；大於 2 才算顯著。", "",
        pd.DataFrame(stat_rows).to_markdown(index=False), "",
        "## 2. 成本的影響", "", cost_tbl.to_markdown(), "",
        "## 3. 整體績效（扣成本）", "",
    ]
    for lab, t in perf.items():
        lines += [f"### {lab}", "", t.to_markdown(), ""]
    lines += ["> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "swing_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
