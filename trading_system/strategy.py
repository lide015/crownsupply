"""技術面交易大腦：20 EMA 趨勢 + 盤整盒子突破。零指標學習曲線，只看價格行為本身。
輸入一律是「已收盤」的 K 線（見 okx_client.fetch_confirmed_candles），避免插針假突破。
"""
import pandas as pd


def compute_ema_series(candles: list[dict], period: int = 20) -> list[float] | None:
    """算出每一根K線當下的 EMA 值（pandas ewm(span=period, adjust=False)）。這是
    `compute_signal()` 判斷方向用的同一套公式，單獨拉出來給 K 線走勢圖疊加 EMA 線用
    （見 app.py 的 /api/v1/candles 端點），兩處只有一份公式，不會各寫一套可能兜不起來
    的版本。資料不到一個 EMA 週期就回傳 None（呼叫端沒有足夠資料可以判斷）。"""
    if len(candles) < period:
        return None
    df = pd.DataFrame(candles)
    return [round(float(v), 6) for v in df["c"].ewm(span=period, adjust=False).mean()]


def compute_signal(
    candles: list[dict],
    ema_period: int = 20,
    box_lookback: int = 15,
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.0,
    volume_confirm_multiple: float = 0.0,
) -> dict | None:
    """candles: 升冪（舊到新）的 [{o,h,l,c}, ...]，全部是已收盤的 K 線。

    做多：收盤價站上盒子高點，且站上 20 EMA。
    做空：收盤價跌破盒子低點，且跌破 20 EMA。
    停損固定設在盒子中線（比「盒子邊緣」保守、比「前一根K線極值」寬鬆，兩者的折衷）。
    停利用風報比（reward:risk）算：risk = |進場價 - 停損價|，
    TP1 = 進場價 ± risk * tp1_rr（可先減碼）、TP2 = 進場價 ± risk * tp2_rr（留給趨勢延續）。
    回傳 None 代表資料不夠（還沒收集滿 EMA 週期 + 盒子回看窗）。

    volume_confirm_multiple：量能突破確認——真正有動能的突破通常伴隨成交量放大，雜訊
    假突破的量能往往稀薄，這是很基本的技術分析常識。0（預設）代表不啟用，維持原本
    行為；> 0 時，突破那根 K 線的成交量必須達到「盒子回看窗」平均成交量的這個倍數以上，
    否則視為量能不足、不觸發訊號。candles 沒有 "vol" 欄位時（例如舊測試資料、或資料源
    沒提供）一律優雅放行、視為無法判斷，不會因為缺資料就擋掉原本該有的訊號。
    """
    min_len = max(ema_period, box_lookback + 1)
    if len(candles) < min_len:
        return None

    # min_len >= ema_period 保證了這裡一定拿得到非 None 的 EMA 序列，不用另外判斷。
    ema_series = compute_ema_series(candles, ema_period)

    df = pd.DataFrame(candles)
    last = df.iloc[-1]
    box_df = df.iloc[-(box_lookback + 1):-1]  # 排除當前這根，只看它「之前」的整理區間
    box_high = float(box_df["h"].max())
    box_low = float(box_df["l"].min())
    box_mid = (box_high + box_low) / 2.0

    price = float(last["c"])
    ema = ema_series[-1]

    volume_confirmed = True
    avg_vol = None
    current_vol = None
    if volume_confirm_multiple > 0 and "vol" in df.columns:
        current_vol = float(last["vol"])
        avg_vol = float(box_df["vol"].mean())
        if avg_vol > 0:
            volume_confirmed = current_vol >= avg_vol * volume_confirm_multiple

    raw_long_breakout = price > box_high and price > ema
    raw_short_breakout = price < box_low and price < ema

    signal = None
    stop_loss = None
    take_profit_1 = None
    take_profit_2 = None
    if raw_long_breakout and volume_confirmed:
        signal = "long"
        stop_loss = box_mid
        risk = price - stop_loss
        take_profit_1 = price + risk * tp1_rr
        take_profit_2 = price + risk * tp2_rr
    elif raw_short_breakout and volume_confirmed:
        signal = "short"
        stop_loss = box_mid
        risk = stop_loss - price
        take_profit_1 = price - risk * tp1_rr
        take_profit_2 = price - risk * tp2_rr

    return {
        "price": price,
        "ema": round(ema, 6),
        "box_high": box_high,
        "box_low": box_low,
        "signal": signal,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "tp1_rr": tp1_rr,
        "tp2_rr": tp2_rr,
        "volume_confirmed": volume_confirmed,
        "avg_vol": avg_vol,
        "current_vol": current_vol,
        # 技術面上有效突破（價格+EMA都符合），但量能不足被擋下來——跟「根本沒有突破」
        # 是不同的情況，brain.fuse() 用這個欄位給使用者一個具體的理由，不是含糊的「觀望中」。
        "blocked_by_volume": (raw_long_breakout or raw_short_breakout) and not volume_confirmed,
    }


def compute_trend_bias(candles: list[dict], ema_period: int = 20) -> str | None:
    """更高週期的簡單趨勢判斷，給多時間週期共振用（見 brain.fuse() 的 htf_trend 參數）。
    不是另一套複雜指標——就是同一套「收盤價 vs EMA」邏輯，只是套用在更長的 K 線週期上
    （例如 1 小時線），跟 5 分鐘線判斷方向的思路一致，只是看的時間尺度不同：5 分鐘線
    決定「現在要不要進場」，1 小時線決定「大方向站在哪一邊」，兩者同向才是真正值得跟隨
    的動能，逆著大方向做短線突破容易被雜訊洗出場。

    回傳 "up"/"down"；資料不夠（不到一個 EMA 週期）或剛好持平（極罕見）回傳 None，
    代表無法判斷、呼叫端應該優雅忽略這個維度，不要當作明確反向。
    """
    if len(candles) < ema_period:
        return None
    df = pd.DataFrame(candles)
    ema = df["c"].ewm(span=ema_period, adjust=False).mean().iloc[-1]
    price = df["c"].iloc[-1]
    if price > ema:
        return "up"
    if price < ema:
        return "down"
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

    # 1) 資料不足 -> None
    check("insufficient data -> None", compute_signal([{"o": 1, "h": 1, "l": 1, "c": 1}] * 5), None)

    # 2) 建構 20 根平盤盤整（形成盒子）+ 第 21 根強勢突破盒子高點，且站上 EMA -> long
    flat = [{"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for _ in range(20)]
    breakout_up = flat + [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0}]
    sig_long = compute_signal(breakout_up, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("breakout above box -> long", sig_long["signal"], "long")
    check("box_high from lookback window", sig_long["box_high"], 101.0)
    check("box_low from lookback window", sig_long["box_low"], 99.0)
    check("stop_loss at box mid", sig_long["stop_loss"], 100.0)
    # entry=105, stop_loss=100 -> risk=5 -> tp1=105+5*1.5=112.5, tp2=105+5*2.0=115.0
    check("take_profit_1 at 1.5R", sig_long["take_profit_1"], 112.5)
    check("take_profit_2 at 2.0R", sig_long["take_profit_2"], 115.0)
    check("no volume data -> volume_confirmed defaults True", sig_long["volume_confirmed"], True)
    check("no volume data -> not blocked_by_volume", sig_long["blocked_by_volume"], False)

    # 3) 對稱情境：跌破盒子低點且跌破 EMA -> short
    breakout_down = flat + [{"o": 100.0, "h": 100.0, "l": 94.0, "c": 95.0}]
    sig_short = compute_signal(breakout_down, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("breakdown below box -> short", sig_short["signal"], "short")
    # entry=95, stop_loss=100 -> risk=5 -> tp1=95-5*1.5=87.5, tp2=95-5*2.0=85.0
    check("short take_profit_1 at 1.5R", sig_short["take_profit_1"], 87.5)
    check("short take_profit_2 at 2.0R", sig_short["take_profit_2"], 85.0)

    # 4) 價格仍在盒子內盤整 -> 無訊號，停損停利皆為 None
    still_inside = flat + [{"o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0}]
    sig_none = compute_signal(still_inside, ema_period=20, box_lookback=15)
    check("price inside box -> no signal", sig_none["signal"], None)
    check("no signal -> no take_profit", sig_none["take_profit_1"], None)
    check("no breakout at all -> not blocked_by_volume", sig_none["blocked_by_volume"], False)

    # 5) 量能突破確認：突破但量能不足 -> 不觸發訊號，且明確標示 blocked_by_volume
    flat_low_vol = [{"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "vol": 1000.0} for _ in range(20)]
    weak_breakout = flat_low_vol + [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 500.0}]  # 量能只有均量的一半
    sig_weak = compute_signal(weak_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=1.2)
    check("breakout with weak volume -> no signal", sig_weak["signal"], None)
    check("breakout with weak volume -> volume_confirmed False", sig_weak["volume_confirmed"], False)
    check("breakout with weak volume -> blocked_by_volume True", sig_weak["blocked_by_volume"], True)

    # 6) 量能突破確認：突破且量能充足 -> 正常觸發訊號
    strong_breakout = flat_low_vol + [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 2000.0}]  # 量能是均量的 2 倍
    sig_strong = compute_signal(strong_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=1.2)
    check("breakout with strong volume -> long signal", sig_strong["signal"], "long")
    check("breakout with strong volume -> volume_confirmed True", sig_strong["volume_confirmed"], True)

    # 7) volume_confirm_multiple=0（預設）-> 完全不啟用量能過濾，就算量能極低也照樣觸發
    sig_disabled = compute_signal(weak_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=0.0)
    check("volume_confirm_multiple=0 -> filter disabled, signal still fires", sig_disabled["signal"], "long")

    # 8) compute_trend_bias：站上 EMA -> up；跌破 -> down；資料不足 -> None
    up_candles = [{"c": 100.0} for _ in range(19)] + [{"c": 110.0}]
    check("trend bias: price above EMA -> up", compute_trend_bias(up_candles, ema_period=20), "up")
    down_candles = [{"c": 100.0} for _ in range(19)] + [{"c": 90.0}]
    check("trend bias: price below EMA -> down", compute_trend_bias(down_candles, ema_period=20), "down")
    check("trend bias: insufficient data -> None", compute_trend_bias([{"c": 100.0}] * 5, ema_period=20), None)

    # 9) compute_ema_series：長度跟輸入一致、資料不足回傳 None、跟 compute_signal 內部
    # 用的是同一份數字（不會各算一套兜不起來的版本）
    check("compute_ema_series insufficient data -> None", compute_ema_series([{"c": 100.0}] * 5, period=20), None)
    series = compute_ema_series(flat, period=20)
    check("compute_ema_series length matches input", len(series), len(flat))
    check("compute_ema_series constant price -> EMA settles at that price", series[-1], 100.0)
    check("compute_signal's ema field matches compute_ema_series' last value",
          sig_long["ema"], compute_ema_series(breakout_up, period=20)[-1])

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
