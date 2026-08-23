"""資金費率（Funding Rate）追蹤：OKX 永續合約每 8 小時收取一次的多空資金費率——正值代表
多頭付錢給空頭（市場整體偏多、持有多單要付出成本），負值代表空頭付錢給多頭。這是加密貨幣
永續合約特有的機制（股票沒有這個概念，也是股票永續合約跟真正的股票最大的差異之一），拿來
當「市場情緒過熱程度」的輔助參考。

⚠️ 誠實範圍說明：資金費率反映的是「持有合約部位的多空傾向與成本」，不是「這個方向一定會
贏」的訊號——費率極端偏高（多頭擁擠）業界常被視為短線反轉/回檔風險升高，不是加碼訊號。
這裡只負責客觀分類費率高低，不做多空建議，也不參與 brain.fuse() 的訊號融合（純資訊揭露，
不影響任何既有訊號判斷邏輯）。

純函式（classify_funding_rate）+ 網路呼叫（fetch_funding_rate）分離，方便單元測試——跟
oi_tracker.py 同樣的設計。
"""
import logging

import httpx

logger = logging.getLogger("funding_rate")

OKX_FUNDING_RATE_URL = "https://www.okx.com/api/v5/public/funding-rate"

# 費率分類門檻（%）。OKX 回傳的原始 fundingRate 通常是每 8 小時 0.01%~0.05% 這種量級的
# 小數（例如 0.0003 代表 0.03%），這裡已經換算成百分比後再比較門檻，比較符合直覺。
FUNDING_RATE_HIGH_PCT = 0.05   # 高於這個視為「多頭付費偏高」
FUNDING_RATE_LOW_PCT = -0.05   # 低於這個視為「空頭付費偏高」


async def fetch_funding_rate(client: httpx.AsyncClient, inst_id: str) -> dict | None:
    """抓取單一永續合約目前的資金費率。回傳 {"inst_id", "funding_rate_pct", "next_funding_time"}，
    查不到就回傳 None——現貨／非永續合約商品本來就沒有這個概念，OKX 對這種 instId 查詢會
    回傳空清單，呼叫端據此優雅略過，不需要另外判斷商品類型。"""
    resp = await client.get(OKX_FUNDING_RATE_URL, params={"instId": inst_id})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        logger.warning("OKX funding-rate API error for %s: %s", inst_id, data.get("msg"))
        return None
    rows = data.get("data", [])
    if not rows:
        return None
    row = rows[0]
    try:
        return {
            "inst_id": inst_id,
            "funding_rate_pct": round(float(row["fundingRate"]) * 100.0, 4),
            "next_funding_time": int(row["nextFundingTime"]) if row.get("nextFundingTime") else None,
        }
    except (KeyError, TypeError, ValueError):
        return None


def classify_funding_rate(funding_rate_pct: float | None) -> dict:
    """回傳 {"label": str, "is_extreme": bool}。funding_rate_pct 是 None（查不到資料、
    或這檔本來就不是永續合約）時回傳中性「無資料」，不瞎猜方向。"""
    if funding_rate_pct is None:
        return {"label": "無資料", "is_extreme": False}
    if funding_rate_pct >= FUNDING_RATE_HIGH_PCT:
        return {"label": "多頭付費偏高（情緒偏熱，留意過度擁擠風險）", "is_extreme": True}
    if funding_rate_pct <= FUNDING_RATE_LOW_PCT:
        return {"label": "空頭付費偏高（情緒偏空，留意軋空風險）", "is_extreme": True}
    return {"label": "費率正常範圍", "is_extreme": False}


if __name__ == "__main__":
    _passed = 0
    _total = 0

    def check(name, actual, expected):
        global _passed, _total
        _total += 1
        ok = actual == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={actual} expected={expected}")
        if ok:
            _passed += 1

    # 1) 沒有資料 -> 中性，不瞎猜
    r0 = classify_funding_rate(None)
    check("no data -> 無資料", r0["label"], "無資料")
    check("no data -> not extreme", r0["is_extreme"], False)

    # 2) 正常範圍
    r1 = classify_funding_rate(0.01)
    check("small positive rate -> 正常範圍", r1["label"], "費率正常範圍")
    check("small positive rate -> not extreme", r1["is_extreme"], False)

    r1b = classify_funding_rate(-0.01)
    check("small negative rate -> 正常範圍", r1b["label"], "費率正常範圍")

    r1c = classify_funding_rate(0.0)
    check("zero rate -> 正常範圍", r1c["label"], "費率正常範圍")

    # 3) 多頭付費偏高
    r2 = classify_funding_rate(0.08)
    check("high positive rate -> 多頭付費偏高", r2["label"], "多頭付費偏高（情緒偏熱，留意過度擁擠風險）")
    check("high positive rate -> is_extreme True", r2["is_extreme"], True)

    # 4) 空頭付費偏高
    r3 = classify_funding_rate(-0.08)
    check("high negative rate -> 空頭付費偏高", r3["label"], "空頭付費偏高（情緒偏空，留意軋空風險）")
    check("high negative rate -> is_extreme True", r3["is_extreme"], True)

    # 5) 剛好在門檻邊界 -> 算作極端（>=/<=，不是 >/<）
    r4 = classify_funding_rate(0.05)
    check("exactly at high threshold -> extreme (boundary inclusive)", r4["is_extreme"], True)
    r5 = classify_funding_rate(-0.05)
    check("exactly at low threshold -> extreme (boundary inclusive)", r5["is_extreme"], True)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
