"""陽之眼 v0.3：風險控制（產業上限＋空位補滿）回測，與 v0.2 對照。輸出 reports/v03_report.md 與 v03_equity_curve.png。"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from run_backtest import REPORTS, START, data_quality, fmt
from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import RevenueMomentumParams, equal_weight_universe, target_weights

import matplotlib.pyplot as plt  # noqa: E402  (run_backtest 已設定 Agg 後端與字型)
from matplotlib import font_manager

BASE = RevenueMomentumParams()
VARIANTS = {
    "v0.2 原版": BASE,
    "v0.3 主方案（產業≤3檔＋補等權重）": replace(BASE, max_per_industry=3, fill="ew"),
    "敏感度A（產業≤2檔＋補等權重）": replace(BASE, max_per_industry=2, fill="ew"),
    "敏感度B（產業≤3檔＋補0050）": replace(BASE, max_per_industry=3, fill="0050"),
}
COLORS = {"v0.2 原版": "#2a78d6", "v0.3 主方案（產業≤3檔＋補等權重）": "#eb6834", "加權報酬指數": "#1baf7a"}


def max_industry_share(picks: dict, industry: dict) -> pd.Series:
    """每期持股中，最大單一產業占幾檔。"""
    out = {}
    for d, xs in picks.items():
        counts = pd.Series([industry.get(s, f"?{s}") for s in xs]).value_counts()
        out[d] = counts.iloc[0] if len(counts) else 0
    return pd.Series(out)


def plot(values: dict[str, pd.Series], path) -> None:
    for f in ("Noto Sans CJK TC", "WenQuanYi Zen Hei"):
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]}, facecolor="#fcfcfb")
    ends = []
    for name, v in values.items():
        nav = v / v.iloc[0]
        ax1.plot(nav.index, nav, color=COLORS[name], lw=2, label=name)
        ends.append((name, nav.index[-1], nav.iloc[-1]))
        dd = v / v.cummax() - 1
        ax2.plot(dd.index, dd * 100, color=COLORS[name], lw=1.2)
    last = None
    for name, x, y in sorted(ends, key=lambda e: e[2]):
        ty = y if last is None else max(y, last * 1.12)
        ax1.annotate(f"{y:.1f}x", (x, y), xytext=(x + pd.Timedelta(days=40), ty), textcoords="data",
                     va="center", fontsize=9, color="#52514e", annotation_clip=False)
        last = ty
    ax1.set_yscale("log")
    ax1.set_ylabel("淨值（起始=1，對數刻度）", color="#52514e")
    ax1.set_title("陽之眼 v0.3｜產業上限＋空位補滿 vs v0.2（時點正確選股池，已扣成本）", loc="left", fontsize=13)
    ax1.legend(loc="upper left", frameon=False)
    ax2.set_ylabel("回撤 %", color="#52514e")
    for ax in (ax1, ax2):
        ax.set_facecolor("#fcfcfb")
        ax.grid(color="#e6e5e0", lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors="#52514e")
    fig.tight_layout()
    fig.subplots_adjust(right=0.9)
    fig.savefig(path, dpi=150)


def main() -> None:
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    close, volume, rev = data.load_panel(members)
    etf = data.adjust_close(data.prices("0050"), data.dividends("0050"))
    close["0050"] = etf.reindex(close.index)
    volume["0050"] = 0.0
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    industry = universe_pit.industries()
    names = universe_pit.names()

    values, picks_all, weights_all = {}, {}, {}
    for label, p in VARIANTS.items():
        w, picks = target_weights(close, volume, rev, p, START, pit, industry)
        values[label] = bt.run_vbt(close, w)
        picks_all[label], weights_all[label] = picks, w
    ew = equal_weight_universe(close, volume, weights_all["v0.2 原版"], BASE.min_avg_volume_lots, pit)
    values["選股池等權重"] = bt.run_vbt(close, ew)
    bench = data.benchmark()
    bench = bench[bench.index >= values["v0.2 原版"].index[0]]
    values["加權報酬指數"] = bench / bench.iloc[0] * 1_000_000

    main_label = "v0.3 主方案（產業≤3檔＋補等權重）"
    check = bt.run_simple(close, weights_all[main_label])
    end = values["v0.2 原版"].index[-1]
    periods = {"全期": (START, end), "2015–2020": (START, "2020-12-31"), "2021–至今": ("2021-01-01", end)}
    tables = {label: pd.DataFrame({k: fmt(bt.metrics(v.loc[a:b])) for k, v in values.items()}).T
              for label, (a, b) in periods.items()}
    yearly = bt.yearly_returns({k: values[k] for k in ("v0.2 原版", main_label, "選股池等權重", "加權報酬指數")})
    yearly.index = yearly.index.year

    def dd_window(v: pd.Series, a: str, b: str) -> str:
        x = v.loc[a:b]
        return f"{(x / x.cummax() - 1).min():.1%}"
    shipping = {k: dd_window(v, "2021-07-01", "2022-12-31") for k, v in values.items()}

    stats = []
    for label in VARIANTS:
        n = pd.Series({d: len(x) for d, x in picks_all[label].items()})
        mi = max_industry_share(picks_all[label], industry)
        stats.append({"方案": label, "平均選股數": f"{n.mean():.1f}", "選不滿 10 檔的月份": f"{(n < 10).sum()}/{len(n)}",
                      "最大單一產業平均檔數": f"{mi.mean():.1f}", "單一產業 ≥4 檔的月份": int((mi >= 4).sum())})

    latest_d = max(picks_all[main_label])
    latest = picks_all[main_label][latest_d]
    pd.DataFrame([{"rebalance_date": d.date(), "stock_id": s, "name": names.get(s, ""), "industry": industry.get(s, "")}
                  for d, xs in picks_all[main_label].items() for s in xs]).to_csv(REPORTS / "v03_picks_history.csv", index=False)
    plot({k: values[k] for k in COLORS}, REPORTS / "v03_equity_curve.png")

    lines = [
        "# 陽之眼 v0.3 回測報告：產業上限＋空位補滿",
        "",
        f"- 期間：{values['v0.2 原版'].index[0].date()} ~ {end.date()}；選股池與 v0.2 相同（時點正確，含下市股）",
        "- 選股規則與 v0.2 相同；v0.3 只加兩條風險控制：",
        "  1. **產業上限**：依 3 月營收 YoY 由高到低挑，同一產業最多 3 檔（30%）",
        "  2. **空位補滿**：選不滿 10 檔時，空出的權重平均買進選股池其他股票（等權重），不再留現金",
        "- 主方案在跑回測前就決定；敏感度 A、B 只用來看結論穩不穩，不拿來挑最好看的",
        "- 產業別用 FinMind 目前的分類（取細類，如半導體業，而非電子工業），歷史期間沿用今天的分類",
        f"- 成本：每邊 {bt.FEE_PER_SIDE:.4%}；未計滑價",
        "",
    ]
    for label, t in tables.items():
        lines += [f"## 績效：{label}", "", t.to_markdown(), ""]
    lines += ["## 2021–2022 航運泡沫期間的最大回撤", "",
              pd.Series(shipping, name="2021-07～2022-12 最大回撤").to_frame().to_markdown(), "",
              "## 持股集中度", "", pd.DataFrame(stats).to_markdown(index=False), "",
              "## 逐年報酬", "", yearly.map(lambda x: f"{x:.1%}").to_markdown(), "",
              "## 其他", "",
              f"- 交叉驗證（主方案）：vectorbt 年化 {bt.metrics(values[main_label])['年化報酬']:.2%}，"
              f"簡易引擎 {bt.metrics(check)['年化報酬']:.2%}",
              f"- 最新一期主方案選股（{latest_d.date()}）：" + "、".join(f"{s} {names.get(s, '')}（{industry.get(s, '?')}）" for s in latest),
              "", "> 研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "v03_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
