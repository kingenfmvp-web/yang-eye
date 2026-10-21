"""A1 參數穩健性＋投資效益評估。輸出 reports/robustness_report.md 與 robustness.png。

參數格點（現行 v0.3 在正中間）：營收門檻 15/20/25%、持股 8/10/12 檔、換股日 11/12/15 號。
投資效益：以現行核心衛星配置，統計任意起點持有 1 年、3 年的報酬分布，與 0050 比較。
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

from run_backtest import REPORTS, START, fmt
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import target_weights

GRID = {"min_yoy3": [0.15, 0.20, 0.25], "top_n": [8, 10, 12], "rebalance_day": [11, 12, 15]}
CURRENT = (0.20, 10, 11)


def core_sat(w: pd.DataFrame) -> pd.DataFrame:
    b = w * 0.5
    rows = w.notna().any(axis=1)
    b.loc[rows, "0050"] = b.loc[rows, "0050"].fillna(0) + 0.5
    return b


def rolling_stats(v: pd.Series, bench: pd.Series, years: int) -> dict:
    """任意交易日起持有 years 年的報酬（年化前）。"""
    n = 252 * years
    r = (v.shift(-n) / v - 1).dropna()
    b = (bench.reindex(v.index).ffill().shift(-n) / bench.reindex(v.index).ffill() - 1).reindex(r.index)
    return {"樣本數": len(r), "中位數": r.median(), "最差 5%": r.quantile(0.05), "最差": r.min(), "最好": r.max(),
            "虧錢的機率": (r < 0).mean(), "贏 0050 的機率": (r > b).mean()}


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    etf = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    close["0050"] = etf
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    industry = universe_pit.industries()

    rows, curves = [], {}
    for yoy, n, day in itertools.product(*GRID.values()):
        p = replace(V03, min_yoy3=yoy, top_n=n, rebalance_day=day)
        # 選股池是在每月 11 日起的換股日建立的；換股日不同時，沿用當月那一期
        uni = {d2: xs for d1, xs in pit.items()
               for d2 in [close.index[close.index.searchsorted(d1.replace(day=day))]]
               if d1.replace(day=day) <= close.index[-1]} if day != 11 else pit
        w, _ = target_weights(close, volume, rev, p, START, uni, industry)
        v = bt.run_vbt(close, w)
        cs = bt.run_vbt(close, core_sat(w))
        key = (yoy, n, day)
        curves[key] = (v, cs)
        for kind, s in (("單獨策略", v), ("核心衛星", cs)):
            for per, (a, b) in {"全期": (START, None), "2015–2020": (START, "2020-12-31"), "2021–": ("2021-01-01", None)}.items():
                m = bt.metrics(s.loc[a:b])
                rows.append({"營收門檻": yoy, "持股數": n, "換股日": day, "類型": kind, "期間": per, **m})
        print(f"{key} 完成", flush=True)
    res = pd.DataFrame(rows)

    # 對照：0050 與加權報酬指數
    start = curves[CURRENT][0].index[0]
    e = etf.loc[start:].dropna()
    etf_v = e / e.iloc[0] * 1_000_000
    bench = data.benchmark()
    bench_v = bench.loc[start:] / bench.loc[start:].iloc[0] * 1_000_000
    ref = {}
    for name, s in (("0050（含息）", etf_v), ("加權報酬指數（含息）", bench_v)):
        for per, (a, b) in {"全期": (START, None), "2015–2020": (START, "2020-12-31"), "2021–": ("2021-01-01", None)}.items():
            ref[(name, per)] = bt.metrics(s.loc[a:b])

    def summary(kind: str, per: str) -> dict:
        x = res[(res["類型"] == kind) & (res["期間"] == per)]
        e50 = ref[("0050（含息）", per)]
        cur = x[(x["營收門檻"] == CURRENT[0]) & (x["持股數"] == CURRENT[1]) & (x["換股日"] == CURRENT[2])].iloc[0]
        return {"現行設定 年化": f"{cur['年化報酬']:.1%}", "27 組 年化（最低～最高）": f"{x['年化報酬'].min():.1%} ～ {x['年化報酬'].max():.1%}",
                "27 組 年化中位數": f"{x['年化報酬'].median():.1%}",
                "現行設定 Sharpe": f"{cur['Sharpe']:.2f}", "27 組 Sharpe（最低～最高）": f"{x['Sharpe'].min():.2f} ～ {x['Sharpe'].max():.2f}",
                "年化贏 0050 的組數": f"{(x['年化報酬'] > e50['年化報酬']).sum()}/27",
                "Sharpe 贏 0050 的組數": f"{(x['Sharpe'] > e50['Sharpe']).sum()}/27",
                "現行設定 年化排名": f"{int((x['年化報酬'] > cur['年化報酬']).sum()) + 1}/27"}
    summ = pd.DataFrame({f"{k}｜{p}": summary(k, p) for k in ("單獨策略", "核心衛星") for p in ("全期", "2015–2020", "2021–")}).T
    ref_tbl = pd.DataFrame({f"{n}｜{p}": {"年化": f"{m['年化報酬']:.1%}", "Sharpe": f"{m['Sharpe']:.2f}", "最大回撤": f"{m['最大回撤']:.1%}"}
                            for (n, p), m in ref.items()}).T

    # 各參數單獨的影響（全期、單獨策略，其他兩個參數取平均）
    full = res[(res["類型"] == "單獨策略") & (res["期間"] == "全期")]
    effect = []
    for col in ("營收門檻", "持股數", "換股日"):
        g = full.groupby(col)[["年化報酬", "Sharpe", "最大回撤"]].mean()
        for val, r in g.iterrows():
            effect.append({"參數": col, "值": val, "平均年化": f"{r['年化報酬']:.1%}", "平均 Sharpe": f"{r['Sharpe']:.2f}",
                           "平均最大回撤": f"{r['最大回撤']:.1%}"})

    # 投資效益：現行核心衛星 vs 0050，任意起點持有 1 年／3 年
    cur_cs = curves[CURRENT][1]
    hold = []
    for yrs in (1, 3):
        for name, s in (("核心衛星（現行）", cur_cs), ("0050（含息）", etf_v)):
            st = rolling_stats(s, etf_v, yrs)
            hold.append({"持有": f"{yrs} 年", "組合": name, "樣本數": st["樣本數"],
                         "報酬中位數": f"{st['中位數']:+.0%}", "最差 5% 情況": f"{st['最差 5%']:+.0%}",
                         "歷史最差": f"{st['最差']:+.0%}", "歷史最好": f"{st['最好']:+.0%}",
                         "虧錢的機率": f"{st['虧錢的機率']:.0%}",
                         "贏 0050 的機率": "—" if name.startswith("0050") else f"{st['贏 0050 的機率']:.0%}"})
    money = {}
    for name, s in (("核心衛星（現行）", cur_cs), ("0050（含息）", etf_v)):
        for yrs in (1, 3):
            r = (s.shift(-252 * yrs) / s - 1).dropna()
            money[(name, yrs)] = (100 * (1 + r.quantile(0.05)), 100 * (1 + r.median()), 100 * (1 + r.quantile(0.95)))

    # 圖：27 組全期年化與 Sharpe（單獨策略與核心衛星），標出現行設定與 0050
    for f in ("Noto Sans CJK TC", "WenQuanYi Zen Hei"):
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10, 6), facecolor="#fcfcfb")
    for kind, color in (("單獨策略", "#2a78d6"), ("核心衛星", "#eb6834")):
        x = res[(res["類型"] == kind) & (res["期間"] == "全期")]
        ax.scatter(x["最大回撤"] * 100, x["年化報酬"] * 100, s=40, color=color, alpha=0.75, label=f"{kind}（27 組參數）")
        cur = x[(x["營收門檻"] == CURRENT[0]) & (x["持股數"] == CURRENT[1]) & (x["換股日"] == CURRENT[2])].iloc[0]
        ax.scatter(cur["最大回撤"] * 100, cur["年化報酬"] * 100, s=140, facecolors="none", edgecolors=color, linewidths=2)
        ax.annotate(f"現行 {kind}", (cur["最大回撤"] * 100, cur["年化報酬"] * 100), xytext=(8, 6),
                    textcoords="offset points", fontsize=9, color="#52514e")
    for name, color in (("0050（含息）", "#1baf7a"), ("加權報酬指數（含息）", "#a8a69e")):
        m = ref[(name, "全期")]
        ax.scatter(m["最大回撤"] * 100, m["年化報酬"] * 100, s=90, marker="D", color=color, label=name)
    ax.set_xlabel("最大回撤 %（越靠右越好）", color="#52514e")
    ax.set_ylabel("年化報酬 %", color="#52514e")
    ax.set_title("27 組參數的報酬與回撤（2015–2026，已扣成本）", loc="left", fontsize=13)
    ax.legend(frameon=False, loc="lower left")
    ax.set_facecolor("#fcfcfb")
    ax.grid(color="#e6e5e0", lw=0.8)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(REPORTS / "robustness.png", dpi=150)

    lines = [
        "# A1 參數穩健性與投資效益",
        "",
        f"- 期間：{START} ~ {close.index[-1].date()}；選股池、產業上限、補空位都與 v0.3 主方案相同；成本每邊 {bt.FEE_PER_SIDE:.4%}",
        "- 參數格點：營收門檻 15/20/25%、持股 8/10/12 檔、換股日 11/12/15 號，共 27 組；現行 = 20%、10 檔、11 號",
        "- 目的是看結果是否只在「剛好這組參數」才好；**不是**拿來挑最好的一組",
        "",
        "## 1. 27 組參數的結果分布", "", summ.to_markdown(), "",
        "對照：", "", ref_tbl.to_markdown(), "",
        "## 2. 各參數的平均影響（單獨策略、全期）", "", pd.DataFrame(effect).to_markdown(index=False), "",
        "## 3. 投資效益：現行核心衛星 vs 0050（任意一天起持有）", "",
        pd.DataFrame(hold).to_markdown(index=False), "",
        "投入 100 萬，持有後大約變成（萬元；最差 5%／中位數／最好 5%）：", "",
    ]
    for (name, yrs), (lo, md, hi) in money.items():
        lines.append(f"- {name}，持有 {yrs} 年：{lo:,.0f}／{md:,.0f}／{hi:,.0f}")
    lines += ["", "> 歷史回測不代表未來績效；研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "robustness_report.md").write_text("\n".join(lines), encoding="utf-8")
    res.to_csv(REPORTS / "robustness_grid.csv", index=False)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
