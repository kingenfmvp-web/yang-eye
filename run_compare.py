"""陽之眼各版本收益總比較：同一期間、同一成本假設。輸出 reports/version_comparison.md 與 version_comparison.png。"""
from __future__ import annotations

from dataclasses import replace

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from run_backtest import REPORTS, START, fmt
from run_v04 import V03
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import RevenueMomentumParams, equal_weight_universe, target_weights

V01 = RevenueMomentumParams()
VERSIONS = {
    "v0.2 營收動能（時點正確選股池）": (V01, "pit"),
    "v0.3 ＋產業上限＋補空位": (V03, "pit"),
    "v0.4 ＋大盤濾網": (replace(V03, regime_ma=200, regime_exposure=0.5), "pit"),
    "v0.5 ＋移動停損 20%": (replace(V03, trailing_stop=0.20), "pit"),
}
BLEND = "核心衛星：50% 0050 ＋ 50% v0.3"
BIASED = "v0.1 營收動能（今日市值前140，有偏差）"


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    old = data.universe(140)
    close, volume, rev = data.load_panel(sorted(set(members) | set(old["stock_id"])))
    close["0050"] = data.adjust_close(data.prices("0050"), data.dividends("0050")).reindex(close.index)
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    old_uni = {d: [s for s in old["stock_id"] if s in close.columns] for d in pit}
    industry = universe_pit.industries()
    market = data.benchmark()

    values, weights = {}, {}
    w, _ = target_weights(close, volume, rev, V01, START, old_uni)
    values[BIASED] = bt.run_vbt(close, w)
    for label, (p, _) in VERSIONS.items():
        w, _ = target_weights(close, volume, rev, p, START, pit, industry, market)
        weights[label] = w
        values[label] = bt.run_vbt(close, w)
    # 核心衛星：每月換股日把一半放 0050、一半照 v0.3 權重
    w3 = weights["v0.3 ＋產業上限＋補空位"]
    blend = w3 * 0.5
    blend.loc[w3.notna().any(axis=1), "0050"] = blend.loc[w3.notna().any(axis=1), "0050"].fillna(0) + 0.5
    values[BLEND] = bt.run_vbt(close, blend)
    values["0050（含息，扣成本）"] = bt.run_vbt(close, blend.where(blend.isna(), 0).assign(
        **{"0050": blend["0050"].where(blend["0050"].isna(), 1.0)}))
    ew = equal_weight_universe(close, volume, w3, V01.min_avg_volume_lots, pit)
    values["選股池等權重"] = bt.run_vbt(close, ew)
    bench = market[market.index >= values[BLEND].index[0]]
    values["加權報酬指數（含息）"] = bench / bench.iloc[0] * 1_000_000

    rows = []
    for k, v in values.items():
        m = bt.metrics(v)
        rows.append({"版本": k, "100萬變成": f"{v.iloc[-1] / v.iloc[0] * 100:,.0f} 萬", **fmt(m)})
    table = pd.DataFrame(rows).set_index("版本")
    yearly = bt.yearly_returns(values)
    yearly.index = yearly.index.year
    sharpe = pd.Series({k: bt.metrics(v)["Sharpe"] for k, v in values.items()})
    best = {y: yearly.loc[y].drop(BIASED).idxmax() for y in yearly.index}

    # 圖：100 萬變多少（橫條），依 Sharpe 標註
    for f in ("Noto Sans CJK TC", "WenQuanYi Zen Hei"):
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    order = [k for k in values if k != BIASED]
    finals = pd.Series({k: values[k].iloc[-1] / values[k].iloc[0] * 100 for k in order}).sort_values()
    colors = {k: "#2a78d6" for k in order}
    colors[BLEND] = "#eb6834"
    for k in ("0050（含息，扣成本）", "選股池等權重", "加權報酬指數（含息）"):
        colors[k] = "#a8a69e"
    fig, ax = plt.subplots(figsize=(11, 5.2), facecolor="#fcfcfb")
    bars = ax.barh(finals.index, finals.values, color=[colors[k] for k in finals.index], height=0.6)
    for b, k in zip(bars, finals.index):
        ax.text(b.get_width() + 20, b.get_y() + b.get_height() / 2,
                f"{b.get_width():,.0f} 萬　Sharpe {sharpe[k]:.2f}　最大回撤 {bt.metrics(values[k])['最大回撤']:.0%}",
                va="center", fontsize=9, color="#52514e")
    ax.set_xlim(0, finals.max() * 1.55)
    ax.set_title(f"2015 年投入 100 萬，到 {values[BLEND].index[-1]:%Y-%m-%d} 變成多少（已扣手續費與證交稅）", loc="left", fontsize=13)
    ax.set_facecolor("#fcfcfb")
    ax.grid(axis="x", color="#e6e5e0", lw=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors="#52514e")
    fig.tight_layout()
    fig.savefig(REPORTS / "version_comparison.png", dpi=150)

    lines = [
        "# 陽之眼各版本收益比較",
        "",
        f"- 期間：{values[BLEND].index[0].date()} ~ {values[BLEND].index[-1].date()}，每月第一個 ≥ 11 日的交易日收盤換股",
        f"- 成本：每邊 {bt.FEE_PER_SIDE:.4%}（手續費 0.1425% ×2 ＋ 證交稅 0.3%）；未計滑價；股利再投入",
        "- v0.2 起都用時點正確選股池（每期成交金額前 140 名，含後來下市的股票）",
        f"- **{BIASED}** 用今天的市值選股池，等於事先知道誰會成功，數字偏樂觀，只留作對照",
        f"- **{BLEND}**：每次換股時把資金調回一半 0050、一半 v0.3；這是看過 v0.4、v0.5 結果後才提出的，屬事後方案",
        "",
        "## 總表", "", table.to_markdown(), "",
        "## 逐年報酬", "", yearly.map(lambda x: f"{x:.1%}").to_markdown(), "",
        "## 每年表現最好的（不含 v0.1）", "",
        "、".join(f"{y}：{k}" for y, k in best.items()), "",
        "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。",
    ]
    (REPORTS / "version_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
