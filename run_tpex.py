"""A2 上櫃樣本外驗證：v0.3 規則原封不動套用到上櫃股票。輸出 reports/tpex_report.md。

選股池：每個換股日前 20 日平均成交金額前 140 名的上櫃普通股（已有 120 個交易日成交紀錄，含後來下櫃者）。
其他規則與上市 v0.3 主方案完全相同。對照：上櫃選股池等權重、櫃買報酬指數、加權報酬指數。
"""
from __future__ import annotations

import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import equal_weight_universe, target_weights


def tpex_index(start: str = "2013-01-01") -> pd.Series | None:
    for data_id in ("TPEx", "TPEX", "OTC"):
        try:
            df = data._cached(f"benchmark_{data_id}_TR",
                              lambda d=data_id: data._finmind("TaiwanStockTotalReturnIndex", d, start))
        except RuntimeError:
            continue
        if len(df):
            return df.assign(date=pd.to_datetime(df["date"])).set_index("date")["price"]
    return None


def main() -> None:
    pit = universe_pit.load("universe_pit_tpex")
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    coverage = pd.Series({d: len(xs) for d, xs in pit.items()})
    industry = universe_pit.industries()

    w, picks = target_weights(close, volume, rev, V03, START, pit, industry)
    ew = equal_weight_universe(close, volume, w, V03.min_avg_volume_lots, pit)
    values = {"v0.3 規則｜上櫃": bt.run_vbt(close, w), "上櫃選股池等權重": bt.run_vbt(close, ew)}
    start = values["v0.3 規則｜上櫃"].index[0]
    for name, s in (("櫃買報酬指數", tpex_index()), ("加權報酬指數（含息）", data.benchmark())):
        if s is not None:
            s = s.loc[start:]
            values[name] = s / s.iloc[0] * 1_000_000
    check = bt.run_simple(close, w)
    end = values["v0.3 規則｜上櫃"].index[-1]
    perf = {lab: pd.DataFrame({k: fmt(bt.metrics(v.loc[a:b])) for k, v in values.items()}).T
            for lab, (a, b) in {"全期": (START, end), "2015–2020": (START, "2020-12-31"), "2021–至今": ("2021-01-01", end)}.items()}
    yearly = bt.yearly_returns(values)
    yearly.index = yearly.index.year
    n_hold = pd.Series({d: len(x) for d, x in picks.items()})
    names = universe_pit.names()
    latest = max(picks)

    s, e = bt.metrics(values["v0.3 規則｜上櫃"]), bt.metrics(values["上櫃選股池等權重"])
    passed = s["年化報酬"] > e["年化報酬"] and s["Sharpe"] > e["Sharpe"]
    lines = [
        "# A2 上櫃樣本外驗證：v0.3 規則套用到上櫃股票",
        "",
        f"- 期間：{start.date()} ~ {end.date()}；規則與上市 v0.3 主方案**完全相同**（營收條件、同產業最多 3 檔、選不滿補等權重、每月 11 日起第一個交易日換股）",
        f"- 選股池：上櫃普通股，每期前 20 日平均成交金額前 140 名、已有 120 個交易日成交紀錄，含後來下櫃者；歷年成員 {len(members)} 檔",
        "- 上櫃資料在設計 v0.1–v0.6 時完全沒有用過，是乾淨的樣本外",
        "- 限制：下市櫃表沒有標市場別、也不在現有總覽裡的下櫃股，這裡沒有納入（上市版把它們都歸到上市）",
        f"- 成本：每邊 {bt.FEE_PER_SIDE:.4%}；未計滑價（上櫃股流動性較差，實際滑價可能比上市大）",
        "",
    ]
    for lab, t in perf.items():
        lines += [f"## 績效：{lab}", "", t.to_markdown(), ""]
    lines += ["## 逐年報酬", "", yearly.map(lambda x: f"{x:.1%}").to_markdown(), "",
              "## 判定", "",
              f"- 策略 vs 上櫃選股池等權重（全期）：年化 {s['年化報酬']:.1%} vs {e['年化報酬']:.1%}；Sharpe {s['Sharpe']:.2f} vs {e['Sharpe']:.2f}",
              f"- **{'通過' if passed else '未通過'}**（年化與 Sharpe 都要贏同一選股池的等權重，才代表營收選股在上櫃也有效）",
              "", "## 其他", "",
              f"- 平均持股數：{n_hold.mean():.1f} 檔；選股池每期平均 {coverage.mean():.0f} 檔",
              f"- 交叉驗證：vectorbt 年化 {s['年化報酬']:.2%}，簡易引擎 {bt.metrics(check)['年化報酬']:.2%}",
              f"- 最新一期（{latest.date()}）：" + "、".join(f"{x} {names.get(x, '')}" for x in picks[latest]),
              "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所、證券櫃檯買賣中心。"]
    (REPORTS / "tpex_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
