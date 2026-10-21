"""下載上櫃（TPEx）股票資料並建立時點正確選股池，規則與上市版完全相同（前 140 名、上市滿 120 交易日）。"""
from yang_eye import data
from yang_eye import universe_pit as up
from scripts.download_factors import run

if __name__ == "__main__":
    ids = up.candidates(market="tpex")
    print(f"上櫃候選 {len(ids)} 檔", flush=True)
    run(ids, data.prices, "上櫃股價")
    universe = up.build(ids)
    up.save(universe, "universe_pit_tpex")
    members = sorted({s for xs in universe.values() for s in xs})
    print(f"上櫃選股池 {len(universe)} 期，歷年成員 {len(members)} 檔", flush=True)
    run(members, data.dividends, "上櫃除權息")
    run(members, data.revenue, "上櫃營收")
    print("完成", flush=True)
