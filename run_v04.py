"""陽之眼 v0.4：大盤濾網（加權報酬指數 < 200 日均線時降低持股）回測，與 v0.3 對照。

輸出 reports/v04_report.md 與 v04_equity_curve.png。
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

import run_v03
from run_backtest import REPORTS, START, fmt
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import market_exposure, target_weights

V03 = run_v03.VARIANTS["v0.3 主方案（產業≤3檔＋補等權重）"]
VARIANTS = {
    "v0.3 主方案": V03,
    "v0.4 主方案（換股日檢查，跌破降到50%）": replace(V03, regime_ma=200, regime_exposure=0.5),
    "敏感度A（每天檢查，跌破降到50%）": replace(V03, regime_ma=200, regime_exposure=0.5, regime_daily=True),
    "敏感度B（換股日檢查，跌破全部出場）": replace(V03, regime_ma=200, regime_exposure=0.0),
}
MAIN = "v0.4 主方案（換股日檢查，跌破降到50%）"
run_v03.TITLE = "陽之眼 v0.4｜大盤濾網 vs v0.3（時點正確選股池，已扣成本）"
run_v03.COLORS = {"v0.3 主方案": "#2a78d6", MAIN: "#eb6834", "加權報酬指數": "#1baf7a"}


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    industry = universe_pit.industries()
    names = universe_pit.names()
    market = data.benchmark()

    values, weights_all = {}, {}
    for label, p in VARIANTS.items():
        w, _ = target_weights(close, volume, rev, p, START, pit, industry, market)
        values[label] = bt.run_vbt(close, w)
        weights_all[label] = w
    bench = market[market.index >= values["v0.3 主方案"].index[0]]
    values["加權報酬指數"] = bench / bench.iloc[0] * 1_000_000

    end = values["v0.3 主方案"].index[-1]
    periods = {"全期": (START, end), "2015–2020": (START, "2020-12-31"), "2021–至今": ("2021-01-01", end)}
    tables = {label: pd.DataFrame({k: fmt(bt.metrics(v.loc[a:b])) for k, v in values.items()}).T
              for label, (a, b) in periods.items()}

    def worst(v: pd.Series, a: str, b: str) -> str:
        x = v.loc[a:b]
        return f"{(x / x.cummax() - 1).min():.1%}"
    windows = {"2018 下半年–2020 疫情": ("2018-06-01", "2020-06-30"), "2021–2022 航運泡沫與升息": ("2021-07-01", "2022-12-31"),
               "2024 下半年–2025 關稅": ("2024-07-01", "2025-06-30")}
    dd = pd.DataFrame({w: {k: worst(v, a, b) for k, v in values.items()} for w, (a, b) in windows.items()})

    expo = market_exposure(market, VARIANTS[MAIN]).loc[START:]
    reb = weights_all[MAIN].dropna(how="all").index
    filt_months = int((expo.reindex(reb) < 1).sum())
    yearly = bt.yearly_returns({k: values[k] for k in ("v0.3 主方案", MAIN, "加權報酬指數")})
    yearly.index = yearly.index.year
    check = bt.run_simple(close, weights_all[MAIN])
    run_v03.plot({k: values[k] for k in run_v03.COLORS}, REPORTS / "v04_equity_curve.png")

    lines = [
        "# 陽之眼 v0.4 回測報告：大盤濾網",
        "",
        f"- 期間：{values['v0.3 主方案'].index[0].date()} ~ {end.date()}；選股池、選股、產業上限、空位補滿都與 v0.3 主方案相同",
        "- v0.4 只加一條：**加權報酬指數低於 200 日均線時，總持股降到 50%，其餘留現金**（用前一天收盤判斷）",
        "- 這條規則在第一版風控設計時就列出，不是看過回測才加的；主方案事先決定，敏感度 A、B 只看結論穩不穩",
        f"- 主方案在 {len(reb)} 個換股月中，有 {filt_months} 個月觸發濾網",
        f"- 成本：每邊 {bt.FEE_PER_SIDE:.4%}；未計滑價",
        "",
    ]
    for label, t in tables.items():
        lines += [f"## 績效：{label}", "", t.to_markdown(), ""]
    lines += ["## 各次大跌期間的最大回撤", "", dd.to_markdown(), "",
              "## 逐年報酬", "", yearly.map(lambda x: f"{x:.1%}").to_markdown(), "",
              "## 其他", "",
              f"- 交叉驗證（主方案）：vectorbt 年化 {bt.metrics(values[MAIN])['年化報酬']:.2%}，"
              f"簡易引擎 {bt.metrics(check)['年化報酬']:.2%}",
              f"- 目前大盤狀態（{expo.index[-1].date()}）：{'低於' if expo.iloc[-1] < 1 else '高於'} 200 日均線，"
              f"主方案目標持股 {expo.iloc[-1]:.0%}",
              "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "v04_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
