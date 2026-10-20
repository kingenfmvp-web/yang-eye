"""背景下載多因子研究資料；避開模擬帳戶（18:40）與盤前參考（08:10）排程時段，以免搶 FinMind 額度。"""
import time
from datetime import datetime, timedelta, timezone

from yang_eye import data
from yang_eye import universe_pit as up

TZ = timezone(timedelta(hours=8))
QUIET = [((18, 20), (19, 40)), ((7, 50), (8, 50))]  # 台北時間


def wait_if_quiet() -> None:
    while True:
        now = datetime.now(TZ)
        hm = (now.hour, now.minute)
        if not any(a <= hm < b for a, b in QUIET):
            return
        print(f"{now:%H:%M} 排程時段，暫停下載", flush=True)
        time.sleep(300)


def run(stock_ids, fetch, label):
    i = 0
    while i < len(stock_ids):
        wait_if_quiet()
        try:
            fetch(stock_ids[i])
            i += 1
            if i % 50 == 0 or i == len(stock_ids):
                print(f"{label} {i}/{len(stock_ids)}", flush=True)
        except data.QuotaExceeded:
            print(f"{datetime.now(TZ):%H:%M} 額度用完，等 10 分鐘", flush=True)
            time.sleep(600)
        except Exception as e:  # 單一檔一直失敗就跳過，不要讓整個下載停掉
            print(f"{datetime.now(TZ):%H:%M} {label} {stock_ids[i]} 失敗，跳過：{e}", flush=True)
            i += 1


if __name__ == "__main__":
    members = sorted({s for xs in up.load().values() for s in xs})
    run(members, data.per, "本益比")
    run(members, data.institutional, "三大法人")
    run(members, data.financials, "損益表")
    print("完成", flush=True)
