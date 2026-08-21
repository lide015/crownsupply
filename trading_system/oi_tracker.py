"""未平倉量（Open Interest, OI）追蹤：OKX 合約市場的公開籌碼指標，用來當「巨鯨/大戶動向」
的替代訊號。

⚠️ 誠實範圍說明：這**不是**真正的鏈上大戶錢包監控（不是在追蹤特定錢包地址的資金流向），
OKX 公開 API 沒有提供那種資料，要做那個需要額外的鏈上資料商（例如 Nansen/Arkham/Etherscan
Pro），目前沒有接。這裡做的是「衍生品市場籌碼」的替代指標：OI 在價格持平時大幅增加，
代表有大額資金正在建立新倉位（不論多空）；OI 隨價格同步變化，通常只是既有部位跟著損益
波動，不是新籌碼進場。這是業界常見的、對散戶也公開透明的替代解讀方式，但終究是「合約
未平倉量」，不是「錢包持倉」，兩者不能劃上等號。

純函式（compute_oi_delta）+ 網路呼叫（fetch_open_interest）分離，方便單元測試——跟
okx_client.py 同樣的設計。
"""
import logging

import httpx

logger = logging.getLogger("oi_tracker")

OKX_OI_URL = "https://www.okx.com/api/v5/public/open-interest"

OI_SURGE_THRESHOLD_PCT = 5.0  # OI 單一分析週期內變動超過這個百分比，視為「快速變化」


async def fetch_open_interest(client: httpx.AsyncClient, inst_id: str) -> dict | None:
    """抓取單一合約目前的未平倉量。回傳 {"inst_id", "oi", "oi_ccy"}，查不到就回傳 None
    （單一商品失敗不該擋住整輪分析，呼叫端自行決定要不要略過）。"""
    resp = await client.get(OKX_OI_URL, params={"instId": inst_id})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        logger.warning("OKX open-interest API error for %s: %s", inst_id, data.get("msg"))
        return None
    rows = data.get("data", [])
    if not rows:
        return None
    row = rows[0]
    try:
        return {
            "inst_id": inst_id,
            "oi": float(row["oi"]),        # 未平倉量（張數/合約單位）
            "oi_ccy": float(row["oiCcy"]),  # 未平倉量（換算成標的幣種數量）
        }
    except (KeyError, TypeError, ValueError):
        return None


def compute_oi_delta(current_oi: float, previous_oi: float | None) -> dict:
    """比較這次跟上次分析週期的 OI，判斷是否有「快速建倉/平倉」的跡象。
    previous_oi 是 None（第一次看到這檔商品，沒有基準值）時回傳中性結果，不瞎猜。"""
    if previous_oi is None or previous_oi <= 0:
        return {"oi_change_pct": None, "label": "尚無基準值", "is_surge": False}

    change_pct = (current_oi - previous_oi) / previous_oi * 100.0
    if change_pct >= OI_SURGE_THRESHOLD_PCT:
        label = "OI快速增加（可能有大額資金新建倉）"
    elif change_pct <= -OI_SURGE_THRESHOLD_PCT:
        label = "OI快速減少（可能有大額資金平倉/去槓桿）"
    else:
        label = "OI持平"
    return {
        "oi_change_pct": round(change_pct, 2),
        "label": label,
        "is_surge": abs(change_pct) >= OI_SURGE_THRESHOLD_PCT,
    }


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

    # 1) 沒有基準值（第一次分析）-> 中性結果，不亂猜方向
    r0 = compute_oi_delta(1000.0, None)
    check("no previous_oi -> 尚無基準值", r0["label"], "尚無基準值")
    check("no previous_oi -> not surge", r0["is_surge"], False)

    # 2) OI 大增 -> 快速增加標籤
    r1 = compute_oi_delta(1100.0, 1000.0)
    check("+10% OI change computed", r1["oi_change_pct"], 10.0)
    check("+10% OI -> surge label", r1["label"], "OI快速增加（可能有大額資金新建倉）")
    check("+10% OI -> is_surge True", r1["is_surge"], True)

    # 3) OI 大減 -> 快速減少標籤
    r2 = compute_oi_delta(900.0, 1000.0)
    check("-10% OI -> surge label", r2["label"], "OI快速減少（可能有大額資金平倉/去槓桿）")

    # 4) 變化在閾值內 -> 持平
    r3 = compute_oi_delta(1020.0, 1000.0)
    check("+2% OI -> 持平", r3["label"], "OI持平")
    check("+2% OI -> not surge", r3["is_surge"], False)

    # 5) 剛好在閾值邊界 -> 算作 surge（>=，不是 >）
    r4 = compute_oi_delta(1050.0, 1000.0)
    check("exactly +5% -> surge (boundary inclusive)", r4["is_surge"], True)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
