"""陽之眼 v0.8：營收規模下限、個股站上 120 日均線。輸出 reports/v08_report.md。

事先決定（跑之前寫好、先 commit，2026-10-22）：
- 候選（都在 v0.3 主方案上加一條，其他規則不變）：
  - A 營收規模下限：近 3 月營收合計 ≥ 3 億元，且去年同期 ≥ 1.5 億元（排除基期太低的年增暴衝）
  - B 個股站上 120 日均線：換股日前一天收盤 > 120 日均線
  - C＝A＋B
  - 點子來源：ryukyucoding/quant-bot（A、B）、FinLab 公開範例（股價確認營收動能）
- 成交條件一律用實際做得到的版本：換股日收漲停的新買進延後到第一個不漲停的日子（S1），
  跌停賣不掉延後；另外每邊扣滑價 0.1%。v0.3 對照也用同樣條件
- 步驟一：只看樣本內（2015–2020）的 Sharpe，在 A／B／C 中選一個
- 步驟二：選中的版本在樣本外（2021–至今）年化報酬與 Sharpe 都贏 v0.3 → 通過
- 參考（不拿來判定）：核心衛星版與 0050 比較、選中版本套到上櫃的結果
- 多重比較：這是第 8 輪，累計測過的版本約 20 個，所以就算通過也可能是運氣，要看幅度與前後段是否一致
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_limits import apply_limits, limit_flags
from run_robustness import core_sat
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import target_weights

IS_END, OOS_START = "2020-12-31", "2021-01-01"
SLIP = 0.001
CANDIDATES = {
    "A 營收規模下限": replace(V03, min_rev3=3e8),
    "B 站上 120 日均線": replace(V03, above_ma=120),
    "C 兩者都加": replace(V03, min_rev3=3e8, above_ma=120),
}


def panel(universe_name: str):
    pit = universe_pit.load(universe_name)
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    close["0050"] = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    up, down = limit_flags([c for c in close.columns if c != "0050"], close.index)
    return close, volume, rev, pit, up, down


def realistic(close, w, picks, up, down) -> pd.Series:
    wl, _ = apply_limits(w, picks, up, down, "S1")
    return bt.run_simple(close, wl, pd.Series(SLIP, index=[c for c in close.columns if c != "0050"]))


def main() -> None:
    close, volume, rev, pit, up, down = panel("universe_pit")
    industry = universe_pit.industries()

    runs, n_picks = {}, {}
    for label, p in {"v0.3（現行）": V03, **CANDIDATES}.items():
        w, picks = target_weights(close, volume, rev, p, START, pit, industry)
        runs[label] = realistic(close, w, picks, up, down)
        pc = replace(p, fill="0050")
        wc, picks_c = target_weights(close, volume, rev, pc, START, pit, industry)
        runs[f"核心衛星｜{label}"] = realistic(close, core_sat(wc), picks_c, up, down)
        n_picks[label] = pd.Series({d: len(x) for d, x in picks.items()}).mean()
    start = runs["v0.3（現行）"].index[0]
    e = close["0050"].loc[start:].dropna()
    runs["0050（含息）"] = e / e.iloc[0] * 1_000_000
    end = runs["0050（含息）"].index[-1]

    is_sharpe = {k: bt.metrics(runs[k].loc[START:IS_END])["Sharpe"] for k in CANDIDATES}
    chosen = max(is_sharpe, key=is_sharpe.get)
    oos = lambda k: bt.metrics(runs[k].loc[OOS_START:])
    passed = oos(chosen)["年化報酬"] > oos("v0.3（現行）")["年化報酬"] and oos(chosen)["Sharpe"] > oos("v0.3（現行）")["Sharpe"]

    base = ["v0.3（現行）", *CANDIDATES]
    cs = [f"核心衛星｜{k}" for k in base] + ["0050（含息）"]
    def table(a, b, keys):
        return pd.DataFrame({k: fmt(bt.metrics(runs[k].loc[a:b])) for k in keys}).T.to_markdown()

    # 參考：選中的版本套到上櫃（同樣條件）
    tclose, tvol, trev, tpit, tup, tdown = panel("universe_pit_tpex")
    tpex = {}
    for label, p in (("v0.3（上櫃）", V03), (f"{chosen}（上櫃）", CANDIDATES[chosen])):
        w, picks = target_weights(tclose, tvol, trev, p, START, tpit, industry)
        tpex[label] = realistic(tclose, w, picks, tup, tdown)
    tpex_tbl = pd.DataFrame({k: fmt(bt.metrics(v)) for k, v in tpex.items()}).T.to_markdown()

    lines = [
        "# 陽之眼 v0.8：營收規模下限、個股站上 120 日均線",
        "",
        f"- 期間：{start.date()} ~ {end.date()}；其他規則同 v0.3 主方案",
        f"- 成交條件：漲停延後買、跌停延後賣，每邊成本 {bt.FEE_PER_SIDE:.4%}＋滑價 {SLIP:.1%}（v0.3 對照同條件）",
        "- 候選（事先決定）：A 近 3 月營收 ≥ 3 億且去年同期 ≥ 1.5 億；B 前一天收盤 > 120 日均線；C＝A＋B",
        "- 樣本內 2015–2020 只用來挑版本；樣本外 2021–至今判定。累計已測約 20 個版本，通過也要保守看待",
        "",
        "## 步驟一：樣本內（2015–2020）", "", table(START, IS_END, base), "",
        "樣本內 Sharpe：" + "、".join(f"{k} {v:.2f}" for k, v in is_sharpe.items()) + f" → **選中：{chosen}**", "",
        "## 步驟二：樣本外（2021–至今）", "", table(OOS_START, end, base), "",
        "## 判定", "",
        f"- {chosen} 樣本外：年化 {oos(chosen)['年化報酬']:.1%}（v0.3 {oos('v0.3（現行）')['年化報酬']:.1%}）、"
        f"Sharpe {oos(chosen)['Sharpe']:.2f}（v0.3 {oos('v0.3（現行）')['Sharpe']:.2f}）→ **{'通過' if passed else '未通過'}**",
        "- 平均每期選到幾檔：" + "、".join(f"{k} {v:.1f}" for k, v in n_picks.items()),
        "",
        "## 參考：核心衛星（50% 0050，空位補 0050）全期", "", table(START, end, cs), "",
        "## 參考：核心衛星 2021–至今", "", table(OOS_START, end, cs), "",
        "## 參考：套到上櫃（同條件，全期）", "", tpex_tbl, "",
        "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所、證券櫃檯買賣中心。",
    ]
    (REPORTS / "v08_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
