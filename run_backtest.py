"""陽之眼 v0.1：營收動能策略回測，輸出 reports/ 底下的報告、圖表與選股清單。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from yang_eye import backtest as bt
from yang_eye import data, universe_pit
from yang_eye.strategy import RevenueMomentumParams, equal_weight_universe, target_weights

REPORTS = Path(__file__).resolve().parent / "reports"
START = "2015-01-01"
# 參考色盤 slot 1~3（三條線，全組對比皆通過）
COLORS = {"營收動能": "#2a78d6", "加權報酬指數": "#eb6834", "選股池等權重": "#1baf7a"}


def data_quality(close: pd.DataFrame) -> pd.DataFrame:
    """台股漲跌幅限制 10%，還原後單日超過 ±11% 多半是減資、分割等沒還原到的事件。"""
    r = close.pct_change()
    hits = r[(r.abs() > 0.11)].stack().dropna()
    return hits.rename("ret").reset_index().rename(columns={"level_0": "date", "level_1": "stock_id"})


def plot(values: dict[str, pd.Series], path: Path) -> None:
    for f in ("Noto Sans CJK TC", "Noto Sans CJK JP", "WenQuanYi Zen Hei", "Droid Sans Fallback"):
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]}, facecolor="#fcfcfb")
    label_y = {}
    for name, v in values.items():
        nav = v / v.iloc[0]
        ax1.plot(nav.index, nav, color=COLORS[name], lw=2, label=name)
        label_y[name] = (nav.index[-1], nav.iloc[-1])
    last = None  # 對數刻度下讓相鄰標籤至少差 12%，避免重疊
    for name, (x, y) in sorted(label_y.items(), key=lambda kv: kv[1][1]):
        ty = y if last is None else max(y, last * 1.12)
        ax1.annotate(f"{name} {y:.1f}x", (x, y), xytext=(x, ty), textcoords="data",
                     va="center", fontsize=9, color="#52514e",
                     annotation_clip=False).set_x(x + pd.Timedelta(days=40))
        last = ty
    for name, v in values.items():
        dd = v / v.cummax() - 1
        ax2.plot(dd.index, dd * 100, color=COLORS[name], lw=1.2)
    ax1.set_yscale("log")
    ax1.set_ylabel("淨值（起始=1，對數刻度）", color="#52514e")
    ax1.set_title("陽之眼 v0.2｜營收動能 vs 大盤（時點正確選股池）（已扣手續費與證交稅）", loc="left", fontsize=13)
    ax1.legend(loc="upper left", frameon=False)
    ax2.set_ylabel("回撤 %", color="#52514e")
    for ax in (ax1, ax2):
        ax.set_facecolor("#fcfcfb")
        ax.grid(color="#e6e5e0", lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors="#52514e")
    fig.tight_layout()
    fig.subplots_adjust(right=0.86)
    fig.savefig(path, dpi=150)


def fmt(m: dict) -> dict:
    return {k: (f"{v:.2f}" if k == "Sharpe" else f"{v:.1%}") for k, v in m.items()}


def scenario(close, volume, rev, universe=None) -> tuple[dict[str, pd.Series], dict, pd.Series]:
    p = RevenueMomentumParams()
    w, picks = target_weights(close, volume, rev, p, START, universe)
    ew = equal_weight_universe(close, volume, w, p.min_avg_volume_lots, universe)
    values = {"營收動能": bt.run_vbt(close, w), "選股池等權重": bt.run_vbt(close, ew)}
    return values, picks, bt.run_simple(close, w)


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    pit = universe_pit.load()
    members = sorted({s for xs in pit.values() for s in xs})
    old = data.universe(140)
    ids = sorted(set(members) | set(old["stock_id"]))
    close, volume, rev = data.load_panel(ids)
    names = universe_pit.names()
    missing = sorted(set(members) - set(close.columns))
    print(f"載入 {close.shape[1]} 檔；時點正確選股池成員 {len(members)} 檔，缺資料 {len(missing)} 檔")

    # 缺資料的成員從各期選股池移除，並記錄每期覆蓋率
    coverage = pd.Series({d: sum(s in close.columns for s in xs) / len(xs) for d, xs in pit.items()})
    pit = {d: [s for s in xs if s in close.columns] for d, xs in pit.items()}
    old_set = set(old["stock_id"])
    old_uni = {d: [s for s in close.columns if s in old_set] for d in pit}

    v_old, _, _ = scenario(close, volume, rev, old_uni)
    v_pit, picks, check = scenario(close, volume, rev, pit)
    bench = data.benchmark()
    bench = bench[bench.index >= v_pit["營收動能"].index[0]]
    v_pit["加權報酬指數"] = bench / bench.iloc[0] * 1_000_000

    end = v_pit["營收動能"].index[-1]
    periods = {"全期": (START, end), "2015–2020": (START, "2020-12-31"), "2021–至今": ("2021-01-01", end)}
    tables = {label: pd.DataFrame({k: fmt(bt.metrics(v.loc[a:b])) for k, v in v_pit.items()}).T
              for label, (a, b) in periods.items()}
    compare = pd.DataFrame({
        f"v0.1 今日市值前140（有偏差）｜{k}": fmt(bt.metrics(v)) for k, v in v_old.items()} | {
        f"v0.2 時點正確｜{k}": fmt(bt.metrics(v)) for k, v in v_pit.items() if k != "加權報酬指數"}).T

    yearly = bt.yearly_returns(v_pit)
    yearly.index = yearly.index.year
    n_hold = pd.Series({d: len(x) for d, x in picks.items()})
    dq = data_quality(close.loc[START:])
    turnover_names = pd.Series({d: len(set(xs) - old_set) for d, xs in pit.items()})

    latest_d = max(picks)
    latest = [(s, names.get(s, "")) for s in picks[latest_d]]
    pd.DataFrame([{"rebalance_date": d.date(), "stock_id": s, "name": names.get(s, "")}
                  for d, xs in picks.items() for s in xs]).to_csv(REPORTS / "picks_history.csv", index=False)
    plot(v_pit, REPORTS / "equity_curve.png")

    lines = [
        "# 陽之眼 v0.2 回測報告：營收動能（時點正確選股池）",
        "",
        f"- 期間：{v_pit['營收動能'].index[0].date()} ~ {end.date()}",
        "- 選股池：每個換股日前 20 個交易日的平均成交金額，上市普通股前 140 名，且已有 120 個交易日以上的成交紀錄（只用當時已知資料，含後來下市的股票）",
        f"- 選股池歷年成員共 {len(members)} 檔；FinMind 有資料 {len(members) - len(missing)} 檔，平均每期覆蓋率 {coverage.mean():.1%}（最低 {coverage.min():.1%}）",
        f"- 每期平均有 {turnover_names.mean():.0f} 檔不在 v0.1 的「今日市值前 140」名單裡 → 這就是 v0.1 漏掉的存活者偏差",
        "- 規則：近 3 月營收 YoY > 20%、當月營收創 12 個月新高、YoY 加速、20 日均量 > 1000 張；取 YoY 前 10 檔，每檔 10%，選不滿留現金",
        "- 換股：每月第一個 ≥ 11 日的交易日收盤（營收公告期限為 10 日）",
        f"- 成本：每邊 {bt.FEE_PER_SIDE:.4%}（手續費 0.1425% ×2 ＋ 證交稅 0.3%，攤成兩邊）；未計滑價",
        "- 價格：FinMind 原始收盤價 ＋ 除權息結果自行向後還原",
        "- 參數：與 v0.1 完全相同，沒有做任何最佳化",
        "",
        "## v0.1 vs v0.2：存活者偏差有多大", "", compare.to_markdown(), "",
    ]
    for label, t in tables.items():
        lines += [f"## 績效：{label}", "", t.to_markdown(), ""]
    lines += ["## 逐年報酬", "", yearly.map(lambda x: f"{x:.1%}").to_markdown(), "",
              "## 其他統計", "",
              f"- 平均持股數：{n_hold.mean():.1f} 檔（最少 {n_hold.min()}、最多 {n_hold.max()}）",
              f"- 持股 < 5 檔的月份：{(n_hold < 5).sum()} / {len(n_hold)}",
              f"- 交叉驗證：vectorbt 年化 {bt.metrics(v_pit['營收動能'])['年化報酬']:.2%}，"
              f"簡易引擎 {bt.metrics(check)['年化報酬']:.2%}",
              f"- 資料品質：單日漲跌超過 ±11% 的筆數 {len(dq)}（可能是沒還原到的減資或分割）",
              f"- 缺資料的成員（FinMind 查無）：{', '.join(f'{s} {names.get(s, chr(32))}' for s in missing) or '無'}",
              "",
              f"## 最新一期選股（{latest_d.date()}，依 {(latest_d.to_period('M') - 1)} 營收）", ""]
    lines += [f"- {s} {n}" for s, n in latest] or ["- （本期無符合條件的股票，空手）"]
    if len(dq):
        lines += ["", "## 資料品質明細（前 20 筆）", "",
                  dq.sort_values("ret", key=abs, ascending=False).head(20).to_markdown(index=False)]
    lines += ["", "> 本報告為研究用途，不構成投資建議。資料來源：FinMind、臺灣證券交易所。"]
    (REPORTS / "backtest_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
