"""抓 ToAlpha 產業輪動頁的 AI 供應鏈子產業分群，存成 yang_eye/themes.json，給模擬帳戶算主題集中度。

分群由該站依主要產品整理、會隨題材增減，所以只當「目前」的標籤用，不拿來回測。
手動執行後 commit；排程不跑這支。
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

import requests

URL = "https://toalpha.tw/rotation"
OUT = Path(__file__).resolve().parents[1] / "yang_eye" / "themes.json"


def fetch() -> dict[str, list[str]]:
    r = requests.get(URL, timeout=30, headers={"User-Agent": "yang-eye research"})
    r.raise_for_status()
    groups = {}
    for card in re.split(r'<div class="ai-card" id="t-[^"]+">', r.text)[1:]:
        card = card.split('<ul class="ai-news">')[0].split('</section>')[0]
        name = html.unescape(re.search(r'<b class="nm">(.*?)</b>', card).group(1))
        groups[name] = re.findall(r'href="/stock/(\w+)"', card)
    if len(groups) < 10:
        raise RuntimeError(f"只解析到 {len(groups)} 群，頁面格式可能改了")
    return groups


def main() -> None:
    groups = fetch()
    OUT.write_text(json.dumps({"source": URL, "as_of": date.today().isoformat(), "groups": groups},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(groups)} 群、{len({s for xs in groups.values() for s in xs})} 檔 → {OUT}")


if __name__ == "__main__":
    main()
