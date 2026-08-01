"""規則式交易計畫合成器 — 零 AI 呼叫。整合 indicators.py（RSI/均線乖離/DMI/布林通道）與
smc.py（市場結構/BOS·CHoCH/FVG）產生結構化計畫：方向、評分、進場/停損/停利、判斷依據。
純規則運算，SL/TP 與勝率為簡化啟發式估算，不是統計回測結果，僅供參考、非投資建議。
"""

from . import indicators


def _build_reasons(structure, rsi14, ma_bias_pct, dmi_result, bb, price, event):
    reasons = [f"市場結構：{structure}"]
    if rsi14 is not None:
        tag = "（超買）" if rsi14 >= 70 else "（超賣）" if rsi14 <= 30 else ""
        reasons.append(f"RSI14={rsi14:.1f}{tag}")
    if ma_bias_pct is not None:
        reasons.append(f"均線乖離{ma_bias_pct:+.2f}%")
    if dmi_result is not None:
        trend_tag = "多頭動能強" if dmi_result["plus_di"] > dmi_result["minus_di"] else "空頭動能強"
        reasons.append(f"+DI {dmi_result['plus_di']:.1f} / -DI {dmi_result['minus_di']:.1f}（{trend_tag}）")
    if bb is not None and price is not None:
        if price > bb["upper"]:
            pos = "高於布林上軌"
        elif price < bb["lower"]:
            pos = "低於布林下軌"
        else:
            pos = "布林中軌附近" if abs(price - bb["mid"]) < (bb["upper"] - bb["mid"]) * 0.3 else "布林通道內"
        reasons.append(pos)
    if event:
        reasons.append(f"最新{event['type']}：{event['direction']}突破 {event['level']}")
    return reasons


def _sl_tp(price, bias, event, bb):
    """SL 放在關鍵結構價（最近 BOS/CHoCH level，或缺乏時用布林通道）外側一點緩衝；
    TP1 = 1:1 風報比、TP2 = 1:1.5，簡化估算，不是回測結果。"""
    key_level = event["level"] if event else None
    if key_level is None and bb is not None:
        key_level = bb["lower"] if bias == "bullish" else bb["upper"]
    if key_level is None:
        return None

    buffer = abs(price - key_level) * 0.1 or price * 0.005
    if bias == "bullish":
        sl = min(key_level - buffer, price * 0.98)
        risk = price - sl
        return {"sl": sl, "tp1": price + risk, "tp2": price + risk * 1.5, "rr1": 1.0, "rr2": 1.5}
    else:
        sl = max(key_level + buffer, price * 1.02)
        risk = sl - price
        return {"sl": sl, "tp1": price - risk, "tp2": price - risk * 1.5, "rr1": 1.0, "rr2": 1.5}


def build_trade_plan(ohlc_rows, indicators_result, smc_result):
    """ohlc_rows: [(day, open, high, low, close), ...] 升冪；indicators_result:
    indicators.compute_indicators() 輸出；smc_result: smc.compute_smc() 輸出。"""
    if not ohlc_rows or not indicators_result or not smc_result or smc_result.get("structure") == "insufficient_data":
        return {"available": False}

    closes = [r[4] for r in ohlc_rows]
    highs = [r[2] for r in ohlc_rows]
    lows = [r[3] for r in ohlc_rows]
    price = closes[-1]

    structure = smc_result["structure"]
    rsi14 = indicators_result.get("rsi14")
    ma_bias_pct = indicators_result.get("ma_bias_pct")
    event = smc_result.get("last_event")
    dmi_result = indicators.dmi(highs, lows, closes)
    bb = indicators.bollinger_bands(closes)

    bull_votes = sum([
        structure == "bullish",
        rsi14 is not None and rsi14 >= 50,
        ma_bias_pct is not None and ma_bias_pct >= 0,
        dmi_result is not None and dmi_result["plus_di"] > dmi_result["minus_di"],
    ])
    bear_votes = sum([
        structure == "bearish",
        rsi14 is not None and rsi14 < 50,
        ma_bias_pct is not None and ma_bias_pct < 0,
        dmi_result is not None and dmi_result["plus_di"] <= dmi_result["minus_di"],
    ])

    if bull_votes > bear_votes:
        bias, win_rate_pct = "bullish", 50 + bull_votes * 8
    elif bear_votes > bull_votes:
        bias, win_rate_pct = "bearish", 50 + bear_votes * 8
    else:
        bias, win_rate_pct = "neutral", 50

    plan_score = 50
    if event and event["direction"] == bias:
        plan_score += 20
    if rsi14 is not None and (rsi14 >= 70 or rsi14 <= 30):
        plan_score += 10
    if dmi_result is not None and dmi_result["adx"] >= 25:
        plan_score += 10  # ADX>=25 常規視為「有明確趨勢」
    plan_score = min(plan_score, 100)

    levels = _sl_tp(price, bias, event, bb) if bias != "neutral" else None

    return {
        "available": True,
        "price": price,
        "market_structure": structure,
        "bias": bias,
        "win_rate_pct": min(win_rate_pct, 90),
        "plan_score": plan_score,
        "levels": levels,
        "key_level": event["level"] if event else None,
        "last_smc_event": event,
        "dmi": dmi_result,
        "bollinger": bb,
        "reasons": _build_reasons(structure, rsi14, ma_bias_pct, dmi_result, bb, price, event),
        "disclaimer": "本地規則式合成，非 AI 研判、非投資建議，SL/TP 為簡化啟發式估算",
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

    # 1) 資料不足 -> available False
    check("insufficient data", build_trade_plan([], {}, {"structure": "insufficient_data"}), {"available": False})

    # 2) 建構一段 30 天的多頭走勢 OHLC（高低收皆逐日上升，符合 bullish DMI/RSI/均線）
    rows = []
    price = 100.0
    for i in range(30):
        o = price
        c = price + 1.0
        h = c + 0.5
        low = o - 0.5
        rows.append((f"d{i}", o, h, low, c))
        price = c
    ind = indicators.compute_indicators([r[4] for r in rows])
    smc_res = {"structure": "bullish", "last_event": {"type": "BOS", "direction": "bullish", "level": rows[-2][4]}, "fvgs": []}
    plan = build_trade_plan(rows, ind, smc_res)

    check("bullish uptrend -> bias bullish", plan["bias"], "bullish")
    check("bullish plan available", plan["available"], True)
    check("bullish levels present", plan["levels"] is not None, True)
    check("bullish tp1 above price", plan["levels"]["tp1"] > plan["price"], True)
    check("bullish sl below price", plan["levels"]["sl"] < plan["price"], True)
    check("bullish rr1", plan["levels"]["rr1"], 1.0)
    check("bullish rr2", plan["levels"]["rr2"], 1.5)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
