"""市場情緒儀表板：市場平均 RSI、山寨季代理指標、恐懼貪婪指數。三個指標都刻意不额外
呼叫 AI（零 token 成本），前兩個甚至不用額外打 OKX API——直接重複利用 background.py
已經為了算訊號而抓過的 K 線，只有恐懼貪婪指數需要打一個額外的免費公開 API。

⚠️ 山寨季代理指標的誠實範圍說明：業界常見的「山寨季指數」（例如 blockchaincenter.net）
定義是「前 50 大幣種裡，過去 90 天漲幅贏過 BTC 的比例 > 75% 視為山寨季」。這裡沒有另外
接那個資料源，而是直接用本系統篩選出來、當下正在監控的商品清單，在**同一段 K 線窗口**
（跟訊號判斷用的同一批資料，config.CANDLE_BAR x CANDLE_LIMIT）跟 BTC 比報酬率——樣本
只有 TOP_N 檔（預設 6 檔）、窗口也遠短於 90 天，只能當「短線氛圍」的粗略參考，不是那個
業界指數的正式定義，畫面上會清楚標註這個差異。
"""
import logging

import httpx

logger = logging.getLogger("market_pulse")

FEAR_GREED_URL = "https://api.alternative.me/fng/"

ALTSEASON_THRESHOLD_PCT = 75.0  # 跟業界定義一致的門檻（>75% 跑贏 BTC 視為「山寨季」）


def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI，closes 需為舊到新排序。資料不足一個 period 回傳 None（沒有足夠資料
    硬算出來的數字會失真，不如老實回報「算不出來」）。"""
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def average_rsi(rsi_values: list[float]) -> dict:
    """把每檔監控商品各自算出的 RSI 平均起來，給一個「整體市場目前偏強還是偏弱」的參考。
    rsi_values 已經是每檔算好的 RSI（by caller 逐檔呼叫 compute_rsi 後收集），None 值
    （資料不足算不出來的商品）由呼叫端先過濾掉。"""
    if not rsi_values:
        return {"avg_rsi": None, "label": "資料不足", "sample_size": 0}

    avg = sum(rsi_values) / len(rsi_values)
    if avg >= 70:
        label = "超買"
    elif avg >= 55:
        label = "偏強"
    elif avg > 45:
        label = "中性"
    elif avg > 30:
        label = "偏弱"
    else:
        label = "超賣"
    return {"avg_rsi": round(avg, 1), "label": label, "sample_size": len(rsi_values)}


def compute_altseason_proxy(alt_pct_changes: list[float], btc_pct_change: float | None) -> dict:
    """alt_pct_changes：本輪監控商品（排除 BTC 本身）在同一窗口的報酬率(%) 列表。
    btc_pct_change：BTC 同一窗口的報酬率(%)，抓不到就回傳「資料不足」而不是亂猜。"""
    if btc_pct_change is None or not alt_pct_changes:
        return {"pct_outperforming_btc": None, "label": "資料不足", "sample_size": 0}

    outperforming = sum(1 for p in alt_pct_changes if p > btc_pct_change)
    pct = outperforming / len(alt_pct_changes) * 100.0
    label = "偏山寨季" if pct > ALTSEASON_THRESHOLD_PCT else ("偏比特幣季" if pct < 25.0 else "中性")
    return {
        "pct_outperforming_btc": round(pct, 1),
        "label": label,
        "sample_size": len(alt_pct_changes),
    }


def _describe_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return str(exc)


async def fetch_fear_greed_index(client: httpx.AsyncClient) -> dict | None:
    """免費公開 API（alternative.me），不需要金鑰。查不到就回傳 None，呼叫端優雅降級，
    不會讓整輪分析因為這個非必要的附加指標失敗而整個掛掉。"""
    try:
        resp = await client.get(FEAR_GREED_URL, params={"limit": 1})
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data", [])
        if not rows:
            return None
        row = rows[0]
        return {
            "value": int(row["value"]),
            "label": row.get("value_classification", ""),
        }
    except Exception as exc:  # noqa: BLE001 — 附加指標失敗不影響主要訊號，優雅降級
        logger.warning("fear_greed fetch failed: %s", _describe_error(exc))
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

    # 1) compute_rsi：資料不足回傳 None
    check("not enough data -> None", compute_rsi([1, 2, 3], period=14), None)

    # 2) compute_rsi：連續上漲 -> RSI = 100（avg_loss 為 0）
    rising = [100 + i for i in range(20)]
    check("monotonic rise -> RSI 100", compute_rsi(rising, period=14), 100.0)

    # 3) compute_rsi：連續下跌 -> RSI 接近 0
    falling = [100 - i for i in range(20)]
    check("monotonic fall -> RSI 0", compute_rsi(falling, period=14), 0.0)

    # 4) average_rsi：分類正確
    check("avg 80 -> 超買", average_rsi([80, 82])["label"], "超買")
    check("avg 60 -> 偏強", average_rsi([58, 62])["label"], "偏強")
    check("avg 50 -> 中性", average_rsi([48, 52])["label"], "中性")
    check("avg 35 -> 偏弱", average_rsi([33, 37])["label"], "偏弱")
    check("avg 20 -> 超賣", average_rsi([18, 22])["label"], "超賣")
    check("empty -> 資料不足", average_rsi([])["label"], "資料不足")

    # 5) compute_altseason_proxy
    check("no btc data -> 資料不足", compute_altseason_proxy([5.0, 3.0], None)["label"], "資料不足")
    r_alt = compute_altseason_proxy([10.0, 8.0, 9.0, 7.0], 2.0)  # 全部跑贏 BTC
    check("all outperform BTC -> 100%", r_alt["pct_outperforming_btc"], 100.0)
    check("100% outperform -> 偏山寨季", r_alt["label"], "偏山寨季")
    r_btc_season = compute_altseason_proxy([1.0, 0.5, -1.0, 0.0], 5.0)  # 全部輸給 BTC
    check("all underperform BTC -> 偏比特幣季", r_btc_season["label"], "偏比特幣季")

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
