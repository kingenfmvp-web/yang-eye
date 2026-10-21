"""盤前參考：前一晚美股（費半、那斯達克、台積電 ADR）與預估 0050 開盤跳空。

    python -m yang_eye.premarket <輸出 premarket.json>
台北時間每個交易日早上執行（美股收盤是台北凌晨 4–5 點）。美股資料還沒更新或 FinMind 額度用完時結束碼 3。
預估跳空＝近 3 年「0050 開盤跳空 ~ 前一晚費半報酬」的線性迴歸；只是參考，開盤後的走勢與美股無關（見 reports/us_overnight_report.md）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from yang_eye import data

TZ = timezone(timedelta(hours=8))
INDICES = {"^SOX": "費半", "^IXIC": "那斯達克", "TSM": "台積電 ADR"}
FIT_YEARS = 3


def us_history(sid: str, start: str) -> pd.Series:
    df = data._finmind("USStockPrice", sid, start)
    return df.assign(date=pd.to_datetime(df["date"])).set_index("date")["Adj_Close"].sort_index()


def expected_us_date(now: datetime) -> pd.Timestamp:
    """台北今天早上應該看得到的最近一個美股交易日（前一個平日；美國假日時會更早）。"""
    d = pd.Timestamp(now.date()) - pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def fit_gap_model(sox: pd.Series, start: str) -> tuple[float, float, float, int]:
    p = data._finmind("TaiwanStockPrice", "0050", start)
    p = p[(p["close"] > 0) & (p["open"] > 0)].assign(date=lambda x: pd.to_datetime(x["date"])).set_index("date")
    div = data._finmind("TaiwanStockDividendResult", "0050", start)
    ex = set(pd.to_datetime(div["date"])) if len(div) else set()
    gap = (p["open"] / p["close"].shift(1) - 1)
    gap = gap[~gap.index.isin(ex)].dropna()
    gap = gap[gap.abs() < 0.08]  # 排除分割（0050 於 2025 年 1 拆 4）等非交易造成的假跳空
    r = sox.pct_change().dropna()
    pos = r.index.searchsorted(gap.index, side="left") - 1
    ok = pos >= 0
    x, y = r.iloc[pos[ok]].to_numpy(), gap[ok].to_numpy()
    b, a = np.polyfit(x, y, 1)
    resid = y - (a + b * x)
    return float(a), float(b), float(resid.std()), int(ok.sum())


def build(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(TZ)
    start = (now - timedelta(days=365 * FIT_YEARS + 30)).strftime("%Y-%m-%d")
    hist = {sid: us_history(sid, start) for sid in INDICES}
    last = hist["^SOX"].index[-1]
    if last < expected_us_date(now) - pd.Timedelta(days=3):
        raise RuntimeError(f"美股資料停在 {last.date()}，不像是最新的")
    if last < expected_us_date(now):
        print(f"美股最新只到 {last.date()}（預期 {expected_us_date(now).date()}），可能尚未更新或美國休市")
    rows = []
    for sid, label in INDICES.items():
        s = hist[sid]
        rows.append({"item": label, "symbol": sid, "us_date": f"{s.index[-1]:%Y-%m-%d}",
                     "close": round(float(s.iloc[-1]), 2), "change": float(s.iloc[-1] / s.iloc[-2] - 1)})
    a, b, sd, n = fit_gap_model(hist["^SOX"], start)
    sox_chg = rows[0]["change"]
    rows.append({"item": "0050 預估開盤跳空", "symbol": "0050", "us_date": f"{last:%Y-%m-%d}",
                 "close": None, "change": a + b * sox_chg, "low": a + b * sox_chg - sd,
                 "high": a + b * sox_chg + sd, "beta": b, "samples": n})
    for r in rows:
        r["updated_at"] = now.strftime("%Y-%m-%d %H:%M")
    return rows


def main() -> None:
    out = Path(sys.argv[1])
    now = datetime.now(TZ)
    try:
        rows = build(now)
    except data.QuotaExceeded as e:  # 匿名額度常被同一出口 IP 的其他流量用光：當成「還沒好」，讓排程稍後重試
        print(f"FinMind 額度用完：{e}")
        raise SystemExit(3)
    if pd.Timestamp(rows[0]["us_date"]) < expected_us_date(now):
        print(f"美股資料尚未更新到 {expected_us_date(now).date()}")
        raise SystemExit(3)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for r in rows:
        print(r["item"], r["us_date"], f"{r['change']:+.2%}")


if __name__ == "__main__":
    main()
