"""陽之眼模擬帳戶（前瞻紙上交易）引擎。

帳本存在儀表板裡，這支程式只處理本地的 JSON 帳本檔：
    python -m yang_eye.paper <帳本資料夾>                  每日更新（資料未更新時結束碼 3）
    python -m yang_eye.paper <帳本資料夾> --init YYYY-MM-DD  建立新帳本
流程：從儀表板下載帳本 → 執行本程式 → 把改過的檔案傳回儀表板。

每天收盤後執行一次：
1. 抓證交所全市場當日行情（OpenAPI，一次呼叫），存成交金額快照（選股池用）
2. 持股若遇除權息，依 前收/參考價 調整股數（股利視同再投入）
3. 以收盤價更新淨值：模擬帳戶、選股池等權重、加權報酬指數
4. 若是本月第一個 >= 11 日的交易日且尚未換股：選股並以當日收盤價換股
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from yang_eye import data
from dataclasses import replace

from yang_eye import universe_pit
from yang_eye.strategy import RevenueMomentumParams, revenue_signals, select
from yang_eye.universe_pit import is_common_stock

INITIAL_CAPITAL = 1_000_000
FEE_RATE = 0.001425
MIN_FEE = 20
TAX_RATE = 0.003
TOP_N_UNIVERSE = 140
MIN_LISTED_DAYS = 182
SNAPSHOT_DAYS = 30
TZ = timezone(timedelta(hours=8))
FILES = ["account", "nav", "holdings", "trades", "ew_basket", "value_snapshots", "shadow"]
PORTFOLIOS = ("模擬帳戶", "選股池等權重", "加權報酬指數")
# v0.7 對照：同樣的核心衛星，選股池改成上市前 140 ∪ 上櫃前 140；只記錄、不取代模擬帳戶
SHADOW = "v0.7 對照（上市＋上櫃）"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1"
# v0.3：同產業最多 3 檔；選不滿的空位補 0050（回測的敏感度 B）。
# 回測主方案是補選股池等權重，但 100 萬的帳戶分到上百檔時每筆只有幾千元，最低手續費 20 元會吃掉 1% 以上，所以模擬帳戶改補 0050。
PARAMS = replace(RevenueMomentumParams(), max_per_industry=3, fill="0050")
# 核心衛星：每次換股把資金調回 CORE_WEIGHT 放 0050（核心），其餘照 v0.3 選股（衛星）
CORE_WEIGHT = 0.5
STRATEGY_TEXT = (f"核心衛星：{CORE_WEIGHT:.0%} 0050 ＋ {1 - CORE_WEIGHT:.0%} 營收動能 v0.3（3月YoY>{PARAMS.min_yoy3:.0%}、12月新高、YoY加速、"
                 f"均量>{PARAMS.min_avg_volume_lots:.0f}張，取前{PARAMS.top_n}檔各占衛星{1 / PARAMS.top_n:.0%}，同產業最多{PARAMS.max_per_industry}檔，"
                 f"選不滿的空位也買 {PARAMS.fill}）；每月換股時調回比例")


# ---------- 帳本讀寫 ----------

def load(folder: Path) -> dict[str, list[dict]]:
    """shadow 是後來加的，沒有這個檔就當作還沒建立 v0.7 對照。"""
    return {k: json.loads((folder / f"{k}.json").read_text(encoding="utf-8"))
            if (folder / f"{k}.json").exists() or k != "shadow" else None for k in FILES}


def _clean(x):
    """NaN／inf 不是合法 JSON（瀏覽器讀不了），一律存成 null。"""
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def save(folder: Path, ledger: dict[str, list[dict]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for k in FILES:
        if ledger.get(k) is None:
            continue
        (folder / f"{k}.json").write_text(json.dumps(_clean(ledger[k]), ensure_ascii=False, separators=(",", ":"),
                                                     allow_nan=False),
                                          encoding="utf-8")


def init_ledger(start: str) -> dict[str, list[dict]]:
    p = PARAMS
    account = {"inception": start, "initial_capital": INITIAL_CAPITAL, "cash": INITIAL_CAPITAL,
               "nav": INITIAL_CAPITAL, "ew_nav": INITIAL_CAPITAL, "taiex_base": None,
               "last_update": None, "last_rebalance": None, "next_rebalance": None,
               "holdings_count": 0,
               "strategy": STRATEGY_TEXT,
               "universe": f"上市普通股近 20 日成交金額前 {TOP_N_UNIVERSE} 名，上市滿 6 個月"}
    return {"account": [account], "nav": [], "holdings": [], "trades": [], "ew_basket": [],
            "value_snapshots": seed_snapshots(start)}


def seed_snapshots(before: str) -> list[dict]:
    """建帳時 OpenAPI 只有當天資料，用回測時快取的 FinMind 股價補上之前 20 個交易日的成交金額。"""
    rows = []
    for path in sorted((data.CACHE / "price").glob("*.parquet")):
        sid = path.stem
        if not is_common_stock(sid):
            continue
        p = pd.read_parquet(path)
        if p.empty:
            continue
        p = p[(p["date"] < before) & (p["close"] > 0)].tail(SNAPSHOT_DAYS)
        rows += [{"date": d, "stock_id": sid, "value": float(v), "volume": float(q)}
                 for d, v, q in zip(p["date"], p["Trading_money"], p["Trading_Volume"])]
    dates = sorted({r["date"] for r in rows})[-20:]
    return [r for r in rows if r["date"] in dates]


# ---------- 外部資料 ----------

def roc_to_date(s: str) -> str:
    return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"


def _openapi(path: str, tries: int = 6, base: str = data.TWSE_OPENAPI) -> list[dict]:
    """證交所／櫃買中心 OpenAPI 偶爾會斷線，間隔 30 秒重試。"""
    for i in range(tries):
        try:
            r = requests.get(f"{base}/{path}", timeout=60)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(30)
    raise RuntimeError(f"OpenAPI {base}/{path} 連續 {tries} 次失敗")


def market_snapshot() -> pd.DataFrame:
    """證交所 OpenAPI：最近一個交易日全部上市證券行情。"""
    rows = _openapi("exchangeReport/STOCK_DAY_ALL")
    df = pd.DataFrame(rows)
    df["date"] = df["Date"].map(roc_to_date)
    for c in ("TradeVolume", "TradeValue", "ClosingPrice"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df = df.rename(columns={"Code": "stock_id", "Name": "name", "TradeVolume": "volume",
                            "TradeValue": "value", "ClosingPrice": "close"})
    return df[["date", "stock_id", "name", "volume", "value", "close"]]


def tpex_snapshot() -> pd.DataFrame:
    """櫃買中心 OpenAPI：最近一個交易日全部上櫃證券行情（欄位對齊 market_snapshot）。"""
    df = pd.DataFrame(_openapi("tpex_mainboard_daily_close_quotes", base=TPEX_OPENAPI))
    df["date"] = df["Date"].map(roc_to_date)
    for c in ("TradingShares", "TransactionAmount", "Close"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df = df.rename(columns={"SecuritiesCompanyCode": "stock_id", "CompanyName": "name", "TradingShares": "volume",
                            "TransactionAmount": "value", "Close": "close"})
    return df[["date", "stock_id", "name", "volume", "value", "close"]]


def tpex_listing_dates() -> dict[str, str]:
    rows = _openapi("mopsfin_t187ap03_O", base=TPEX_OPENAPI)
    return {r["SecuritiesCompanyCode"]: f"{r['DateOfListing'][:4]}-{r['DateOfListing'][4:6]}-{r['DateOfListing'][6:]}"
            for r in rows if len(r.get("DateOfListing", "")) == 8}


def listing_dates() -> dict[str, str]:
    rows = _openapi("opendata/t187ap03_L")
    return {r["公司代號"]: f"{r['上市日期'][:4]}-{r['上市日期'][4:6]}-{r['上市日期'][6:]}"
            for r in rows if len(r.get("上市日期", "")) == 8}


def taiex_tr(on: str) -> float | None:
    df = _finmind_wait("TaiwanStockTotalReturnIndex", "TAIEX",
                       (pd.Timestamp(on) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))
    if df.empty:
        return None
    df = df[df["date"] <= on]
    return float(df.iloc[-1]["price"]) if len(df) and df.iloc[-1]["date"] == on else None


def dividend_factors(stock_ids: list[str], after: str, upto: str) -> dict[str, float]:
    """(after, upto] 期間的除權息調整因子：前收 / 參考價（>1 代表股數要放大）。"""
    out = {}
    for sid in stock_ids:
        df = _finmind_wait("TaiwanStockDividendResult", sid, after)
        if df.empty:  # 期間內沒有除權息時 FinMind 回傳沒有欄位的空表
            continue
        df = df[(df["date"] > after) & (df["date"] <= upto)]
        f = 1.0
        for _, r in df.iterrows():
            if r["before_price"] > 0 and r["after_price"] > 0:
                f *= r["before_price"] / r["after_price"]
        if f != 1.0:
            out[sid] = f
    return out


def _finmind_wait(*args, wait_minutes: int = 10, max_waits: int = 3) -> pd.DataFrame:
    """額度用完就等；等太多次就當成資料還沒好，讓排程稍後重試（不要讓一次執行卡好幾個小時）。"""
    for _ in range(max_waits):
        try:
            return data._finmind(*args)
        except data.QuotaExceeded as e:
            print(f"{e}；等 {wait_minutes} 分鐘", flush=True)
            time.sleep(wait_minutes * 60)
    raise DataNotReady(f"FinMind 額度連續 {max_waits} 次用完（{args[0]}）")


def fresh_revenue(stock_ids: list[str], today: str) -> pd.DataFrame:
    """選股要用上個月營收：本地快取已經有就用快取，否則向 FinMind 抓近 30 個月。"""
    period = pd.Timestamp(today).to_period("M") - 1
    start = (pd.Timestamp(today) - pd.DateOffset(months=30)).strftime("%Y-%m-%d")
    frames = []
    for sid in stock_ids:
        cached = data.CACHE / f"revenue/{sid}.parquet"
        if cached.exists():
            df = pd.read_parquet(cached)
            if ((df["revenue_year"] == period.year) & (df["revenue_month"] == period.month)).any():
                frames.append(df)
                continue
        frames.append(_finmind_wait("TaiwanStockMonthRevenue", sid, start))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------- 交易 ----------

def fee(amount: float) -> int:
    return max(MIN_FEE, round(amount * FEE_RATE)) if amount > 0 else 0


def rebalance(acct: dict, holdings: list[dict], prices: dict[str, float], names: dict[str, str],
              picks: list[str], today: str, top_n: int, fill: str | None = None,
              core: float = 0.0) -> tuple[list[dict], list[dict]]:
    """以收盤價換股：先賣不在名單的、調整留下的，再買新的；股數取整數（含零股）。

    core 比例放 fill（核心）；其餘為衛星，每檔目標 衛星/top_n，選不滿的空位也買 fill。
    """
    trades, pos = [], {h["stock_id"]: dict(h) for h in holdings}
    nav = acct["cash"] + sum(h["shares"] * prices.get(s, h["last_price"]) for s, h in pos.items())
    target_value = nav * (1 - core) / top_n
    targets = {s: int(target_value // prices[s]) for s in picks if prices.get(s, 0) > 0}
    fill_share = core + (1 - core) * (1 - len(targets) / top_n)
    if fill and fill_share > 0 and prices.get(fill, 0) > 0:
        targets[fill] = int(nav * fill_share // prices[fill])

    def trade(sid, shares, side):
        price = prices.get(sid, pos.get(sid, {}).get("last_price", 0))
        amount = shares * price
        f, tax = fee(amount), (round(amount * TAX_RATE) if side == "賣出" else 0)
        acct["cash"] += (amount - f - tax) if side == "賣出" else -(amount + f)
        trades.append({"date": today, "stock_id": sid, "name": names.get(sid, ""), "side": side,
                       "shares": shares, "price": price, "amount": round(amount), "fee": f, "tax": tax})

    for sid in list(pos):  # 賣出或減碼
        diff = targets.get(sid, 0) - pos[sid]["shares"]
        if diff < 0:
            trade(sid, -diff, "賣出")
            pos[sid]["shares"] += diff
            if pos[sid]["shares"] == 0:
                del pos[sid]
    for sid, tgt in targets.items():  # 買進或加碼
        diff = tgt - pos.get(sid, {}).get("shares", 0)
        if diff > 0:
            price = prices[sid]
            while diff > 0 and diff * price + fee(diff * price) > acct["cash"]:
                diff -= 1  # 現金不夠就少買一點
            if diff <= 0:
                continue
            trade(sid, diff, "買進")
            old = pos.get(sid, {"shares": 0, "cost": 0.0})
            pos[sid] = {"stock_id": sid, "name": names.get(sid, ""), "shares": old["shares"] + diff,
                        "cost": old["cost"] + diff * price + fee(diff * price)}
    new = []
    for sid, h in pos.items():
        new.append({"stock_id": sid, "name": h.get("name") or names.get(sid, ""), "shares": h["shares"],
                    "cost": round(h["cost"]), "last_price": prices.get(sid, h.get("last_price", 0))})
    return new, trades


# ---------- 選股 ----------

def universe(snapshots: list[dict], listed: dict[str, str], today: str) -> tuple[list[str], dict[str, float]]:
    """用今天之前的快照：平均成交金額前 140 名、上市滿 6 個月的普通股。回傳名單與平均成交量（張）。"""
    snap = pd.DataFrame(snapshots)
    snap = snap[snap["date"] < today]
    snap = snap[snap["date"].isin(sorted(snap["date"].unique())[-20:])]
    n_days = snap["date"].nunique()
    avg = snap.groupby("stock_id")[["value", "volume"]].sum() / max(n_days, 1)
    cutoff = (pd.Timestamp(today) - pd.Timedelta(days=MIN_LISTED_DAYS)).strftime("%Y-%m-%d")
    ok = [s for s in avg.index if is_common_stock(s) and listed.get(s, "9999") <= cutoff]
    top = avg.loc[ok].sort_values("value", ascending=False).head(TOP_N_UNIVERSE)
    return top.index.tolist(), (top["volume"] / 1000).to_dict()


def pick(members: list[str], avg_lots: dict[str, float], rev: pd.DataFrame, today: str,
         p: RevenueMomentumParams, industry: dict[str, str] | None = None) -> list[str]:
    sig = revenue_signals(rev)
    period = pd.Timestamp(today).to_period("M") - 1
    if period not in sig["yoy3"].index:
        return []
    df = pd.DataFrame({k: v.loc[period] for k, v in sig.items()}).reindex(members)
    df["lots"] = pd.Series(avg_lots)
    mask = (df["yoy3"] > p.min_yoy3) & (df["lots"] > p.min_avg_volume_lots)
    if p.require_new_high:
        mask &= df["new_high"].fillna(False).astype(bool)
    if p.require_accel:
        mask &= df["accel"] > 0
    return select(df[mask], p, industry)


def is_rebalance_day(today: str, last_rebalance: str | None) -> bool:
    d = pd.Timestamp(today)
    done_this_month = last_rebalance is not None and last_rebalance[:7] == today[:7]
    return d.day >= RevenueMomentumParams().rebalance_day and not done_this_month


def next_rebalance_after(today: str) -> str:
    d = pd.Timestamp(today)
    nxt = (d + pd.offsets.MonthBegin(1)).replace(day=RevenueMomentumParams().rebalance_day)
    if d.day < RevenueMomentumParams().rebalance_day:
        nxt = d.replace(day=RevenueMomentumParams().rebalance_day)
    return f"{nxt:%Y-%m-%d} 起第一個交易日"


# ---------- 每日一步 ----------

class DataNotReady(RuntimeError):
    pass


def themes() -> tuple[dict[str, list[str]], str]:
    """股票 → AI 供應鏈子產業（ToAlpha 分群，scripts/update_themes.py 更新）。一檔可屬多群。"""
    f = Path(__file__).with_name("themes.json")
    if not f.exists():
        return {}, ""
    t = json.loads(f.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for g, ids in t["groups"].items():
        for sid in ids:
            out.setdefault(sid, []).append(g)
    return out, t["as_of"]


def theme_exposure(holdings: list[dict], nav: float) -> dict:
    """衛星持股（0050 以外）的 AI 主題集中度：占帳戶淨值的比例，與權重最大的子產業。"""
    tags, as_of = themes()
    by_group: dict[str, float] = {}
    ai = 0.0
    sat = [h for h in holdings if h["stock_id"] != PARAMS.fill]
    for h in sat:
        gs = tags.get(h["stock_id"], [])
        h["theme"] = "、".join(gs)
        if gs:
            ai += h["market_value"] / nav
        for g in gs:
            by_group[g] = by_group.get(g, 0.0) + h["market_value"] / nav
    top = max(by_group, key=by_group.get) if by_group else ""
    return {"ai_weight": round(ai, 4), "ai_count": f"{sum(bool(h['theme']) for h in sat)}/{len(sat)}",
            "top_theme": top, "top_theme_weight": round(by_group.get(top, 0.0), 4), "themes_as_of": as_of}


def adjust_shares(holdings: list[dict], last: str, today: str, log=print) -> None:
    """(last, today] 期間的除權息（股利再投入）、分割與面額變更，直接改股數。"""
    acts = data.corporate_actions()
    acts = acts[(acts["date"] > last) & (acts["date"] <= today)]
    for h in holdings:
        f = dividend_factors([h["stock_id"]], last, today).get(h["stock_id"], 1.0)
        for _, a in acts[acts["stock_id"] == h["stock_id"]].iterrows():
            f /= a["factor"]  # 1 拆 4：參考價變 1/4，股數變 4 倍
        if f != 1.0:
            log(f"{h['stock_id']} 除權息／分割，股數 ×{f:.4f}")
            h["shares"] = int(round(h["shares"] * f))


def keep_snapshots(old: list[dict], snap: pd.DataFrame, today: str) -> list[dict]:
    keep = snap[snap["stock_id"].map(is_common_stock)][["date", "stock_id", "value", "volume"]]
    rows = [r for r in old if r["date"] != today] + keep.to_dict("records")
    dates = sorted({r["date"] for r in rows})[-SNAPSHOT_DAYS:]
    return [r for r in rows if r["date"] in dates]


def shadow_members(twse_snaps: list[dict], tpex_snaps: list[dict], today: str) -> tuple[list[str], dict[str, float]]:
    m1, l1 = universe(twse_snaps, listing_dates(), today)
    m2, l2 = universe(tpex_snaps, tpex_listing_dates(), today)
    return m1 + m2, {**l1, **l2}


def shadow_rebalance(sh: dict, members: list[str], lots: dict[str, float], prices: dict[str, float],
                     names: dict[str, str], today: str, log=print) -> None:
    rev = fresh_revenue(members, today)
    picks = pick(members, lots, rev, today, PARAMS, universe_pit.industries())
    log(f"{today} {SHADOW} 換股：選股池 {len(members)} 檔，選出 {len(picks)} 檔 {picks}")
    sh["holdings"], trades = rebalance(sh, sh["holdings"], prices, names, picks, today,
                                       PARAMS.top_n, PARAMS.fill, CORE_WEIGHT)
    sh["trades"] += trades
    sh["last_rebalance"] = today


def shadow_value(sh: dict, prices: dict[str, float], today: str) -> dict:
    for h in sh["holdings"]:
        h["last_price"] = prices.get(h["stock_id"], h["last_price"])
        h["market_value"] = round(h["shares"] * h["last_price"])
    nav = sh["cash"] + sum(h["market_value"] for h in sh["holdings"])
    for h in sh["holdings"]:
        h["weight"] = h["market_value"] / nav
    expo = theme_exposure(sh["holdings"], nav)
    sh.update({"nav": round(nav), "last_update": today, "ai_weight": expo["ai_weight"]})
    return {"date": today, "portfolio": SHADOW, "nav": round(nav),
            "cum_return": nav / INITIAL_CAPITAL - 1, "ai_weight": expo["ai_weight"]}


def shadow_step(sh: dict, prices: dict[str, float], names: dict[str, str], twse_snaps: list[dict],
                today: str, log=print) -> dict | None:
    """v0.7 對照的一天：存上櫃快照、除權息、月換股、估值。上櫃行情日期對不上就整天略過，不影響模擬帳戶。"""
    tp = tpex_snapshot()
    if tp["date"].iloc[0] != today:
        log(f"{SHADOW}：上櫃行情是 {tp['date'].iloc[0]}，和上市 {today} 對不上，今天略過")
        return None
    sh["tpex_snapshots"] = keep_snapshots(sh["tpex_snapshots"], tp, today)
    prices = {**prices, **{k: v for k, v in zip(tp["stock_id"], tp["close"]) if pd.notna(v) and v > 0}}
    names = {**names, **dict(zip(tp["stock_id"], tp["name"]))}
    adjust_shares(sh["holdings"], sh["last_update"], today, log)
    if is_rebalance_day(today, sh["last_rebalance"]):
        members, lots = shadow_members(twse_snaps, sh["tpex_snapshots"], today)
        shadow_rebalance(sh, members, lots, prices, names, today, log)
    return shadow_value(sh, prices, today)


def step(ledger: dict[str, list[dict]], snap: pd.DataFrame, log=print) -> dict[str, list[dict]]:
    acct = ledger["account"][0]
    today = snap["date"].iloc[0]
    # 每次執行都記下檢查時間，儀表板才分得出「沒有新資料」和「沒有執行」
    acct["last_check"] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    if acct["last_update"] and today <= acct["last_update"]:
        log(f"{today} 已經更新過，略過（只更新 account 的檢查時間）")
        return ledger
    if today < acct["inception"]:
        raise DataNotReady(f"證交所行情還停在 {today}，起始日 {acct['inception']} 的資料尚未發布")
    tr = taiex_tr(today)
    if tr is None:
        raise DataNotReady(f"FinMind 還沒有 {today} 的加權報酬指數，晚點再跑")
    prices = dict(zip(snap["stock_id"], snap["close"].where(snap["close"] > 0)))
    prices = {k: v for k, v in prices.items() if pd.notna(v)}
    names = dict(zip(snap["stock_id"], snap["name"]))

    # 1. 成交金額快照
    ledger["value_snapshots"] = keep_snapshots(ledger["value_snapshots"], snap, today)

    # 2. 除權息（股利再投入）、分割與面額變更
    last = acct["last_update"] or acct["inception"]
    if acct["last_update"]:
        adjust_shares(ledger["holdings"], last, today, log)

    # 3. 換股
    trades = []
    if is_rebalance_day(today, acct["last_rebalance"]):
        p = PARAMS
        members, lots = universe(ledger["value_snapshots"], listing_dates(), today)
        if len(members) < TOP_N_UNIVERSE // 2:
            log(f"成交金額快照不足（{len(members)} 檔），本月先不換股")
        else:
            if ledger["ew_basket"] and acct["last_rebalance"]:  # 等權重組合的股利在換股時補上
                fs = dividend_factors([b["stock_id"] for b in ledger["ew_basket"]],
                                      acct["last_rebalance"], today)
                for b in ledger["ew_basket"]:
                    b["units"] *= fs.get(b["stock_id"], 1.0)
            rev = fresh_revenue(members, today)
            picks = pick(members, lots, rev, today, p, universe_pit.industries())
            log(f"{today} 換股：選股池 {len(members)} 檔，選出 {len(picks)} 檔 {picks}")
            ledger["holdings"], trades = rebalance(acct, ledger["holdings"], prices, names,
                                                   picks, today, p.top_n, p.fill, CORE_WEIGHT)
            ledger["trades"] += trades
            # 等權重對照組：同樣的流動性門檻，換股成本以每邊 0.2925% 估計
            eligible = [s for s in members if lots.get(s, 0) > p.min_avg_volume_lots and s in prices]
            ew_value = sum(b["units"] * prices.get(b["stock_id"], b["last_price"])
                           for b in ledger["ew_basket"]) or acct["ew_nav"]
            old = {b["stock_id"]: b["units"] * prices.get(b["stock_id"], b["last_price"])
                   for b in ledger["ew_basket"]}
            target = ew_value / len(eligible)
            turnover = sum(abs(target - old.get(s, 0)) for s in eligible) + sum(
                v for s, v in old.items() if s not in eligible)
            ew_value -= turnover * (FEE_RATE * 2 + TAX_RATE) / 2
            ledger["ew_basket"] = [{"stock_id": s, "name": names.get(s, ""),
                                    "units": ew_value / len(eligible) / prices[s],
                                    "last_price": prices[s]} for s in eligible]
            acct["last_rebalance"] = today

    # 4. 估值
    for h in ledger["holdings"]:
        h["last_price"] = prices.get(h["stock_id"], h["last_price"])
        h["market_value"] = round(h["shares"] * h["last_price"])
        h["pnl"] = h["market_value"] - h["cost"]
        h["pnl_pct"] = h["pnl"] / h["cost"] if h["cost"] else 0.0
    nav = acct["cash"] + sum(h["market_value"] for h in ledger["holdings"])
    for h in ledger["holdings"]:
        h["weight"] = h["market_value"] / nav
    expo = theme_exposure(ledger["holdings"], nav)
    for b in ledger["ew_basket"]:
        b["last_price"] = prices.get(b["stock_id"], b["last_price"])
    ew_nav = sum(b["units"] * b["last_price"] for b in ledger["ew_basket"]) or acct["ew_nav"]

    if acct["taiex_base"] is None:
        acct["taiex_base"] = tr
    taiex_nav = INITIAL_CAPITAL * tr / acct["taiex_base"]

    ledger["nav"] = [r for r in ledger["nav"] if r["date"] != today]
    for name, v in zip(PORTFOLIOS, (nav, ew_nav, taiex_nav)):
        ledger["nav"].append({"date": today, "portfolio": name, "nav": round(v),
                              "cum_return": v / INITIAL_CAPITAL - 1,
                              "ai_weight": expo["ai_weight"] if name == PORTFOLIOS[0] else None})

    if ledger.get("shadow") and ledger["shadow"][0]["last_update"] < today:
        row = shadow_step(ledger["shadow"][0], prices, names, ledger["value_snapshots"], today, log)
        if row:
            ledger["nav"].append(row)
            log(f"{SHADOW} 淨值 {row['nav']:,.0f}，AI 主題占 {row['ai_weight']:.0%}")

    acct.update({"strategy": STRATEGY_TEXT, "nav": round(nav), "ew_nav": round(ew_nav), "cash": round(acct["cash"]),
                 "last_update": today, "holdings_count": len(ledger["holdings"]),
                 "next_rebalance": next_rebalance_after(today), **expo,
                 "updated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")})
    log(f"{today} 淨值：模擬帳戶 {nav:,.0f}｜等權重 {ew_nav:,.0f}｜大盤 {taiex_nav:,.0f}｜"
        f"持股 {len(ledger['holdings'])} 檔，新交易 {len(trades)} 筆｜"
        f"AI 主題 {expo['ai_count']} 檔、占淨值 {expo['ai_weight']:.0%}，最大子產業 {expo['top_theme']} {expo['top_theme_weight']:.0%}")
    return ledger


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--init", metavar="START", help="建立新帳本（起始日 YYYY-MM-DD）")
    args = ap.parse_args()
    if args.init:  # 只建立帳本（現金＋成交金額快照），第一次換股在下一次正常執行時發生
        save(args.folder, init_ledger(args.init))
        print(f"已建立帳本，起始日 {args.init}")
        return
    ledger = load(args.folder)
    try:
        ledger = step(ledger, market_snapshot())
    except DataNotReady as e:
        print(f"資料尚未更新：{e}")
        raise SystemExit(3)
    save(args.folder, ledger)


if __name__ == "__main__":
    main()
