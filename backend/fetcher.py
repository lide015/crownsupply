"""Fetch public market data. CoinGecko primary, OKX public fallback. No HTML scraping, no auth."""
import logging
import time

import httpx

logger = logging.getLogger("fetcher")

TIMEOUT = 10.0
RETRIES = 2  # total attempts = RETRIES + 1

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FNG_URL = "https://api.alternative.me/fng/?limit=1"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"

SYMBOL_TO_CG_ID = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin"}
CG_ID_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_CG_ID.items()}
OKX_INST = {"BTC": "BTC-USDT", "ETH": "ETH-USDT", "SOL": "SOL-USDT", "BNB": "BNB-USDT"}

# 台股（TWSE 即時揭示 API）／美股與大宗商品期貨（Yahoo Finance chart API）— 預設觀察清單，
# 非窮舉全市場；想調整就改這幾個 dict。
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_INDEX_PAGE = "https://mis.twse.com.tw/stock/index.jsp"
TW_STOCKS = {"t00": "加權指數", "2330": "台積電", "2317": "鴻海", "2454": "聯發科"}

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
US_STOCKS = {"SPY": "S&P 500 ETF", "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA"}
COMMODITIES = {"GC=F": "黃金期貨", "CL=F": "WTI原油期貨", "SI=F": "白銀期貨"}


def _get_json(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    warmup_url: str | None = None,
) -> dict:
    backoff = 1.0
    last_exc: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
                if warmup_url:
                    client.get(warmup_url)
                resp = client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001 — deliberately broad, caller decides fallback
            last_exc = exc
            logger.warning("GET %s failed (attempt %d/%d): %s", url, attempt + 1, RETRIES + 1, exc)
            if attempt < RETRIES:
                time.sleep(backoff)
                backoff *= 2
    assert last_exc is not None
    raise last_exc


def fetch_quotes_coingecko() -> dict:
    data = _get_json(
        f"{COINGECKO_BASE}/simple/price",
        params={
            "ids": ",".join(SYMBOL_TO_CG_ID.values()),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
    )
    quotes = {}
    for cg_id, sym in CG_ID_TO_SYMBOL.items():
        d = data.get(cg_id)
        if not d:
            raise ValueError(f"coingecko response missing {cg_id}")
        quotes[sym] = {"usd": float(d["usd"]), "chg24": float(d.get("usd_24h_change") or 0.0)}
    return quotes


def fetch_quotes_okx() -> dict:
    data = _get_json(OKX_TICKERS_URL, params={"instType": "SPOT"})
    tickers = {t["instId"]: t for t in data.get("data", [])}
    quotes = {}
    for sym, inst in OKX_INST.items():
        t = tickers.get(inst)
        if not t:
            raise ValueError(f"okx response missing {inst}")
        last = float(t["last"])
        open24 = float(t["open24h"])
        chg24 = (last / open24 - 1.0) * 100.0 if open24 else 0.0
        quotes[sym] = {"usd": last, "chg24": chg24}
    return quotes


def fetch_fng() -> dict:
    data = _get_json(FNG_URL)
    item = data["data"][0]
    return {"value": int(item["value"]), "label": item["value_classification"]}


def fetch_klines_coingecko(days: int = 100) -> list[tuple[str, float]]:
    data = _get_json(
        f"{COINGECKO_BASE}/coins/bitcoin/market_chart",
        params={"vs_currency": "usd", "days": days, "interval": "daily"},
    )
    out = []
    for ms, price in data["prices"]:
        day = time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
        out.append((day, float(price)))
    return out


def fetch_klines_okx(limit: int = 100) -> list[tuple[str, float]]:
    data = _get_json(OKX_CANDLES_URL, params={"instId": "BTC-USDT", "bar": "1D", "limit": limit})
    rows = data.get("data", [])
    out = []
    for row in rows:
        ts_ms = int(row[0])
        close = float(row[4])
        day = time.strftime("%Y-%m-%d", time.gmtime(ts_ms / 1000))
        out.append((day, close))
    out.reverse()  # OKX returns newest-first
    return out


def fetch_ohlc_okx(limit: int = 100) -> list[tuple[str, float, float, float, float, float]]:
    """OKX 日K原生就是完整 OHLCV，供 SMC 分析用（CoinGecko 免費版 OHLC 端點超過 30 天會退化成
    4 天一根，不是真日K，所以 SMC 專用這個獨立來源，不影響既有 RSI/SMA 的 close-only 管線）。
    回傳 [(day, open, high, low, close, volume), ...]。"""
    data = _get_json(OKX_CANDLES_URL, params={"instId": "BTC-USDT", "bar": "1D", "limit": limit})
    rows = data.get("data", [])
    out = []
    for row in rows:
        ts_ms, o, h, low, c, vol = int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
        day = time.strftime("%Y-%m-%d", time.gmtime(ts_ms / 1000))
        out.append((day, o, h, low, c, vol))
    out.reverse()  # OKX returns newest-first
    return out


def fetch_tw_stocks() -> dict:
    """TWSE 即時揭示 API（公開、免金鑰）。回傳 {股票代號: {name, price, chg_pct}}。"""
    ex_ch = "|".join(f"tse_{code}.tw" for code in TW_STOCKS)
    data = _get_json(
        TWSE_MIS_URL,
        params={"ex_ch": ex_ch},
        headers={"Referer": TWSE_INDEX_PAGE},
        warmup_url=TWSE_INDEX_PAGE,  # TWSE 需要先取一次首頁的 session cookie
    )
    out = {}
    for row in data.get("msgArray", []):
        code = row.get("c")
        if code not in TW_STOCKS:
            continue
        try:
            price = float(row["z"])
            prev = float(row["y"])
        except (KeyError, TypeError, ValueError):
            continue  # 未開盤等情況 z 會是 "-"，跳過這檔，不影響其他檔
        chg = (price / prev - 1.0) * 100.0 if prev else None
        out[code] = {"name": TW_STOCKS[code], "price": price, "chg_pct": chg}
    return out


def fetch_yahoo_quote(symbol: str) -> dict:
    data = _get_json(YAHOO_CHART_URL.format(symbol=symbol), headers={"User-Agent": "Mozilla/5.0"})
    meta = data["chart"]["result"][0]["meta"]
    price = float(meta["regularMarketPrice"])
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    prev = float(prev) if prev is not None else None
    chg = (price / prev - 1.0) * 100.0 if prev else None
    return {"price": price, "chg_pct": chg}


def _fetch_yahoo_group(symbols: dict) -> dict:
    out = {}
    for sym, name in symbols.items():
        try:
            out[sym] = {"name": name, **fetch_yahoo_quote(sym)}
        except Exception as exc:  # noqa: BLE001 — one bad symbol shouldn't drop the rest
            logger.warning("yahoo quote failed for %s: %s", sym, exc)
    return out


def fetch_us_stocks() -> dict:
    return _fetch_yahoo_group(US_STOCKS)


def fetch_commodities() -> dict:
    return _fetch_yahoo_group(COMMODITIES)
