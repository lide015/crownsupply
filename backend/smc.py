"""SMC（Smart Money Concept）技術分析 — 純 Python，零 AI 呼叫。
基於 OHLC 日K判斷市場結構（bullish/bearish/ranging）、BOS（順勢突破前高/前低）、
CHoCH（逆勢跌破/漲破，結構可能反轉）、FVG（公允價值缺口）。
資料來源見 fetcher.fetch_ohlc_okx → db.kline_ohlc_daily。
"""


def swing_points(highs, lows, lookback=2):
    """回傳依索引排序的 [(index, 'high'|'low', price), ...]。
    pivot 定義：比左右各 lookback 根的同類值都高（或都低）的局部極值。"""
    n = len(highs)
    swings = []
    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback:i + lookback + 1]
        if highs[i] == max(window_h) and window_h.count(highs[i]) == 1:
            swings.append((i, "high", highs[i]))
        window_l = lows[i - lookback:i + lookback + 1]
        if lows[i] == min(window_l) and window_l.count(lows[i]) == 1:
            swings.append((i, "low", lows[i]))
    swings.sort(key=lambda s: s[0])
    return swings


def market_structure(swings):
    """依最近兩個 swing high 與兩個 swing low 判斷多空排列。
    higher-high + higher-low = bullish；lower-high + lower-low = bearish；其餘 ranging。"""
    highs = [s for s in swings if s[1] == "high"]
    lows = [s for s in swings if s[1] == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return "ranging"
    hh = highs[-1][2] > highs[-2][2]
    hl = lows[-1][2] > lows[-2][2]
    lh = highs[-1][2] < highs[-2][2]
    ll = lows[-1][2] < lows[-2][2]
    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "ranging"


def detect_bos_choch(closes, swings):
    """最新收盤價對照最近一個反向 swing：順著現有結構方向突破＝BOS，
    逆著現有結構方向突破＝CHoCH（結構轉變，反轉警訊）。"""
    if not swings or not closes:
        return None
    last_close = closes[-1]
    last_high = next((s for s in reversed(swings) if s[1] == "high"), None)
    last_low = next((s for s in reversed(swings) if s[1] == "low"), None)
    structure = market_structure(swings)

    if last_high and last_close > last_high[2]:
        event_type = "BOS" if structure == "bullish" else "CHoCH"
        return {"type": event_type, "direction": "bullish", "level": last_high[2]}
    if last_low and last_close < last_low[2]:
        event_type = "BOS" if structure == "bearish" else "CHoCH"
        return {"type": event_type, "direction": "bearish", "level": last_low[2]}
    return None


def fair_value_gaps(highs, lows, days, lookback=30):
    """三根一組的公允價值缺口：第1根高點與第3根低點之間（或反向）出現價格真空，
    只回傳最近 lookback 根內的缺口。"""
    n = len(highs)
    start = max(2, n - lookback)
    fvgs = []
    for i in range(start, n):
        if highs[i - 2] < lows[i]:
            fvgs.append({"day": days[i], "direction": "bullish", "bottom": highs[i - 2], "top": lows[i]})
        elif lows[i - 2] > highs[i]:
            fvgs.append({"day": days[i], "direction": "bearish", "bottom": highs[i], "top": lows[i - 2]})
    return fvgs


def compute_smc(rows):
    """rows: [(day, open, high, low, close), ...]，依日期升冪排序（最舊在前）。"""
    if len(rows) < 10:
        return {"structure": "insufficient_data", "last_event": None, "fvgs": []}
    days = [r[0] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    closes = [r[4] for r in rows]

    swings = swing_points(highs, lows, lookback=2)
    structure = market_structure(swings)
    event = detect_bos_choch(closes, swings)
    fvgs = fair_value_gaps(highs, lows, days, lookback=30)

    return {"structure": structure, "last_event": event, "fvgs": fvgs[-5:]}


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

    # 1) swing_points + market_structure — 手工構造的漲勢 zigzag（lookback=1）
    highs = [10, 13, 11, 16, 12, 19, 14]
    lows = [8, 11, 9, 14, 10, 17, 12]
    swings = swing_points(highs, lows, lookback=1)
    check(
        "swing_points bullish zigzag",
        swings,
        [(1, "high", 13), (2, "low", 9), (3, "high", 16), (4, "low", 10), (5, "high", 19)],
    )
    check("market_structure bullish", market_structure(swings), "bullish")

    # 2) BOS：順著既有多頭結構，收盤突破前高
    check(
        "detect_bos_choch BOS (break above prior high in bullish structure)",
        detect_bos_choch(closes=[10, 13, 11, 16, 12, 19, 14, 20], swings=swings),
        {"type": "BOS", "direction": "bullish", "level": 19},
    )

    # 3) CHoCH：多頭結構中跌破前低，結構可能反轉
    check(
        "detect_bos_choch CHoCH (break below prior low in bullish structure)",
        detect_bos_choch(closes=[10, 13, 11, 16, 12, 19, 14, 8], swings=swings),
        {"type": "CHoCH", "direction": "bearish", "level": 10},
    )

    # 4) FVG：單一 3 根缺口
    fvg_days = ["d0", "d1", "d2", "d3", "d4"]
    fvg_highs = [10, 11, 9, 20, 15]
    fvg_lows = [8, 9, 7, 18, 8]
    check(
        "fair_value_gaps single bullish gap",
        fair_value_gaps(fvg_highs, fvg_lows, fvg_days, lookback=30),
        [{"day": "d3", "direction": "bullish", "bottom": 11, "top": 18}],
    )

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
