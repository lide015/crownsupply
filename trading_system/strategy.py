"""技術面交易大腦：20 EMA 趨勢 + 盤整盒子突破。零指標學習曲線，只看價格行為本身。
輸入一律是「已收盤」的 K 線（見 okx_client.fetch_confirmed_candles），避免插針假突破。
"""
import pandas as pd


def compute_signal(candles: list[dict], ema_period: int = 20, box_lookback: int = 15) -> dict | None:
    """candles: 升冪（舊到新）的 [{o,h,l,c}, ...]，全部是已收盤的 K 線。

    做多：收盤價站上盒子高點，且站上 20 EMA。
    做空：收盤價跌破盒子低點，且跌破 20 EMA。
    停損固定設在盒子中線（比「盒子邊緣」保守、比「前一根K線極值」寬鬆，兩者的折衷）。
    回傳 None 代表資料不夠（還沒收集滿 EMA 週期 + 盒子回看窗）。
    """
    min_len = max(ema_period, box_lookback + 1)
    if len(candles) < min_len:
        return None

    df = pd.DataFrame(candles)
    df["ema"] = df["c"].ewm(span=ema_period, adjust=False).mean()

    last = df.iloc[-1]
    box_df = df.iloc[-(box_lookback + 1):-1]  # 排除當前這根，只看它「之前」的整理區間
    box_high = float(box_df["h"].max())
    box_low = float(box_df["l"].min())
    box_mid = (box_high + box_low) / 2.0

    price = float(last["c"])
    ema = float(last["ema"])

    signal = None
    stop_loss = None
    if price > box_high and price > ema:
        signal = "long"
        stop_loss = box_mid
    elif price < box_low and price < ema:
        signal = "short"
        stop_loss = box_mid

    return {
        "price": price,
        "ema": round(ema, 6),
        "box_high": box_high,
        "box_low": box_low,
        "signal": signal,
        "stop_loss": stop_loss,
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

    # 1) 資料不足 -> None
    check("insufficient data -> None", compute_signal([{"o": 1, "h": 1, "l": 1, "c": 1}] * 5), None)

    # 2) 建構 20 根平盤盤整（形成盒子）+ 第 21 根強勢突破盒子高點，且站上 EMA -> long
    flat = [{"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for _ in range(20)]
    breakout_up = flat + [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0}]
    sig_long = compute_signal(breakout_up, ema_period=20, box_lookback=15)
    check("breakout above box -> long", sig_long["signal"], "long")
    check("box_high from lookback window", sig_long["box_high"], 101.0)
    check("box_low from lookback window", sig_long["box_low"], 99.0)
    check("stop_loss at box mid", sig_long["stop_loss"], 100.0)

    # 3) 對稱情境：跌破盒子低點且跌破 EMA -> short
    breakout_down = flat + [{"o": 100.0, "h": 100.0, "l": 94.0, "c": 95.0}]
    sig_short = compute_signal(breakout_down, ema_period=20, box_lookback=15)
    check("breakdown below box -> short", sig_short["signal"], "short")

    # 4) 價格仍在盒子內盤整 -> 無訊號
    still_inside = flat + [{"o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0}]
    sig_none = compute_signal(still_inside, ema_period=20, box_lookback=15)
    check("price inside box -> no signal", sig_none["signal"], None)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
