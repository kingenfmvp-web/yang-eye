"""陽之眼 v0.7：上市＋上櫃合併選股池。輸出 reports/v07_report.md。

事先決定（跑之前寫好，不依結果調整）：
- 選股池：每個換股日＝上市前 140 名 ∪ 上櫃前 140 名（各自依前 20 日平均成交金額，時點正確、含下市櫃股）
- 其他規則與 v0.3 主方案完全相同（營收條件、產業≤3檔、選不滿補選股池等權重、每月 11 日起第一個交易日換股、10 檔）
- 滑價情境：上市股每邊多扣 0.1%、上櫃股每邊多扣 0.3%，兩個版本都套用
- 通過條件：2021–至今，合併版的年化報酬與 Sharpe 都贏 v0.3（上市），而且在滑價情境下也一樣贏
- 注意：上櫃的 A2 結果已經看過，所以這不是乾淨的樣本外；通過條件刻意設在後段＋含滑價，盡量保守
"""
from __future__ import annotations

import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_robustness import core_sat, rolling_stats
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import target_weights

OOS_START = "2021-01-01"
SLIP_TWSE, SLIP_TPEX = 0.001, 0.003


def main() -> None:
    twse, tpex = universe_pit.load(), universe_pit.load("universe_pit_tpex")
    union = {d: sorted(set(twse.get(d, [])) | set(tpex.get(d, []))) for d in sorted(set(twse) | set(tpex))}
    tpex_ids = {s for xs in tpex.values() for s in xs}
    members = sorted({s for xs in union.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    etf = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    close["0050"] = etf
    volume["0050"] = 0.0
    twse = {d: [s for s in xs if s in close.columns] for d, xs in twse.items()}
    union = {d: [s for s in xs if s in close.columns] for d, xs in union.items()}
    industry = universe_pit.industries()
    slip = pd.Series({s: SLIP_TPEX if s in tpex_ids else SLIP_TWSE for s in close.columns if s != "0050"})

    runs, picks = {}, {}
    for label, uni in (("v0.3（上市）", twse), ("v0.7（上市＋上櫃）", union)):
        w, picks[label] = target_weights(close, volume, rev, V03, START, uni, industry)
        runs[label] = bt.run_vbt(close, w)
        runs[f"{label}｜含滑價"] = bt.run_simple(close, w, slip)
        runs[f"核心衛星｜{label}"] = bt.run_vbt(close, core_sat(w))
        runs[f"核心衛星｜{label}｜含滑價"] = bt.run_simple(close, core_sat(w), slip)
        runs[f"_check｜{label}"] = bt.run_simple(close, w)
    start = runs["v0.3（上市）"].index[0]
    e = etf.loc[start:].dropna()
    runs["0050（含息）"] = e / e.iloc[0] * 1_000_000
    end = runs["v0.3（上市）"].index[-1]

    shown = [k for k in runs if not k.startswith("_")]
    def table(a, b, keys=shown):
        return pd.DataFrame({k: fmt(bt.metrics(runs[k].loc[a:b])) for k in keys}).T.to_markdown()

    m = lambda k: bt.metrics(runs[k].loc[OOS_START:])
    checks = {"不含滑價": ("v0.3（上市）", "v0.7（上市＋上櫃）"), "含滑價": ("v0.3（上市）｜含滑價", "v0.7（上市＋上櫃）｜含滑價")}
    verdict = {}
    for name, (a, b) in checks.items():
        ma, mb = m(a), m(b)
        verdict[name] = (mb["年化報酬"] > ma["年化報酬"] and mb["Sharpe"] > ma["Sharpe"], ma, mb)
    passed = all(v[0] for v in verdict.values())

    # 選股組成：合併版每期有幾檔上櫃股、選滿 10 檔的比例
    pv = picks["v0.7（上市＋上櫃）"]
    n_tpex = pd.Series({d: sum(s in tpex_ids for s in xs) for d, xs in pv.items()})
    full = {k: pd.Series({d: len(xs) for d, xs in p.items()}) for k, p in picks.items()}

    # 投資效益：含滑價的核心衛星，任意起點持有 3 年
    hold = []
    for k in ("核心衛星｜v0.3（上市）｜含滑價", "核心衛星｜v0.7（上市＋上櫃）｜含滑價"):
        for yrs in (1, 3):
            st = rolling_stats(runs[k], runs["0050（含息）"], yrs)
            hold.append({"組合": k, "持有": f"{yrs} 年", "100 萬變成（中位數，萬）": f"{100 * (1 + st['中位數']):,.0f}",
                         "最差 5%（萬）": f"{100 * (1 + st['最差 5%']):,.0f}", "虧錢機率": f"{st['虧錢的機率']:.0%}",
                         "贏 0050 機率": f"{st['贏 0050 的機率']:.0%}"})

    yearly = bt.yearly_returns({k: runs[k] for k in ("v0.3（上市）｜含滑價", "v0.7（上市＋上櫃）｜含滑價", "0050（含息）")})
    yearly.index = yearly.index.year
    names = universe_pit.names()
    latest = max(pv)
    lines = [
        "# 陽之眼 v0.7：上市＋上櫃合併選股池",
        "",
        f"- 期間：{start.date()} ~ {end.date()}；規則與 v0.3 主方案相同，只把選股池換成「上市前 140 ∪ 上櫃前 140」",
        f"- 成本：每邊 {bt.FEE_PER_SIDE:.4%}；「含滑價」另外每邊多扣上市 {SLIP_TWSE:.1%}、上櫃 {SLIP_TPEX:.1%}（簡易引擎）",
        f"- 事先決定的通過條件：{OOS_START[:4]}–至今，合併版年化與 Sharpe 都贏 v0.3，含滑價也要贏",
        "- 上櫃的單獨結果（A2）已經看過，這不是乾淨的樣本外，所以條件刻意定得保守",
        "",
        "## 判定", "",
    ]
    for name, (ok, ma, mb) in verdict.items():
        lines.append(f"- {name}（2021–至今）：年化 {mb['年化報酬']:.1%} vs v0.3 {ma['年化報酬']:.1%}；"
                     f"Sharpe {mb['Sharpe']:.2f} vs {ma['Sharpe']:.2f} → {'贏' if ok else '沒贏'}")
    lines += [f"- **{'通過' if passed else '未通過'}**", "",
              "## 2021–至今", "", table(OOS_START, end), "",
              "## 2015–2020", "", table(START, "2020-12-31"), "",
              "## 全期", "", table(START, end), "",
              "## 逐年報酬（含滑價）", "", yearly.map(lambda x: f"{x:.1%}").to_markdown(), "",
              "## 投資效益：核心衛星（含滑價），任意一天起持有", "", pd.DataFrame(hold).to_markdown(index=False), "",
              "## 其他", "",
              f"- 合併版每期平均 {n_tpex.mean():.1f} 檔上櫃股；選滿 10 檔的期數比例：" + "、".join(
                  f"{k} {(v == 10).mean():.0%}（平均 {v.mean():.1f} 檔）" for k, v in full.items()),
              "- 交叉驗證（不含滑價）：" + "、".join(
                  f"{k} vectorbt {bt.metrics(runs[k])['年化報酬']:.2%}／簡易 {bt.metrics(runs['_check｜' + k])['年化報酬']:.2%}"
                  for k in picks),
              f"- 合併版最新一期（{latest.date()}）：" + "、".join(
                  f"{x} {names.get(x, '')}{'（櫃）' if x in tpex_ids else ''}" for x in pv[latest]),
              "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所、證券櫃檯買賣中心。"]
    (REPORTS / "v07_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
