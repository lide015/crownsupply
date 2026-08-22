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


def parse_oi_rows(rows: list[dict]) -> list[dict]:
    """把 OKX open-interest API 回應的 data 陣列解析成標準格式，跳過欄位缺漏/格式錯誤的列
    （單一商品資料異常不該讓整批解析失敗）。純函式，跟網路呼叫分開方便測試。"""
    parsed = []
    for row in rows:
        try:
            parsed.append({
                "inst_id": row["instId"],
                "oi": float(row["oi"]),
                "oi_ccy": float(row["oiCcy"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


async def fetch_all_open_interest(client: httpx.AsyncClient, inst_type: str = "SWAP") -> list[dict]:
    """一次抓「全部」某類型合約（預設 SWAP／永續合約）的未平倉量，不用逐檔各打一次 API——
    只帶 instType、不帶 instId 時，OKX 這支公開端點就回傳該類型全部商品的資料，跟
    okx_client.fetch_swap_tickers() 的 instType 用法是同一種慣例。給熱力圖的「📌 持倉」
    模式用：現貨（SPOT）沒有未平倉量的概念，這裡固定只查 SWAP。

    單次呼叫失敗（網路錯誤、OKX 回錯誤碼）時往上拋例外，讓呼叫端決定要不要整批放棄——
    跟單檔查詢的「回 None 就略過」不同，這裡是全市場批次抓取，失敗了通常代表 OKX 那端
    有問題，重試整批比較合理，不是自己在這裡默默吞掉。"""
    resp = await client.get(OKX_OI_URL, params={"instType": inst_type})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise ValueError(f"OKX open-interest API error ({inst_type}): {data.get('msg')}")
    return parse_oi_rows(data.get("data", []))


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

    # 6) parse_oi_rows：正常解析多筆
    raw_rows = [
        {"instId": "BTC-USDT-SWAP", "oi": "10000", "oiCcy": "5000"},
        {"instId": "ETH-USDT-SWAP", "oi": "20000", "oiCcy": "8000"},
    ]
    parsed = parse_oi_rows(raw_rows)
    check("parse_oi_rows parses all valid rows", len(parsed), 2)
    check("parse_oi_rows converts fields to float", parsed[0], {"inst_id": "BTC-USDT-SWAP", "oi": 10000.0, "oi_ccy": 5000.0})

    # 7) parse_oi_rows：單筆欄位缺漏不該讓整批解析失敗，只跳過那一筆
    raw_rows_bad = [
        {"instId": "BTC-USDT-SWAP", "oi": "10000", "oiCcy": "5000"},
        {"instId": "BROKEN-SWAP"},  # 缺 oi/oiCcy
    ]
    check("parse_oi_rows skips malformed rows instead of failing entirely", len(parse_oi_rows(raw_rows_bad)), 1)

    # 8) parse_oi_rows：空清單 -> 空清單
    check("parse_oi_rows on empty input", parse_oi_rows([]), [])

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
