"""建立 v0.7 對照（上市＋上櫃）的帳本 shadow.json：只做一次。

從模擬帳戶最後一個資料日（收盤）起跑，起始資金＝模擬帳戶當天淨值，兩條線從同一點出發。
上櫃成交金額快照：那天之前用本地 FinMind 股價快取補（只留完整的交易日），當天用櫃買中心 OpenAPI。
用法：.venv/bin/python -m scripts.init_shadow ledger/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from yang_eye import data, paper, universe_pit


def seed_tpex(before: str, ids: list[str]) -> list[dict]:
    rows = []
    for sid in ids:
        path = data.CACHE / f"price/{sid}.parquet"
        if not path.exists():
            continue
        p = pd.read_parquet(path)
        p = p[(p["date"] < before) & (p["close"] > 0)].tail(paper.SNAPSHOT_DAYS)
        rows += [{"date": d, "stock_id": sid, "value": float(v), "volume": float(q)}
                 for d, v, q in zip(p["date"], p["Trading_money"], p["Trading_Volume"])]
    count = pd.Series([r["date"] for r in rows]).value_counts()
    full = sorted(count[count >= 0.9 * count.max()].index)[-20:]  # 快取沒抓到最後一天的股票不少，那種日期不用
    return [r for r in rows if r["date"] in full]


def main(folder: Path) -> None:
    ledger = paper.load(folder)
    if ledger.get("shadow"):
        raise SystemExit("shadow.json 已經存在")
    acct = ledger["account"][0]
    today = acct["last_update"]
    tw, tp = paper.market_snapshot(), paper.tpex_snapshot()
    if tw["date"].iloc[0] != today or tp["date"].iloc[0] != today:
        raise SystemExit(f"OpenAPI 是上市 {tw['date'].iloc[0]}／上櫃 {tp['date'].iloc[0]}，帳本是 {today}，對不上")
    tpex_ids = universe_pit.candidates(market="tpex")
    snaps = seed_tpex(today, tpex_ids)
    sh = {"inception": today, "initial_capital": acct["nav"], "cash": acct["nav"], "holdings": [], "trades": [],
          "last_rebalance": None, "last_update": today, "strategy": paper.SHADOW,
          "tpex_snapshots": paper.keep_snapshots(snaps, tp, today)}
    prices = {k: v for k, v in zip(pd.concat([tw, tp])["stock_id"], pd.concat([tw, tp])["close"])
              if pd.notna(v) and v > 0}
    names = dict(zip(pd.concat([tw, tp])["stock_id"], pd.concat([tw, tp])["name"]))
    members, lots = paper.shadow_members(ledger["value_snapshots"], sh["tpex_snapshots"], today)
    paper.shadow_rebalance(sh, members, lots, prices, names, today)
    row = paper.shadow_value(sh, prices, today)
    ledger["shadow"] = [sh]  # 和 account 一樣是一列的表，儀表板才能當資料來源讀
    ledger["nav"].append(row)
    paper.save(folder, ledger)
    print(f"{paper.SHADOW} 建立：{today} 收盤，淨值 {row['nav']:,}，持股 {len(sh['holdings'])} 檔，"
          f"上櫃快照 {len({r['date'] for r in sh['tpex_snapshots']})} 天，AI 主題占 {row['ai_weight']:.0%}")
    for h in sorted(sh["holdings"], key=lambda h: -h["market_value"]):
        print(f"  {h['stock_id']} {h['name']} {h['weight']:.1%} {h.get('theme', '')}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
