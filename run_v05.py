"""陽之眼 v0.5：個股風控（移動停損、避開過熱股）回測，與 v0.3 對照。

輸出 reports/v05_report.md 與 v05_equity_curve.png。
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

import run_v03
from run_backtest import REPORTS, START, fmt
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import target_weights

V03 = run_v03.VARIANTS["v0.3 主方案（產業≤3檔＋補等權重）"]
VARIANTS = {
    "v0.3 主方案": V03,
    "v0.5 主方案（移動停損 20%）": replace(V03, trailing_stop=0.20),
    "敏感度A（移動停損 15%）": replace(V03, trailing_stop=0.15),
    "敏感度B（排除 60 日漲幅 >50%）": replace(V03, max_ret60=0.50),
}
MAIN = "v0.5 主方案（移動停損 20%）"
run_v03.TITLE = "陽之眼 v0.5｜個股移動停損 vs v0.3（時點正確選股池，已扣成本）"
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

    reb = weights_all["v0.3 主方案"].dropna(how="all").index
    extra = weights_all[MAIN].drop(index=reb, errors="ignore")
    n_stops = int(extra.notna().sum().sum())
    yearly = bt.yearly_returns({k: values[k] for k in ("v0.3 主方案", MAIN, "加權報酬指數")})
    yearly.index = yearly.index.year
    check = bt.run_simple(close, weights_all[MAIN])
    run_v03.plot({k: values[k] for k in run_v03.COLORS}, REPORTS / "v05_equity_curve.png")

    lines = [
        "# 陽之眼 v0.5 回測報告：個股風控",
        "",
        f"- 期間：{values['v0.3 主方案'].index[0].date()} ~ {end.date()}；選股池、選股、產業上限、空位補滿都與 v0.3 主方案相同",
        "- v0.5 只加一條：**選出的股票從買進後最高收盤回落 20%，隔天收盤賣出，資金留現金到下次換股**；補位的等權重部位不停損",
        "- 針對 v0.4 找到的問題：2018–2020 策略跌 -57.8% 時大盤只跌 -15.1%，風險來自個股而非大盤",
        "- 主方案事先決定，敏感度 A、B 只看結論穩不穩；B 是另一種做法（選股時避開過熱股）",
        f"- 主方案共觸發 {n_stops} 次停損（{len(reb)} 個換股月）",
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
              "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "v05_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
