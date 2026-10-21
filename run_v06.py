"""陽之眼 v0.6：把投信買超加進月換股，做樣本外驗證。輸出 reports/v06_report.md。

步驟一：只看樣本內（2015–2020）的 Sharpe，在 A（投信加分）與 B（投信過濾）之間選一個。
步驟二：拿選中的版本在樣本外（2021–至今）和 v0.3 比較；另一個版本也列出但不拿來做判斷。
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, factors, universe_pit
from yang_eye.strategy import target_weights

IS_END, OOS_START = "2020-12-31", "2021-01-01"
CANDIDATES = {
    "A 投信加分（營收排名與投信排名各半）": replace(V03, trust_mode="rank"),
    "B 投信過濾（投信 20 日淨買超 > 0）": replace(V03, trust_mode="filter"),
}


def core_sat(w: pd.DataFrame) -> pd.DataFrame:
    b = w * 0.5
    rows = w.notna().any(axis=1)
    b.loc[rows, "0050"] = b.loc[rows, "0050"].fillna(0) + 0.5
    return b


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    close["0050"] = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    industry = universe_pit.industries()
    trust = factors.trust_flow(members).reindex(index=close.index, columns=close.columns).fillna(0.0)
    vol_sh = volume * 1000
    # 投信近 20 日淨買超 ÷ 近 20 日成交量；往後移一天，換股日只看得到前一天為止的資料
    trust_ratio = (trust.rolling(20).sum() / vol_sh.rolling(20).sum().where(lambda x: x > 0)).shift(1)

    runs, weights = {}, {}
    for label, p in {"v0.3（現行）": V03, **CANDIDATES}.items():
        w, picks = target_weights(close, volume, rev, p, START, pit, industry, None, trust_ratio)
        weights[label] = w
        runs[label] = bt.run_vbt(close, w)
        runs[f"核心衛星｜{label}"] = bt.run_vbt(close, core_sat(w))

    # 步驟一：樣本內挑選
    is_sharpe = {k: bt.metrics(runs[k].loc[START:IS_END])["Sharpe"] for k in CANDIDATES}
    chosen = max(is_sharpe, key=is_sharpe.get)

    def table(a: str, b: str, keys: list[str]) -> str:
        return pd.DataFrame({k: fmt(bt.metrics(runs[k].loc[a:b])) for k in keys}).T.to_markdown()

    base = ["v0.3（現行）", *CANDIDATES]
    end = runs["v0.3（現行）"].index[-1]
    oos_main = bt.metrics(runs[chosen].loc[OOS_START:])
    oos_base = bt.metrics(runs["v0.3（現行）"].loc[OOS_START:])
    oos_cs = bt.metrics(runs[f"核心衛星｜{chosen}"].loc[OOS_START:])
    oos_cs_base = bt.metrics(runs["核心衛星｜v0.3（現行）"].loc[OOS_START:])
    passed = oos_main["Sharpe"] > oos_base["Sharpe"] and oos_main["年化報酬"] > oos_base["年化報酬"]

    # 每月選股和 v0.3 的差異
    reb = weights["v0.3（現行）"].dropna(how="all").index
    def held(w, d):
        row = w.loc[d]
        return set(row[row >= 0.0999].index)
    overlap = sum(len(held(weights[chosen], d) & held(weights["v0.3（現行）"], d)) for d in reb) / len(reb)

    lines = [
        "# 陽之眼 v0.6：投信買超加進月換股（樣本外驗證）",
        "",
        "- 其他規則全部與 v0.3 主方案相同：營收條件、同產業最多 3 檔、選不滿補選股池等權重、每月換股、成本每邊 0.2925%",
        "- 投信指標：近 20 日投信淨買超股數 ÷ 近 20 日成交股數，只用到換股日前一天",
        "- 候選版本（事先決定）：",
        "  - **A 投信加分**：通過營收條件的候選股，依「營收年增率排名」與「投信指標排名」的平均排序",
        "  - **B 投信過濾**：通過營收條件的候選股，還要投信指標 > 0 才能入選",
        f"- **樣本內**：{START[:4]}–2020，只用這段的 Sharpe 挑版本；**樣本外**：2021 – {end.date()}，用來判斷有沒有效",
        "- 注意：投信這個想法來自用全期資料做的波段研究，所以樣本外不是完全沒看過；當時看到投信訊號在 2021 後變弱，這次驗證對它不利",
        "",
        "## 步驟一：樣本內（2015–2020）", "",
        table(START, IS_END, base), "",
        f"樣本內 Sharpe：" + "、".join(f"{k} {v:.2f}" for k, v in is_sharpe.items()) + f" → **選中：{chosen}**", "",
        "## 步驟二：樣本外（2021–至今）", "",
        table(OOS_START, end, base), "",
        "核心衛星（50% 0050 ＋ 50% 策略）：", "",
        table(OOS_START, end, [f"核心衛星｜{k}" for k in base]), "",
        "## 結論", "",
        f"- 選中的版本：{chosen}",
        f"- 樣本外年化：{oos_main['年化報酬']:.1%}（v0.3 {oos_base['年化報酬']:.1%}）；Sharpe {oos_main['Sharpe']:.2f}（v0.3 {oos_base['Sharpe']:.2f}）",
        f"- 核心衛星樣本外 Sharpe：{oos_cs['Sharpe']:.2f}（現行 {oos_cs_base['Sharpe']:.2f}）",
        f"- 判定：**{'通過' if passed else '未通過'}**（年化報酬與 Sharpe 都要贏 v0.3 才算通過）",
        f"- 與 v0.3 平均每期相同持股：{overlap:.1f} 檔",
        "",
        "## 參考：全期（2015–至今）", "",
        table(START, end, base), "",
        "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。",
    ]
    (REPORTS / "v06_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
