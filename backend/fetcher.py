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


def _get_json(url: str, params: dict | None = None) -> dict:
    backoff = 1.0
    last_exc: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
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
