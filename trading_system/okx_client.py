"""OKX public REST 客戶端：商品篩選（ticker 掃描）+ K 線抓取。全部走公開端點，不需要
API 金鑰、不下單。純函式（screen_active_instruments）刻意跟網路請求分離，方便單元測試。
"""
import logging

import httpx

logger = logging.getLogger("okx_client")

OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"

# OKX 於 2026 年上線「股票永續合約」（Stock Perpetuals / Equity Perpetual Swaps），
# USDT 計價、24/7 交易，涵蓋 Magnificent 7 等指標股。只用來在畫面上標示資產類別，
# 不影響篩選邏輯——篩選一律只看成交額/振幅，不分加密貨幣或股票。
# 這份清單是目前已由多方新聞來源確認的品項；OKX 之後可能繼續擴充，若畫面上出現
# 沒被標到「📈 股票永續」的新股票商品，把它的代碼加進這裡即可。
KNOWN_STOCK_TICKERS = {
    "TSLA", "AAPL", "NVDA", "GOOGL", "GOOG", "MSFT", "AMZN", "META",
}


def asset_class(inst_id: str) -> str:
    """回傳 "stock" 或 "crypto"，純粹用於畫面標籤，不影響任何篩選/訊號邏輯。"""
    base = inst_id.split("-")[0].upper()
    base = base[1:] if base.startswith("X") and base[1:] in KNOWN_STOCK_TICKERS else base
    return "stock" if base in KNOWN_STOCK_TICKERS else "crypto"


def stock_ticker(inst_id: str) -> str | None:
    """從 instId 抽出乾淨的股票代號（例如 "XTSLA-USDT-SWAP" -> "TSLA"），給
    stock_fundamentals.py 查公司基本面用。不是股票永續合約就回傳 None——加密貨幣沒有
    「公司基本面」這回事，呼叫端看到 None 就不用查。"""
    base = inst_id.split("-")[0].upper()
    stripped = base[1:] if base.startswith("X") and base[1:] in KNOWN_STOCK_TICKERS else base
    return stripped if stripped in KNOWN_STOCK_TICKERS else None


async def _fetch_tickers(client: httpx.AsyncClient, inst_type: str) -> list[dict]:
    resp = await client.get(OKX_TICKERS_URL, params={"instType": inst_type})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise ValueError(f"OKX tickers API error ({inst_type}): {data.get('msg')}")
    return data.get("data", [])


async def fetch_swap_tickers(client: httpx.AsyncClient) -> list[dict]:
    """抓取 OKX 所有 USDT 本位永續合約（SWAP）的 24h ticker 快照——本系統的當沖策略
    （20 EMA + 盒子突破，搭配風報比停損停利）預設就是設計給這種可以做多可以做空、
    有槓桿概念的商品。這裡不分加密貨幣或股票永續合約——兩者目前都掛在同一個
    instType=SWAP 底下，只要商品 instId 符合 -USDT-SWAP 後綴，就會一起進到
    screen_active_instruments() 的篩選池，用同一套成交額/振幅門檻、同一套策略。"""
    return await _fetch_tickers(client, "SWAP")


async def fetch_spot_tickers(client: httpx.AsyncClient) -> list[dict]:
    """抓取 OKX 所有 USDT 現貨交易對的 24h ticker 快照。現貨只能做多、沒有槓桿/爆倉概念，
    目前**不會**自動進入篩選/自動分析池（`screen_active_instruments` 只吃 SWAP）——
    只出現在「全部商品總覽」讓你瀏覽/搜尋，想看技術分析可以點「🔍 分析」單獨查一檔
    （`analyze_one_instrument` 對 instId 沒有預設立場，現貨一樣算得出 K 線訊號，只是
    停損停利在現貨語境下沒有真正的槓桿保證金意義，看的時候要記得這個差異）。"""
    return await _fetch_tickers(client, "SPOT")


def parse_instruments(tickers: list[dict], extra_keywords: tuple = (), product_type: str = "swap") -> list[dict]:
    """把 OKX ticker 原始資料解析成標準格式，**不套用任何流動性/振幅門檻、不截斷筆數**——
    給「全部商品總覽」用，讓使用者看得到 OKX 上全部（通常 200~300+ 檔）合約的基本報價，
    不是只看得到自動篩選出來的那幾檔。`screen_active_instruments()` 在這份完整清單上
    再套門檻篩選，兩者共用同一份解析邏輯，門檻邏輯只寫一次。

    product_type: "swap"（永續合約，instId 形如 BTC-USDT-SWAP）或 "spot"（現貨，
    instId 形如 BTC-USDT，沒有 -SWAP 後綴）——回傳的每筆資料都會標上這個欄位，
    給前端「合約/現貨」分類篩選用，兩種格式不會互相誤判。

    注意：OKX ticker 的 `volCcy24h` 欄位本身就是以計價貨幣（USDT 本位合約即 USDT）計算的
    24h 成交額，不需要再乘上最新價——用 `vol24h`（張數/幣數）乘價格會重複換算、算出錯誤數字。
    """
    parsed = []
    for t in tickers:
        inst_id = t.get("instId", "")
        if product_type == "spot":
            is_valid = inst_id.endswith("-USDT") and not inst_id.endswith("-SWAP")
        else:
            is_valid = inst_id.endswith("-USDT-SWAP")
        is_extra = any(kw in inst_id for kw in extra_keywords)
        if not (is_valid or is_extra):
            continue
        try:
            last = float(t["last"])
            vol_usdt = float(t["volCcy24h"])
            high = float(t["high24h"])
            low = float(t["low24h"])
        except (KeyError, TypeError, ValueError):
            continue
        if low <= 0:
            continue
        amplitude_pct = (high - low) / low * 100.0

        # 24h 漲跌幅（有方向性，畫面上綠漲紅跌用這個，不是用 amplitude_pct——後者只是
        # 當天最高最低的震盪幅度，沒有正負號）。open24h 缺漏或是 0 時給 None，
        # 前端遇到 None 就不上色，不會亂猜方向。
        change_pct = None
        try:
            open24h = float(t.get("open24h", ""))
            if open24h > 0:
                change_pct = round((last - open24h) / open24h * 100.0, 2)
        except (TypeError, ValueError):
            change_pct = None

        parsed.append({
            "instId": inst_id,
            "name": inst_id.replace("-SWAP", ""),
            "price": last,
            "vol_usdt": vol_usdt,
            "amplitude_pct": round(amplitude_pct, 2),
            "change_pct": change_pct,
            "asset_class": asset_class(inst_id),
            "product_type": product_type,
        })
    return parsed


def merge_fresh_quotes(previous: list[dict], fresh: list[dict]) -> list[dict]:
    """把「輕量報價快照」（只有 price/vol_usdt/amplitude_pct/change_pct，供
    /api/v1/tickers 高頻輪詢用）套進舊的 all_instruments 清單：只覆蓋報價欄位，
    OI 欄位（oi_ccy/oi_change_pct）刻意沿用舊值不動——OI 有自己一套「跟上一輪快照比較」
    的邏輯（見 background._refresh_signals），輪詢週期跟這裡不同，兩邊互相覆蓋只會把
    OI 比較基準搞亂。舊清單有但這輪沒抓到的商品（極少數下架邊界情況）保留舊資料，
    不會讓畫面上一筆商品無預警消失；新清單有但舊清單沒有的（新上架）直接併入。"""
    fresh_by_id = {item["instId"]: item for item in fresh}
    merged = []
    seen = set()
    for old in previous:
        inst_id = old["instId"]
        seen.add(inst_id)
        new = fresh_by_id.get(inst_id)
        if new is None:
            merged.append(old)
            continue
        updated = dict(old)
        updated["price"] = new["price"]
        updated["vol_usdt"] = new["vol_usdt"]
        updated["amplitude_pct"] = new["amplitude_pct"]
        updated["change_pct"] = new["change_pct"]
        merged.append(updated)
    for item in fresh:
        if item["instId"] not in seen:
            merged.append(item)
    return merged


def screen_active_instruments(
    tickers: list[dict],
    min_vol_usdt: float = 50_000_000.0,
    min_amplitude_pct: float = 3.0,
    top_n: int = 6,
    extra_keywords: tuple = (),
) -> list[dict]:
    """在 parse_instruments() 的完整清單上，篩選具備流動性（24h 成交額）與波動度（24h 振幅）
    的合約，依振幅由高到低排序取前 top_n 檔——這是「自動監控」用的子集合，不是全部商品。"""
    candidates = [
        c for c in parse_instruments(tickers, extra_keywords)
        if c["vol_usdt"] >= min_vol_usdt and c["amplitude_pct"] >= min_amplitude_pct
    ]
    candidates.sort(key=lambda c: c["amplitude_pct"], reverse=True)
    return candidates[:top_n]


async def fetch_confirmed_candles(
    client: httpx.AsyncClient, inst_id: str, bar: str = "5m", limit: int = 50
) -> list[dict]:
    """抓取近 `limit` 根 K 線，並捨棄最新（可能還沒收線）的那一根，只保留「已收盤」的資料。

    這是避免「K 線未收線假突破」的關鍵：OKX REST /market/candles 明確標示第一筆（最新）
    資料不保證已完結，若拿還在走的那根去判斷突破，最後幾秒插針崩回來就會變成假訊號。
    回傳升冪（舊到新）的 [{ts,o,h,l,c,vol}, ...]。
    """
    resp = await client.get(OKX_CANDLES_URL, params={"instId": inst_id, "bar": bar, "limit": limit})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise ValueError(f"OKX candles API error for {inst_id}: {data.get('msg')}")
    rows = data.get("data", [])  # OKX 回傳新到舊
    rows = rows[1:] if len(rows) > 1 else []  # 捨棄第一筆（最新、可能未收線）

    candles = []
    for row in reversed(rows):  # 轉成舊到新，餵給策略模組
        ts, o, h, low, c, vol = row[0], row[1], row[2], row[3], row[4], row[5]
        candles.append({
            "ts": int(ts), "o": float(o), "h": float(h), "l": float(low),
            "c": float(c), "vol": float(vol),
        })
    return candles


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

    # 1) 基本篩選：成交額與振幅都達標才會入選
    tickers = [
        {"instId": "BTC-USDT-SWAP", "last": "100.0", "volCcy24h": "80000000", "high24h": "106.0", "low24h": "100.0"},
        {"instId": "ETH-USDT-SWAP", "last": "50.0", "volCcy24h": "10000000", "high24h": "52.0", "low24h": "50.0"},  # 成交額不夠
        {"instId": "DOGE-USDT-SWAP", "last": "1.0", "volCcy24h": "90000000", "high24h": "1.01", "low24h": "1.0"},  # 振幅不夠
        {"instId": "BTC-USD-SWAP", "last": "100.0", "volCcy24h": "999999999", "high24h": "200.0", "low24h": "100.0"},  # 非 USDT 本位，排除
    ]
    result = screen_active_instruments(tickers, min_vol_usdt=50_000_000, min_amplitude_pct=3.0, top_n=6)
    check("only BTC-USDT-SWAP passes both thresholds", [c["instId"] for c in result], ["BTC-USDT-SWAP"])
    check("amplitude computed correctly", result[0]["amplitude_pct"], 6.0)

    # 2) top_n 截斷 + 依振幅排序
    many = [
        {"instId": f"T{i}-USDT-SWAP", "last": "100", "volCcy24h": "60000000",
         "high24h": str(100 + i), "low24h": "100"}
        for i in range(1, 6)
    ]
    result2 = screen_active_instruments(many, min_vol_usdt=50_000_000, min_amplitude_pct=1.0, top_n=2)
    check("top_n truncates to 2", len(result2), 2)
    check("sorted by amplitude desc", [c["instId"] for c in result2], ["T5-USDT-SWAP", "T4-USDT-SWAP"])

    # 3) extra_keywords 讓非 -USDT-SWAP 的商品也能入選
    extra = [{"instId": "GOLD-USD-SWAP", "last": "2000", "volCcy24h": "60000000", "high24h": "2100", "low24h": "2000"}]
    result3 = screen_active_instruments(extra, min_vol_usdt=50_000_000, min_amplitude_pct=1.0, extra_keywords=("GOLD",))
    check("extra_keywords includes GOLD instrument", [c["instId"] for c in result3], ["GOLD-USD-SWAP"])

    # 4) asset_class 標籤：股票永續合約 vs 加密貨幣
    check("asset_class TSLA-USDT-SWAP -> stock", asset_class("TSLA-USDT-SWAP"), "stock")
    check("asset_class BTC-USDT-SWAP -> crypto", asset_class("BTC-USDT-SWAP"), "crypto")
    check("asset_class XTSLA-USDT-SWAP -> stock (X 前綴也認得)", asset_class("XTSLA-USDT-SWAP"), "stock")
    check("screen_active_instruments tags asset_class", result[0]["asset_class"], "crypto")

    check("stock_ticker TSLA-USDT-SWAP -> TSLA", stock_ticker("TSLA-USDT-SWAP"), "TSLA")
    check("stock_ticker XTSLA-USDT-SWAP -> TSLA (去掉 X 前綴)", stock_ticker("XTSLA-USDT-SWAP"), "TSLA")
    check("stock_ticker BTC-USDT-SWAP -> None（加密貨幣沒有公司基本面）", stock_ticker("BTC-USDT-SWAP"), None)

    # 5) parse_instruments：不套門檻、不截斷，給「全部商品總覽」用
    all_parsed = parse_instruments(tickers)  # 沿用第 1 組資料，4 檔裡有 3 檔是合法 USDT 本位合約
    check("parse_instruments keeps all valid USDT-SWAP instruments (no threshold)",
          sorted(c["instId"] for c in all_parsed), ["BTC-USDT-SWAP", "DOGE-USDT-SWAP", "ETH-USDT-SWAP"])
    check("parse_instruments still excludes non-USDT-SWAP without extra_keywords",
          "BTC-USD-SWAP" not in [c["instId"] for c in all_parsed], True)
    check("screen_active_instruments is a strict subset of parse_instruments",
          set(c["instId"] for c in result).issubset(set(c["instId"] for c in all_parsed)), True)
    check("parse_instruments tags product_type='swap' by default", all_parsed[0]["product_type"], "swap")

    # 6) parse_instruments(product_type="spot")：現貨 instId（沒有 -SWAP 後綴）才算數，
    # 永續合約的 instId 反而要被排除，兩種格式不能互相誤判。
    spot_tickers = [
        {"instId": "BTC-USDT", "last": "100.0", "volCcy24h": "80000000", "high24h": "106.0", "low24h": "100.0"},
        {"instId": "ETH-USDT-SWAP", "last": "50.0", "volCcy24h": "80000000", "high24h": "52.0", "low24h": "50.0"},
    ]
    spot_parsed = parse_instruments(spot_tickers, product_type="spot")
    check("spot parsing keeps only the spot pair", [c["instId"] for c in spot_parsed], ["BTC-USDT"])
    check("spot parsing tags product_type='spot'", spot_parsed[0]["product_type"], "spot")

    # 7) change_pct：24h 漲跌幅（有方向性，畫面上綠漲紅跌要用這個，不是 amplitude_pct）
    change_tickers = [
        {"instId": "UP-USDT-SWAP", "last": "110.0", "volCcy24h": "60000000",
         "high24h": "112.0", "low24h": "95.0", "open24h": "100.0"},   # 漲 +10%
        {"instId": "DOWN-USDT-SWAP", "last": "90.0", "volCcy24h": "60000000",
         "high24h": "105.0", "low24h": "88.0", "open24h": "100.0"},   # 跌 -10%
        {"instId": "NOOPEN-USDT-SWAP", "last": "100.0", "volCcy24h": "60000000",
         "high24h": "101.0", "low24h": "99.0"},                        # 沒有 open24h 欄位
    ]
    change_parsed = {c["instId"]: c for c in parse_instruments(change_tickers)}
    check("change_pct computed correctly for a gain", change_parsed["UP-USDT-SWAP"]["change_pct"], 10.0)
    check("change_pct computed correctly for a loss", change_parsed["DOWN-USDT-SWAP"]["change_pct"], -10.0)
    check("change_pct is None when open24h is missing (no guessing direction)",
          change_parsed["NOOPEN-USDT-SWAP"]["change_pct"], None)

    # 8) merge_fresh_quotes：即時報價輪詢（/api/v1/tickers）只更新報價欄位，OI 沿用舊值，
    # 舊清單獨有/新清單獨有的商品都要保留，不能無預警消失或漏掉新上架的。
    old_list = [
        {"instId": "BTC-USDT-SWAP", "name": "BTC-USDT", "price": 100.0, "vol_usdt": 1e8,
         "amplitude_pct": 5.0, "change_pct": 2.0, "asset_class": "crypto", "product_type": "swap",
         "oi_ccy": 500.0, "oi_change_pct": 3.5},
        {"instId": "DELISTED-USDT-SWAP", "name": "DELISTED-USDT", "price": 1.0, "vol_usdt": 1e7,
         "amplitude_pct": 1.0, "change_pct": 0.0, "asset_class": "crypto", "product_type": "swap"},
    ]
    fresh_list = [
        {"instId": "BTC-USDT-SWAP", "name": "BTC-USDT", "price": 103.0, "vol_usdt": 1.1e8,
         "amplitude_pct": 5.5, "change_pct": 3.0, "asset_class": "crypto", "product_type": "swap"},
        {"instId": "NEW-USDT-SWAP", "name": "NEW-USDT", "price": 10.0, "vol_usdt": 6e7,
         "amplitude_pct": 4.0, "change_pct": 1.0, "asset_class": "crypto", "product_type": "swap"},
    ]
    merged = {c["instId"]: c for c in merge_fresh_quotes(old_list, fresh_list)}
    check("merge_fresh_quotes updates price from fresh snapshot", merged["BTC-USDT-SWAP"]["price"], 103.0)
    check("merge_fresh_quotes keeps oi_ccy from old snapshot (not refreshed by ticker poll)",
          merged["BTC-USDT-SWAP"]["oi_ccy"], 500.0)
    check("merge_fresh_quotes keeps oi_change_pct from old snapshot",
          merged["BTC-USDT-SWAP"]["oi_change_pct"], 3.5)
    check("merge_fresh_quotes keeps an instrument missing from this round's fresh snapshot",
          "DELISTED-USDT-SWAP" in merged, True)
    check("merge_fresh_quotes adds a newly-listed instrument not in the old snapshot",
          "NEW-USDT-SWAP" in merged, True)
    check("merge_fresh_quotes result count is old ∪ fresh (no duplicates, nothing dropped)", len(merged), 3)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
