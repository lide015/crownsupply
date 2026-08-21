"""美股代幣（Stock Perpetuals）公司基本面：抓公司名稱／產業／市值／掛牌日期等基本資料，
給「單一商品詳情頁」用。只在 asset_class == "stock" 時才會用到（見 okx_client.stock_ticker），
加密貨幣不會呼叫這裡。

⚠️ 誠實範圍說明：這是「公司基本面」（是哪家公司、做什麼產業、市值多大、哪一年上市），
不是即時財報數字（不是本益比、EPS、營收成長率那種每季會變的數字）——免費資料源能穩定
拿到的就是這種偏靜態的公司輪廓資料。資料來源是 Finnhub 免費方案
（https://finnhub.io/register，需自行申請免費 API key，見 .env.example 的
FINNHUB_API_KEY）；沒設定金鑰、或這一輪查詢失敗，就不會顯示這塊，不影響任何其他功能
（合約/現貨報價、技術分析、AI 新聞情緒都跟這個金鑰完全無關）。

純函式（parse_company_profile）+ 網路呼叫（fetch_company_profile）分離，方便單元測試，
跟 okx_client.py／oi_tracker.py 同樣的設計慣例。
"""
import logging

import httpx

logger = logging.getLogger("stock_fundamentals")

FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"


def parse_company_profile(raw: dict) -> dict | None:
    """把 Finnhub `/stock/profile2` 的原始回應整理成畫面要用的格式。

    Finnhub 對查無資料的代號回傳空 dict `{}`（不是錯誤狀態碼），所以用 "有沒有公司名稱"
    當作「這筆資料到底有沒有查到」的判斷依據，而不是只看 HTTP 狀態碼。
    市值（marketCapitalization）Finnhub 給的單位是「百萬美元」，這裡換算成原始美元，
    避免前端還要記住這個單位換算細節。缺欄位一律給 None，不瞎猜/不補 0。
    """
    if not raw or not raw.get("name"):
        return None
    market_cap_musd = raw.get("marketCapitalization")
    return {
        "name": raw.get("name"),
        "industry": raw.get("finnhubIndustry") or None,
        "exchange": raw.get("exchange") or None,
        "country": raw.get("country") or None,
        "ipo_date": raw.get("ipo") or None,
        "market_cap_usd": (
            market_cap_musd * 1_000_000 if isinstance(market_cap_musd, (int, float)) else None
        ),
        "website": raw.get("weburl") or None,
        "logo": raw.get("logo") or None,
    }


async def fetch_company_profile(client: httpx.AsyncClient, ticker: str, api_key: str) -> dict | None:
    """ticker 是乾淨的股票代號（例如 "TSLA"，用 okx_client.stock_ticker() 從 instId
    抽出來的那種，不是 OKX 的 instId 本身）；api_key 是使用者自己申請的 Finnhub 免費金鑰。

    任何失敗情況（沒設金鑰／額度用完／查無資料／連線失敗／回應格式跟預期不同）都回傳
    None，呼叫端看到 None 就顯示「公司基本面暫時無法取得」，不會讓整個詳情頁掛掉——
    這是外部資料源的公開限制，不是本系統的錯誤。
    """
    if not api_key or not ticker:
        return None
    try:
        resp = await client.get(
            FINNHUB_PROFILE_URL, params={"symbol": ticker, "token": api_key}, timeout=8.0
        )
        resp.raise_for_status()
        return parse_company_profile(resp.json())
    except Exception as exc:  # noqa: BLE001 — 公司基本面拿不到不該擋住詳情頁其他資料
        logger.warning("fetch_company_profile failed for %s: %s", ticker, exc)
        return None


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

    # 1) 正常回應解析
    raw = {
        "country": "US", "currency": "USD", "exchange": "NASDAQ NMS - GLOBAL MARKET",
        "ipo": "2010-06-29", "marketCapitalization": 800000.0, "name": "Tesla, Inc.",
        "shareOutstanding": 3180.0, "ticker": "TSLA", "weburl": "https://www.tesla.com/",
        "logo": "https://static2.finnhub.io/file/publicdatany/finnhubimage/stock_logo/TSLA.png",
        "finnhubIndustry": "Auto Manufacturers",
    }
    parsed = parse_company_profile(raw)
    check("parses company name", parsed["name"], "Tesla, Inc.")
    check("parses industry", parsed["industry"], "Auto Manufacturers")
    check("converts market cap from millions to raw USD", parsed["market_cap_usd"], 800000.0 * 1_000_000)
    check("parses ipo date", parsed["ipo_date"], "2010-06-29")
    check("parses exchange", parsed["exchange"], "NASDAQ NMS - GLOBAL MARKET")

    # 2) 查無資料（Finnhub 對不存在的代號回傳空 dict，或缺公司名稱）
    check("empty response -> None", parse_company_profile({}), None)
    check("response missing name -> None", parse_company_profile({"exchange": "NASDAQ"}), None)

    # 3) 市值缺漏時不要亂猜/補 0
    raw_no_cap = dict(raw)
    del raw_no_cap["marketCapitalization"]
    check("missing market cap -> None (not 0)", parse_company_profile(raw_no_cap)["market_cap_usd"], None)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
