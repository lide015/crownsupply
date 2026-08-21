"""推薦強度榜：把每檔有訊號的商品，拆成四個維度算出 0-100 的強度分數，再依總分排出
做多/做空推薦榜——不是單一神秘數字，而是「這個分數是怎麼組成的」使用者一看就懂。

四個維度刻意只用系統本來就有、零額外成本的資料算出來，不生造假的「籌碼」「基本面」數字：
- 技術面：突破盒子的幅度 + 站上/跌破 20 EMA 的動能距離（strategy.py 的輸出）。
- 籌碼面：合約市場未平倉量（OI）變化幅度，見 oi_tracker.py——這是唯一比較貼近「籌碼」
  概念的公開數據，沒有基準值時給中性分數，不瞎猜。
- 情緒面：AI 新聞情緒判斷是否跟這個方向共振（news_client.py / brain.py 已經在用的資料）。
- 量能面：24h 成交額／振幅超過篩選門檻多少，反映這檔商品現在的活躍程度。

純函式、零額外網路呼叫、零額外 AI 成本——全部重複利用其他模組已經算好的資料。
"""

TECHNICAL_EMA_FULL_SCORE_PCT = 3.0  # 價格偏離 EMA 達到這個百分比，動能分數視為滿分
CHIPS_OI_FULL_SCORE_PCT = 20.0      # OI 變化達到這個百分比（正負），籌碼分數視為滿分/掛零
VOLUME_FULL_SCORE_RATIO = 2.0       # 成交額/振幅達門檻的這個倍數，量能分數視為滿分


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(value, hi))


def score_technical(signal_type: str, price: float, box_high: float, box_low: float, ema: float | None) -> float:
    """突破幅度佔盒子寬度的比例（0~1 記滿分)，加上偏離 EMA 的動能距離，各佔六四比重。"""
    box_width = box_high - box_low
    if box_width <= 0:
        return 50.0

    if signal_type == "long":
        margin = (price - box_high) / box_width
    else:
        margin = (box_low - price) / box_width
    margin_score = _clip(max(margin, 0.0) * 100.0)

    if ema and ema > 0:
        momentum_pct = abs(price - ema) / ema * 100.0
        momentum_score = _clip(momentum_pct / TECHNICAL_EMA_FULL_SCORE_PCT * 100.0)
    else:
        momentum_score = 50.0

    return round(margin_score * 0.6 + momentum_score * 0.4, 1)


def score_chips(oi_change_pct: float | None) -> float:
    """OI 沒有基準值（第一次看到這檔商品）時回傳中性 50 分，不代表看多也不代表看空。"""
    if oi_change_pct is None:
        return 50.0
    scaled = 50.0 + (oi_change_pct / CHIPS_OI_FULL_SCORE_PCT) * 50.0
    return round(_clip(scaled), 1)


def score_sentiment(signal_type: str, ai_sentiment: str) -> float:
    """跟 brain.fuse() 用同一套多空共振邏輯：方向一致給滿分、衝突給零分、中性/沒有 AI 給 50。"""
    bullish_word = "BULLISH"
    bearish_word = "BEARISH"
    if signal_type == "long":
        if ai_sentiment == bullish_word:
            return 100.0
        if ai_sentiment == bearish_word:
            return 0.0
        return 50.0
    if ai_sentiment == bearish_word:
        return 100.0
    if ai_sentiment == bullish_word:
        return 0.0
    return 50.0


def score_volume(vol_usdt: float, amplitude_pct: float, min_vol_usdt: float, min_amplitude_pct: float) -> float:
    """量能/振幅超過篩選門檻越多分數越高，剛好卡在門檻邊緣（本來就是篩選過的最低標準）給 0 分。"""
    vol_ratio = vol_usdt / min_vol_usdt if min_vol_usdt > 0 else 1.0
    amp_ratio = amplitude_pct / min_amplitude_pct if min_amplitude_pct > 0 else 1.0
    vol_score = _clip((vol_ratio - 1.0) / (VOLUME_FULL_SCORE_RATIO - 1.0) * 100.0)
    amp_score = _clip((amp_ratio - 1.0) / (VOLUME_FULL_SCORE_RATIO - 1.0) * 100.0)
    return round(vol_score * 0.5 + amp_score * 0.5, 1)


def score_signal(item: dict, min_vol_usdt: float, min_amplitude_pct: float) -> dict:
    """item 需含 signal_type("long"/"short")、price、box_high、box_low、ema、ai_sentiment、
    oi_change_pct、vol_usdt、amplitude_pct。回傳 {"dimensions": {...4 維度...}, "overall": float}。"""
    dims = {
        "technical": score_technical(item["signal_type"], item["price"], item["box_high"], item["box_low"], item.get("ema")),
        "chips": score_chips(item.get("oi_change_pct")),
        "sentiment": score_sentiment(item["signal_type"], item.get("ai_sentiment", "NEUTRAL")),
        "volume": score_volume(item["vol_usdt"], item["amplitude_pct"], min_vol_usdt, min_amplitude_pct),
    }
    overall = round(sum(dims.values()) / len(dims), 1)
    return {"dimensions": dims, "overall": overall}


def rank_signals(scored_items: list[dict], top_n: int = 5) -> dict:
    """scored_items：每個元素需含 "signal_type" 與 "overall"（score_signal 的輸出攤平進去）。
    回傳 {"long": [...依 overall 由高到低排序，最多 top_n 筆...], "short": [...同上...]}。"""
    longs = sorted((s for s in scored_items if s["signal_type"] == "long"), key=lambda s: s["overall"], reverse=True)
    shorts = sorted((s for s in scored_items if s["signal_type"] == "short"), key=lambda s: s["overall"], reverse=True)
    return {"long": longs[:top_n], "short": shorts[:top_n]}


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

    # 1) score_technical：突破幅度剛好等於盒子寬度 -> margin_score 滿分；EMA 距離達門檻 -> momentum 滿分
    r = score_technical("long", price=110.0, box_high=100.0, box_low=90.0, ema=106.79)  # 10/10=100%, |110-106.79|/106.79≈3%
    check("full breakout + full momentum -> ~100", r, 100.0)
    check("zero box width -> neutral 50", score_technical("long", 100, 100, 100, 100), 50.0)
    check("no ema -> momentum neutral", score_technical("long", 105, 100, 90, None) > 0, True)

    # 2) score_chips
    check("no oi baseline -> neutral 50", score_chips(None), 50.0)
    check("+20% OI -> full 100", score_chips(20.0), 100.0)
    check("-20% OI -> zero", score_chips(-20.0), 0.0)
    check("0% OI -> neutral 50", score_chips(0.0), 50.0)
    check("beyond +20% clipped at 100", score_chips(40.0), 100.0)

    # 3) score_sentiment：跟 brain.fuse 同樣的共振邏輯
    check("long + BULLISH -> 100", score_sentiment("long", "BULLISH"), 100.0)
    check("long + BEARISH -> 0", score_sentiment("long", "BEARISH"), 0.0)
    check("long + NEUTRAL -> 50", score_sentiment("long", "NEUTRAL"), 50.0)
    check("short + BEARISH -> 100", score_sentiment("short", "BEARISH"), 100.0)
    check("short + BULLISH -> 0", score_sentiment("short", "BULLISH"), 0.0)

    # 4) score_volume：剛好卡門檻 -> 0 分；2 倍門檻 -> 滿分
    check("exactly at threshold -> 0", score_volume(50_000_000, 3.0, 50_000_000, 3.0), 0.0)
    check("2x threshold -> 100", score_volume(100_000_000, 6.0, 50_000_000, 3.0), 100.0)

    # 5) score_signal 整合 + rank_signals 排序
    item_a = {"signal_type": "long", "price": 110.0, "box_high": 100.0, "box_low": 90.0, "ema": 106.79,
              "ai_sentiment": "BULLISH", "oi_change_pct": 20.0, "vol_usdt": 100_000_000, "amplitude_pct": 6.0,
              "instId": "A"}
    item_b = {"signal_type": "long", "price": 101.0, "box_high": 100.0, "box_low": 90.0, "ema": 100.5,
              "ai_sentiment": "NEUTRAL", "oi_change_pct": None, "vol_usdt": 50_000_000, "amplitude_pct": 3.0,
              "instId": "B"}
    scored_a = {**item_a, **score_signal(item_a, 50_000_000, 3.0)}
    scored_b = {**item_b, **score_signal(item_b, 50_000_000, 3.0)}
    check("stronger signal scores higher overall", scored_a["overall"] > scored_b["overall"], True)

    ranked = rank_signals([scored_a, scored_b], top_n=5)
    check("ranked long sorted desc", [s["instId"] for s in ranked["long"]], ["A", "B"])
    check("no short signals -> empty list", ranked["short"], [])

    top1 = rank_signals([scored_a, scored_b], top_n=1)
    check("top_n truncates", len(top1["long"]), 1)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
