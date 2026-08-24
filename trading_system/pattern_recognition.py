"""型態辨識：從已收盤 K 線（純 OHLC，跟 strategy.py 同一種輸入格式）偵測幾種常見的
技術分析圖形型態（突破前高、跳空缺口、均線黏合發散、W底雙重底、三角收斂、回踩黃金
分割位），零額外 AI/API 成本，純數學計算。

⚠️ 誠實範圍說明：這套偵測邏輯的靈感來源是坊間流傳的「25種主升浪啟動形態」型態圖鑑
（Telegram 頻道教學圖卡，非嚴謹學術文獻，圖卡本身也註明「僅供參考，不做為任何投資
建議」），這裡只取「型態名稱代表哪個廣為人知的技術分析概念」當方向線索，偵測邏輯
是重新設計、可回測驗證的量化定義，不是照抄圖卡的圖形判讀。

刻意只實作 6 種、不是全部 25 種：
- 「突破前高／跳空缺口／均線黏合發散／W底雙重底／三角收斂／回踩黃金分割位」這 6 種
  能用單純的 OHLC 數字給出明確、可回測的量化定義。
- 「杯柄突破／圓弧底起漲／頭肩底突破」這幾種需要判斷「形狀是否夠圓滑／夠對稱」，
  用簡單規則硬做容易產生大量假陽性（隨便一段震盪都能牽強解釋成杯柄或頭肩），
  比不做還誤導，刻意不實作。
- 「漲停突破」是台股/中國A股特有的每日漲跌幅限制機制，OKX 永續合約沒有這個概念，
  不適用。
- 「突破籌碼密集區」需要成交量在各價位的分布（volume profile），本系統的 K 線資料
  只有每根的總成交量、沒有價位分布明細，資料精細度不足以可靠判斷，不實作。
- 「旗形整理突破／楔形末端突破」跟三角收斂本質上是同一種「趨勢線收斂突破」的變體，
  避免疊床架屋的重複偵測器。

**這套偵測結果純粹是資訊揭露，不參與 brain.fuse() 的訊號融合**，不影響任何既有的
進場/停損/停利判斷——見 background.py 呼叫端說明。跟 oi_tracker.py／funding_rate.py
同樣的設計哲學：偵測到的型態只是「附加的技術面脈絡」，不是額外的訊號來源。

純函式、零網路呼叫，方便單元測試——跟 strategy.py 同樣的設計。
"""
import pandas as pd


def detect_break_previous_high(candles: list[dict], lookback: int = 20) -> dict | None:
    """突破前高：最近一根收盤價，突破前面 lookback 根（不含當前這根）的最高點。
    跟 strategy.py 既有的盤整盒子突破概念相近，差別是這裡看的是更長回看窗的絕對高點，
    不受盤整盒子固定寬度限制，適合抓「久攻不下的壓力位」被突破的情境。"""
    if len(candles) < lookback + 1:
        return None
    window = candles[-(lookback + 1):-1]
    prev_high = max(c["h"] for c in window)
    current = candles[-1]
    return {
        "pattern": "break_previous_high",
        "detected": current["c"] > prev_high,
        "prev_high": round(prev_high, 8),
    }


def detect_gap_breakout(candles: list[dict], min_gap_pct: float = 0.5) -> dict | None:
    """跳空缺口突破：當前這根的最低點，高於前一根的最高點（乾淨跳空、沒有價格重疊），
    且跳空幅度達到 min_gap_pct% 以上——太小的跳空可能只是正常的開高走勢，不算有意義
    的缺口。"""
    if len(candles) < 2:
        return None
    prev = candles[-2]
    current = candles[-1]
    if prev["h"] <= 0:
        return None
    gap_pct = (current["l"] - prev["h"]) / prev["h"] * 100.0
    return {
        "pattern": "gap_breakout",
        "detected": gap_pct >= min_gap_pct,
        "gap_pct": round(gap_pct, 3),
    }


def _sma_series(closes: list[float], period: int) -> list[float | None]:
    """簡單移動平均，回傳跟輸入等長的序列，資料不足的位置是 None（不是 NaN，
    呼叫端不用額外處理 pandas 的 NaN 判斷）。"""
    series = pd.Series(closes).rolling(window=period).mean()
    return [None if pd.isna(v) else float(v) for v in series]


def detect_ma_convergence_divergence(
    candles: list[dict],
    ma_periods: tuple = (5, 10, 20),
    squeeze_pct: float = 1.0,
    expand_pct: float = 3.0,
    squeeze_lookback: int = 10,
) -> dict | None:
    """均線黏合發散：過去 squeeze_lookback 根（不含當前這根）裡，曾經出現一段所有均線
    彼此距離都在 squeeze_pct% 以內的「黏合」狀態；當前這根，均線已經發散到彼此距離
    超過 expand_pct%，呈多頭排列（短天期均線 >= 長天期均線）、收盤價站上全部均線。"""
    periods_sorted = sorted(ma_periods)
    min_len = max(periods_sorted) + squeeze_lookback
    if len(candles) < min_len:
        return None
    closes = [c["c"] for c in candles]
    ma_values = {p: _sma_series(closes, p) for p in periods_sorted}

    def spread_pct_at(idx: int) -> float | None:
        vals = [ma_values[p][idx] for p in periods_sorted]
        if any(v is None for v in vals):
            return None
        lo, hi = min(vals), max(vals)
        if lo <= 0:
            return None
        return (hi - lo) / lo * 100.0

    had_squeeze = False
    for idx in range(len(candles) - squeeze_lookback - 1, len(candles) - 1):
        if idx < 0:
            continue
        sp = spread_pct_at(idx)
        if sp is not None and sp <= squeeze_pct:
            had_squeeze = True
            break

    current_idx = len(candles) - 1
    current_vals = [ma_values[p][current_idx] for p in periods_sorted]
    current_spread = spread_pct_at(current_idx)
    current_price = closes[current_idx]

    if any(v is None for v in current_vals):
        return {"pattern": "ma_convergence_divergence", "detected": False}

    bullish_aligned = all(current_vals[i] >= current_vals[i + 1] for i in range(len(current_vals) - 1))
    price_above_all = all(current_price > v for v in current_vals)
    diverged = current_spread is not None and current_spread >= expand_pct

    detected = had_squeeze and diverged and bullish_aligned and price_above_all
    return {
        "pattern": "ma_convergence_divergence",
        "detected": detected,
        "current_spread_pct": round(current_spread, 3) if current_spread is not None else None,
    }


def _find_local_minima(candles: list[dict], order: int = 3) -> list[tuple]:
    """回傳 [(index, low_price), ...]——該根K線的低點比左右各 order 根的低點都低
    （局部低點/波谷），用來抓可能的雙重底轉折點。"""
    lows = [c["l"] for c in candles]
    minima = []
    for i in range(order, len(lows) - order):
        left = lows[i - order:i]
        right = lows[i + 1:i + order + 1]
        if lows[i] < min(left) and lows[i] < min(right):
            minima.append((i, lows[i]))
    return minima


def detect_double_bottom(
    candles: list[dict], lookback: int = 40, similarity_tolerance_pct: float = 2.0, min_trough_separation: int = 5,
) -> dict | None:
    """W底／雙重底：回看窗裡找到兩個價位相近（similarity_tolerance_pct% 以內）、
    彼此有足夠時間間隔（至少 min_trough_separation 根K線）的局部低點，兩個低點之間
    的最高點視為「頸線」；當前這根收盤價突破頸線，視為雙重底確立。"""
    if len(candles) < lookback + 1:
        return None
    window = candles[-(lookback + 1):-1]
    current = candles[-1]
    minima = _find_local_minima(window, order=3)
    if len(minima) < 2:
        return {"pattern": "double_bottom", "detected": False}

    candidates = []
    for i in range(len(minima)):
        for j in range(i + 1, len(minima)):
            idx1, low1 = minima[i]
            idx2, low2 = minima[j]
            if idx2 - idx1 < min_trough_separation:
                continue
            avg = (low1 + low2) / 2.0
            if avg <= 0:
                continue
            diff_pct = abs(low1 - low2) / avg * 100.0
            if diff_pct <= similarity_tolerance_pct:
                candidates.append((idx1, low1, idx2, low2))
    if not candidates:
        return {"pattern": "double_bottom", "detected": False}

    # 取第二個低點（idx2）最接近現在的那一組——最貼近「剛完成的雙重底」情境，
    # 而不是回看窗裡任意一段早已過時的雙重底形狀。
    idx1, low1, idx2, low2 = max(candidates, key=lambda c: c[2])
    neckline = max(c["h"] for c in window[idx1:idx2 + 1])
    return {
        "pattern": "double_bottom",
        "detected": current["c"] > neckline,
        "neckline": round(neckline, 8),
    }


def _linreg_slope_intercept(xs: list[float], ys: list[float]) -> tuple:
    """最小平方法線性回歸，回傳 (斜率, 截距)。資料點不足或 x 完全沒有變化時回傳
    (None, None)。"""
    n = len(xs)
    if n < 2:
        return None, None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None, None
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


def detect_triangle_convergence(candles: list[dict], lookback: int = 30, min_convergence_ratio: float = 0.3) -> dict | None:
    """三角收斂突破：對回看窗（不含當前這根）的高點、低點各自做線性回歸，高點趨勢線
    要向下傾斜、低點趨勢線要向上傾斜（真正在收斂，不是隨便一段震盪），且收斂終點的
    高低差要比起點窄至少 min_convergence_ratio（預設收窄 3 成以上）；當前這根收盤價
    突破外推到「現在」位置的上緣趨勢線，視為三角收斂突破。"""
    if len(candles) < lookback + 1:
        return None
    window = candles[-(lookback + 1):-1]
    current = candles[-1]
    xs = list(range(len(window)))
    highs = [c["h"] for c in window]
    lows = [c["l"] for c in window]
    high_slope, high_intercept = _linreg_slope_intercept(xs, highs)
    low_slope, low_intercept = _linreg_slope_intercept(xs, lows)
    if high_slope is None or low_slope is None:
        return {"pattern": "triangle_convergence", "detected": False}

    converging = high_slope < 0 and low_slope > 0
    start_range = high_intercept - low_intercept
    end_x = len(window) - 1
    end_range = (high_slope * end_x + high_intercept) - (low_slope * end_x + low_intercept)
    narrowing = start_range > 0 and end_range > 0 and (end_range / start_range) <= (1 - min_convergence_ratio)

    upper_line_now = high_slope * len(window) + high_intercept  # 外推到「當前這根」的位置
    breakout = current["c"] > upper_line_now

    return {
        "pattern": "triangle_convergence",
        "detected": bool(converging and narrowing and breakout),
        "upper_line_now": round(upper_line_now, 8),
    }


def detect_fib_pullback_hold(
    candles: list[dict], swing_lookback: int = 60, fib_levels: tuple = (0.382, 0.5, 0.618),
    tolerance_pct: float = 1.5, recent_window: int = 5,
) -> dict | None:
    """回踩黃金分割位：回看窗（不含當前這根）裡先確認一段「低點在前、高點在後」的
    上升段（不是隨便抓區間最高最低就套費波那契），算出幾個回撤比例的參考價位；
    如果最近 recent_window 根裡有低點落在任一參考價位附近（tolerance_pct% 以內），
    取其中離「當前這根收盤價」最近的那一層（平滑的回撤路徑常常沿路碰過好幾層，
    只有離現在最近的那層才是實際在防守的價位，不是路過的淺層），且當前這根收紅
    （收盤價 > 開盤價）並站上那個參考價位，視為「回踩到位、止穩」。"""
    if len(candles) < swing_lookback + 1:
        return None
    window = candles[-(swing_lookback + 1):-1]
    current = candles[-1]

    low_idx = min(range(len(window)), key=lambda i: window[i]["l"])
    high_idx = max(range(len(window)), key=lambda i: window[i]["h"])
    if high_idx <= low_idx:
        # 高點沒有出現在低點「之後」，代表回看窗裡看不到一段明確的上升段可以回撤，
        # 不是「先漲一段、現在拉回」的情境，套費波那契沒有意義。
        return {"pattern": "fib_pullback_hold", "detected": False}

    swing_low = window[low_idx]["l"]
    swing_high = window[high_idx]["h"]
    move = swing_high - swing_low
    if move <= 0:
        return {"pattern": "fib_pullback_hold", "detected": False}

    fib_prices = {lvl: swing_high - move * lvl for lvl in fib_levels}

    recent = window[-recent_window:] if recent_window <= len(window) else window
    touched = [
        (lvl, price) for lvl, price in fib_prices.items()
        if price > 0 and any(abs(c["l"] - price) / price * 100.0 <= tolerance_pct for c in recent)
    ]
    if not touched:
        return {"pattern": "fib_pullback_hold", "detected": False}

    # 平滑的回撤走勢常常沿路碰過好幾個費波那契價位（例如先穿過 38.2%、繼續拉回到
    # 61.8% 才真正止穩）——不能取「由淺到深第一個碰到的」，那只是路過、不是現在真正
    # 在防守的價位。改取跟「當前這根收盤價」最接近的已觸價位，那才是現在實際止穩的那一層。
    touched_level, touched_price = min(touched, key=lambda item: abs(current["c"] - item[1]))

    holding = current["c"] > current["o"] and current["c"] > touched_price
    return {
        "pattern": "fib_pullback_hold",
        "detected": bool(holding),
        "fib_level": touched_level,
        "fib_price": round(touched_price, 8),
    }


PATTERN_DETECTORS = (
    ("break_previous_high", "突破前高", detect_break_previous_high),
    ("gap_breakout", "跳空缺口突破", detect_gap_breakout),
    ("ma_convergence_divergence", "均線黏合發散", detect_ma_convergence_divergence),
    ("double_bottom", "W底雙重底", detect_double_bottom),
    ("triangle_convergence", "三角收斂突破", detect_triangle_convergence),
    ("fib_pullback_hold", "回踩黃金分割位", detect_fib_pullback_hold),
)


def detect_patterns(candles: list[dict]) -> list[dict]:
    """跑過全部 6 種型態偵測器，回傳「當前這根K線」偵測到的型態清單（[]、一種、或
    同時好幾種都有可能）。純資訊揭露，不參與 brain.fuse() 的訊號融合，不影響任何
    既有的進場/停損/停利判斷——見模組說明。任何一個偵測器丟例外（理論上不會，但
    防禦性處理）或資料不足回傳 None，直接跳過那一種，不影響其他偵測器。"""
    results = []
    for key, label, fn in PATTERN_DETECTORS:
        try:
            r = fn(candles)
        except Exception:  # noqa: BLE001 — 單一型態偵測失敗不該讓整輪分析掛掉
            r = None
        if r and r.get("detected"):
            results.append({"key": key, "label": label})
    return results


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

    def flat(n, price=100.0):
        return [{"o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "vol": 1000.0} for _ in range(n)]

    # ---------- detect_break_previous_high ----------
    check("break_prev_high: insufficient data -> None", detect_break_previous_high(flat(5), lookback=20), None)

    flat_hist = flat(20, price=100.0)
    breakout_candle = [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 1000.0}]
    r = detect_break_previous_high(flat_hist + breakout_candle, lookback=20)
    check("break_prev_high: clears prior range high -> detected", r["detected"], True)
    check("break_prev_high: prev_high matches window max", r["prev_high"], 100.5)

    no_break_candle = [{"o": 100.0, "h": 100.4, "l": 99.8, "c": 100.2, "vol": 1000.0}]
    r2 = detect_break_previous_high(flat_hist + no_break_candle, lookback=20)
    check("break_prev_high: stays inside prior range -> not detected", r2["detected"], False)

    # ---------- detect_gap_breakout ----------
    check("gap_breakout: insufficient data -> None", detect_gap_breakout(flat(1)), None)
    gapped = [{"o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "vol": 1000.0},
              {"o": 103.0, "h": 104.0, "l": 102.0, "c": 103.5, "vol": 1000.0}]  # low(102) > prev high(101) -> ~1% gap
    r3 = detect_gap_breakout(gapped, min_gap_pct=0.5)
    check("gap_breakout: clean gap above threshold -> detected", r3["detected"], True)

    overlapping = [{"o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "vol": 1000.0},
                   {"o": 100.6, "h": 101.2, "l": 100.2, "c": 101.0, "vol": 1000.0}]  # low(100.2) < prev high(101) -> overlap
    r4 = detect_gap_breakout(overlapping, min_gap_pct=0.5)
    check("gap_breakout: overlapping candles -> not detected", r4["detected"], False)

    # ---------- detect_ma_convergence_divergence ----------
    check("ma_conv_div: insufficient data -> None",
          detect_ma_convergence_divergence(flat(10), ma_periods=(5, 10, 20), squeeze_lookback=10), None)

    # 建構：先一段所有均線都貼在一起的盤整（黏合），接著一段急拉讓均線發散、價格站上所有均線。
    squeeze_part = flat(30, price=100.0)  # 30 根平盤 -> MA5/MA10/MA20 幾乎重合
    surge_part = [{"o": 100.0 + i * 0.8, "h": 100.5 + i * 0.8, "l": 99.8 + i * 0.8, "c": 100.4 + i * 0.8, "vol": 1000.0} for i in range(1, 9)]
    converge_diverge_candles = squeeze_part + surge_part
    r5 = detect_ma_convergence_divergence(converge_diverge_candles, ma_periods=(5, 10, 20), squeeze_pct=1.0, expand_pct=3.0, squeeze_lookback=10)
    check("ma_conv_div: squeeze then bullish fan-out -> detected", r5["detected"], True)

    # 純平盤走完，從未發散 -> 不觸發
    r6 = detect_ma_convergence_divergence(flat(40), ma_periods=(5, 10, 20), squeeze_pct=1.0, expand_pct=3.0, squeeze_lookback=10)
    check("ma_conv_div: stays flat, never diverges -> not detected", r6["detected"], False)

    # ---------- detect_double_bottom ----------
    check("double_bottom: insufficient data -> None", detect_double_bottom(flat(10), lookback=40), None)

    def make_double_bottom():
        # 下跌到 95 -> 反彈到 100（頸線）-> 再跌回 95.2（第二個低點，跟第一個低點很接近）-> 當前這根突破頸線 100
        candles = []
        # 第一段下跌 + 觸底 (idx 0-9)
        for i in range(10):
            price = 105.0 - i * 1.0
            candles.append({"o": price + 0.3, "h": price + 0.6, "l": price - 0.3, "c": price, "vol": 1000.0})
        # 反彈到頸線 100 (idx 10-15)
        for i in range(6):
            price = 95.0 + i * 1.0
            candles.append({"o": price - 0.3, "h": price + 0.3, "l": price - 0.6, "c": price, "vol": 1000.0})
        # 第二次下跌回接近 95 (idx 16-21)
        for i in range(6):
            price = 100.0 - i * 0.8
            candles.append({"o": price + 0.3, "h": price + 0.6, "l": price - 0.3, "c": price, "vol": 1000.0})
        # 從第二低點反彈 (idx 22-26)，最後一根在 window 內，尚未突破頸線
        for i in range(5):
            price = 95.2 + i * 0.8
            candles.append({"o": price - 0.3, "h": price + 0.3, "l": price - 0.6, "c": price, "vol": 1000.0})
        return candles

    db_window = make_double_bottom()
    padding = flat(40 - len(db_window) + 1, price=db_window[0]["o"])  # 補到剛好 lookback+1 根，用第一根的價位墊在最前面避免製造額外轉折
    breakout_over_neckline = [{"o": 100.0, "h": 102.0, "l": 99.5, "c": 101.5, "vol": 1000.0}]
    full = padding + db_window + breakout_over_neckline
    r7 = detect_double_bottom(full, lookback=40, similarity_tolerance_pct=2.0)
    check("double_bottom: two similar troughs + neckline breakout -> detected", r7["detected"], True)

    r8 = detect_double_bottom(flat(41), lookback=40, similarity_tolerance_pct=2.0)
    check("double_bottom: flat history, no troughs -> not detected", r8["detected"], False)

    # ---------- detect_triangle_convergence ----------
    check("triangle: insufficient data -> None", detect_triangle_convergence(flat(10), lookback=30), None)

    def make_triangle(n=30):
        candles = []
        for i in range(n):
            high = 110.0 - i * 0.3
            low = 90.0 + i * 0.3
            mid = (high + low) / 2
            candles.append({"o": mid, "h": high, "l": low, "c": mid, "vol": 1000.0})
        return candles

    tri_window = make_triangle(30)
    tri_breakout = [{"o": 101.0, "h": 104.0, "l": 100.5, "c": 103.5, "vol": 1000.0}]
    r9 = detect_triangle_convergence(tri_window + tri_breakout, lookback=30)
    check("triangle: converging highs/lows + breakout above upper line -> detected", r9["detected"], True)

    r10 = detect_triangle_convergence(flat(31), lookback=30)
    check("triangle: flat history (no convergence) -> not detected", r10["detected"], False)

    # ---------- detect_fib_pullback_hold ----------
    check("fib_pullback: insufficient data -> None", detect_fib_pullback_hold(flat(10), swing_lookback=60), None)

    def make_fib_setup():
        # 低點 100 (idx 0) 漲到高點 200 (idx 30)，move=100，61.8% 回撤價位＝200-100*0.618＝138.2。
        # 拉回段最後探到接近 138.2，當前這根收紅並站上該價位。
        candles = [{"o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "vol": 1000.0}]  # idx 0: swing low
        for i in range(1, 30):
            price = 100.0 + i * (100.0 / 30)
            candles.append({"o": price - 0.5, "h": price + 0.5, "l": price - 1.0, "c": price, "vol": 1000.0})
        candles.append({"o": 199.0, "h": 200.5, "l": 198.5, "c": 200.0, "vol": 1000.0})  # idx 30: swing high 200
        # 回撤段：從 200 拉回到 61.8% 價位（138.2）附近
        for i in range(1, 6):
            price = 200.0 - i * 12.36  # i=5 -> 200-61.8=138.2
            candles.append({"o": price + 1.0, "h": price + 1.5, "l": price - 1.0, "c": price - 0.5, "vol": 1000.0})
        return candles

    fib_window = make_fib_setup()
    fib_confirm_candle = [{"o": 138.0, "h": 142.0, "l": 137.5, "c": 141.0, "vol": 1000.0}]  # 收紅、站上 61.8% 價位（138.2）
    # swing_lookback=60 需要「回看窗（不含當前這根）」剛好 60 根——前面補一段跟 swing low
    # 同價位的平盤墊資料，湊滿長度但不製造額外的轉折干擾 low_idx/high_idx 的判斷。
    fib_padding = flat(61 - len(fib_window) - 1, price=fib_window[0]["o"])
    full_fib = fib_padding + fib_window + fib_confirm_candle
    r11 = detect_fib_pullback_hold(full_fib, swing_lookback=60, tolerance_pct=1.5)
    check("fib_pullback: pullback touches 61.8% then holds -> detected", r11["detected"], True)
    # 這段平滑回撤的路徑沿路也貼近了 38.2%（161.8）——踩中一個真實 bug：早期版本
    # 用「由淺到深第一個碰到的」邏輯，這裡會誤報 0.382（只是路過的淺層），不是現在
    # 實際止穩的 0.618，修正後改取離「當前這根收盤價」最近的已觸價位。
    check("fib_pullback: identifies the 0.618 level (closest to current close), not 0.382 (a shallower level merely passed through)",
          r11["fib_level"], 0.618)

    r12 = detect_fib_pullback_hold(flat(61), swing_lookback=60)
    check("fib_pullback: flat history, no swing -> not detected", r12["detected"], False)

    # ---------- detect_patterns（聚合器） ----------
    check("detect_patterns: flat history detects nothing", detect_patterns(flat(70)), [])

    aggregated = detect_patterns(flat_hist + breakout_candle)
    check("detect_patterns: break_previous_high shows up in aggregated results",
          any(p["key"] == "break_previous_high" for p in aggregated), True)

    # 單一偵測器丟例外不該讓整個聚合器掛掉——用資料不足以外的方式製造例外不容易，
    # 這裡改測「資料不足時聚合器本身也不會掛」，涵蓋同一種防禦性設計的精神。
    check("detect_patterns: very short candle list doesn't crash", detect_patterns(flat(2)), [])

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
