"""OKX public REST 客戶端：商品篩選（ticker 掃描）+ K 線抓取。全部走公開端點，不需要
API 金鑰、不下單。純函式（screen_active_instruments）刻意跟網路請求分離，方便單元測試。
"""
import logging

import httpx

logger = logging.getLogger("okx_client")

OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"


async def fetch_swap_tickers(client: httpx.AsyncClient) -> list[dict]:
    """抓取 OKX 所有 USDT 本位永續合約（SWAP）的 24h ticker 快照。"""
    resp = await client.get(OKX_TICKERS_URL, params={"instType": "SWAP"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise ValueError(f"OKX tickers API error: {data.get('msg')}")
    return data.get("data", [])


def screen_active_instruments(
    tickers: list[dict],
    min_vol_usdt: float = 50_000_000.0,
    min_amplitude_pct: float = 3.0,
    top_n: int = 6,
    extra_keywords: tuple = (),
) -> list[dict]:
    """篩選具備流動性（24h 成交額）與波動度（24h 振幅）的合約，依振幅由高到低排序取前 top_n 檔。

    注意：OKX ticker 的 `volCcy24h` 欄位本身就是以計價貨幣（USDT 本位合約即 USDT）計算的
    24h 成交額，不需要再乘上最新價——用 `vol24h`（張數/幣數）乘價格會重複換算、算出錯誤數字。
    """
    candidates = []
    for t in tickers:
        inst_id = t.get("instId", "")
        is_crypto_perp = inst_id.endswith("-USDT-SWAP")
        is_extra = any(kw in inst_id for kw in extra_keywords)
        if not (is_crypto_perp or is_extra):
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
        if vol_usdt >= min_vol_usdt and amplitude_pct >= min_amplitude_pct:
            candidates.append({
                "instId": inst_id,
                "name": inst_id.replace("-SWAP", ""),
                "price": last,
                "vol_usdt": vol_usdt,
                "amplitude_pct": round(amplitude_pct, 2),
            })
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

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
