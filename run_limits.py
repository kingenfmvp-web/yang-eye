"""成交可行性檢查：換股日收盤漲停買不到、跌停賣不掉。輸出 reports/limits_report.md。

事先決定（跑之前寫好、先 commit）：
- 漲跌停判定：當天漲跌幅（FinMind spread ÷ 參考價）≥ +9.5%／≤ −9.5%；2015-06-01 前漲跌幅限制是 7%，用 ±6.5%
- 只看「新買進」與「整檔賣出」：
  - 新買進（上期沒有、這期選到）那天收盤漲停 → 買不到
  - 整檔賣出（上期有、這期沒選到）那天收盤跌停 → 賣不掉，之後第一個不是跌停的交易日收盤賣出
  - 續抱股的加減碼、補空位用的 0050／等權重籃子不檢查（金額小、流動性好）
- 兩種處理買不到的情境：
  - S1 延後：之後第一個不是漲停的交易日收盤買進（最晚到下次換股前），這段期間資金閒置
  - S2 放棄：那一格現金閒置到下次換股（最保守）
- 套用在兩個組合：v0.3 單獨策略（補等權重）、模擬帳戶的核心衛星（50% 0050＋v0.3，空位補 0050）
- 判定：核心衛星在 S2 之下，全期年化與 Sharpe 都還贏 0050 → 原結論站得住；
  另外若 S1 讓單獨策略年化少超過 3 個百分點，模擬帳戶要改成「漲停不追、隔天再買」的規則
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from run_backtest import REPORTS, START, fmt
from run_robustness import core_sat
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import target_weights

LIMIT_CHANGE = pd.Timestamp("2015-06-01")


def limit_flags(ids: list[str], index: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """每檔每天是否收在漲停／跌停。"""
    up, down = {}, {}
    for sid in ids:
        p = data.prices(sid)
        p = p.set_index(pd.to_datetime(p["date"]))
        ref = p["close"] - p["spread"]
        chg = (p["spread"] / ref.where(ref > 0)).reindex(index)
        th = pd.Series(np.where(index < LIMIT_CHANGE, 0.065, 0.095), index=index)
        up[sid], down[sid] = chg >= th, chg <= -th
    return pd.DataFrame(up).fillna(False), pd.DataFrame(down).fillna(False)


def apply_limits(w: pd.DataFrame, picks: dict, up: pd.DataFrame, down: pd.DataFrame,
                 mode: str) -> tuple[pd.DataFrame, dict]:
    """把買不到／賣不掉的單改成延後（NaN＝當天不動那一欄）。mode：'S1' 延後、'S2' 放棄。"""
    w = w.copy()
    dates = sorted(picks)
    stats = {"新買進": 0, "漲停買不到": 0, "延後買到": 0, "整檔賣出": 0, "跌停賣不掉": 0}
    prev: set[str] = set()
    for k, d in enumerate(dates):
        nxt = dates[k + 1] if k + 1 < len(dates) else w.index[-1] + pd.Timedelta(days=1)
        window = w.index[(w.index > d) & (w.index < nxt)]
        cur = set(picks[d])
        for s in cur - prev:
            stats["新買進"] += 1
            if s in up.columns and up.at[d, s]:
                stats["漲停買不到"] += 1
                target = w.at[d, s]
                w.at[d, s] = np.nan
                if mode == "S1":
                    ok = [x for x in window if not up.at[x, s]]
                    if ok:
                        w.at[ok[0], s] = target
                        stats["延後買到"] += 1
        for s in prev - cur:
            stats["整檔賣出"] += 1
            if s in down.columns and down.at[d, s] and w.at[d, s] == 0:
                stats["跌停賣不掉"] += 1
                w.at[d, s] = np.nan
                later = [x for x in w.index[w.index > d] if not down.at[x, s]]
                if later and later[0] < nxt:
                    w.at[later[0], s] = 0.0
        prev = cur
    return w, stats


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    etf = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    close["0050"] = etf
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    industry = universe_pit.industries()
    up, down = limit_flags([c for c in close.columns if c != "0050"], close.index)

    configs = {"v0.3 單獨策略": (V03, False), "核心衛星（模擬帳戶）": (replace(V03, fill="0050"), True)}
    runs, stats = {}, {}
    for label, (p, cs) in configs.items():
        w, picks = target_weights(close, volume, rev, p, START, pit, industry)
        base = core_sat(w) if cs else w
        runs[f"{label}｜S0 照收盤成交"] = bt.run_simple(close, base)
        for mode, name in (("S1", "S1 漲停延後"), ("S2", "S2 漲停放棄")):
            wl, st = apply_limits(base, picks, up, down, mode)
            runs[f"{label}｜{name}"] = bt.run_simple(close, wl)
            stats[(label, mode)] = st
        runs[f"_check｜{label}"] = bt.run_vbt(close, base)
    start = runs["v0.3 單獨策略｜S0 照收盤成交"].index[0]
    e = etf.loc[start:].dropna()
    runs["0050（含息）"] = e / e.iloc[0] * 1_000_000
    end = runs["0050（含息）"].index[-1]

    shown = [k for k in runs if not k.startswith("_")]
    def table(a, b):
        return pd.DataFrame({k: fmt(bt.metrics(runs[k].loc[a:b])) for k in shown}).T.to_markdown()

    m = lambda k: bt.metrics(runs[k])
    cs2, e50 = m("核心衛星（模擬帳戶）｜S2 漲停放棄"), m("0050（含息）")
    holds = cs2["年化報酬"] > e50["年化報酬"] and cs2["Sharpe"] > e50["Sharpe"]
    drop = m("v0.3 單獨策略｜S0 照收盤成交")["年化報酬"] - m("v0.3 單獨策略｜S1 漲停延後")["年化報酬"]
    st = stats[("v0.3 單獨策略", "S1")]

    lines = [
        "# 成交可行性：漲停買不到、跌停賣不掉",
        "",
        f"- 期間：{start.date()} ~ {end.date()}；規則同 v0.3 主方案；成本每邊 {bt.FEE_PER_SIDE:.4%}",
        "- 漲跌停：當天漲跌幅 ≥ ±9.5%（2015-06-01 前 ±6.5%）；只檢查新買進與整檔賣出",
        "- S0＝原本的回測（換股日收盤一定成交）；S1＝漲停就延到第一個不漲停的日子買；S2＝漲停就放棄、現金閒置到下次換股",
        "",
        "## 發生頻率（v0.3 單獨策略）", "",
        f"- 新買進 {st['新買進']} 次，其中換股日收漲停 {st['漲停買不到']} 次（{st['漲停買不到'] / max(st['新買進'], 1):.1%}），"
        f"延後後買到 {st['延後買到']} 次",
        f"- 整檔賣出 {st['整檔賣出']} 次，其中換股日收跌停 {st['跌停賣不掉']} 次",
        "",
        "## 判定", "",
        f"- 核心衛星 S2（最保守）全期：年化 {cs2['年化報酬']:.1%}、Sharpe {cs2['Sharpe']:.2f}；"
        f"0050 年化 {e50['年化報酬']:.1%}、Sharpe {e50['Sharpe']:.2f} → **{'原結論站得住' if holds else '原結論站不住'}**",
        f"- 單獨策略 S1 比 S0 年化少 {drop:.2%} → "
        f"**{'模擬帳戶要改成漲停不追、隔天再買' if drop > 0.03 else '影響不到 3 個百分點，模擬帳戶規則不用改'}**",
        "",
        "## 全期", "", table(START, end), "",
        "## 2021–至今", "", table("2021-01-01", end), "",
        "## 其他", "",
        "- 交叉驗證（S0）：" + "、".join(
            f"{k} 簡易 {m(k + '｜S0 照收盤成交')['年化報酬']:.2%}／vectorbt {m('_check｜' + k)['年化報酬']:.2%}" for k in configs),
        "- 限制：被延後的單仍以收盤價成交、未計滑價；續抱股加減碼與補空位不檢查；跌停賣不掉時當天其他買單照原目標，可能短暫用到不存在的現金",
        "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。",
    ]
    (REPORTS / "limits_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
