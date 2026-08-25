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


def compute_atr(candles: list[dict], period: int = 14) -> float | None:
    """平均真實區間（Average True Range，Wilder's 平滑法，跟 market_pulse.compute_rsi
    同一套遞迴平滑公式）——用「真實區間」(True Range) 取代單純的「高低價差」，把跳空
    也算進波動幅度裡：TR = max(當根高低差, |當根高點-前一根收盤|, |當根低點-前一根收盤|)。

    資料不足（至少需要 period+1 根，第一個 TR 要用到「前一根」收盤價）回傳 None——沒有
    足夠資料硬算出來的數字會失真，不如老實回報「算不出來」，跟 compute_rsi 同樣的慣例。"""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high, low, prev_close = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 8)


def compute_signal(
    candles: list[dict],
    ema_period: int = 20,
    box_lookback: int = 15,
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.0,
    volume_confirm_multiple: float = 0.0,
    stop_loss_mode: str = "box_mid",
    atr_period: int = 14,
    atr_multiple: float = 1.5,
) -> dict | None:
    """candles: 升冪（舊到新）的 [{o,h,l,c}, ...]，全部是已收盤的 K 線。

    做多：收盤價站上盒子高點，且站上 20 EMA。
    做空：收盤價跌破盒子低點，且跌破 20 EMA。

    停損有兩種可選模式（stop_loss_mode，預設 "box_mid" 維持原本行為，向後相容）：
    - "box_mid"（預設）：固定設在盒子中線（比「盒子邊緣」保守、比「前一根K線極值」寬鬆，
      兩者的折衷）——不管這檔商品現在波動大小，同樣寬度的盒子給同樣寬度的停損。
    - "atr"：停損距離改用 ATR（見 compute_atr）× atr_multiple 決定，波動大時停損自動
      放寬（避免被正常波動洗出場）、波動小時停損自動收緊（避免虧損風險過度暴露）——
      跟盒子寬度完全脫鉤，是「這檔商品最近真的有多躁動」決定停損遠近，不是「盤整區間
      剛好多寬」決定。資料不足以算出 ATR 時（理論上不會發生，因為進到這個判斷分支已經
      通過了 min_len 檢查，防禦性處理）優雅退回 box_mid，不會讓整個訊號判斷失敗。
      ⚠️ 這個模式下 stop_loss 不保證還在 invalidation_price（盒子邊緣，見下方說明）
      之外——ATR 距離是獨立算出來的，可能比box_mid模式更緊、也可能更寬，這是換成
      波動導向停損的固有特性，不是計算錯誤。
    停利用風報比（reward:risk）算：risk = |進場價 - 停損價|，
    TP1 = 進場價 ± risk * tp1_rr（可先減碼）、TP2 = 進場價 ± risk * tp2_rr（留給趨勢延續）。

    失效條件（invalidation_price）跟停損是兩個不同的概念，刻意分開揭露：停損是「虧到
    這裡就認賠出場」的風險控管價位；失效條件是「這個判斷邏輯本身還成不成立」的結構性
    價位——做多訊號的判斷邏輯是「站上盒子高點」，如果收盤價又跌破盒子高點（跌回盒子
    裡面），代表這次突破很可能是假突破，這個訊號的原始論述已經站不住腳，是比停損更早、
    更輕的示警（做多：invalidation_price = box_high，介於進場價與停損價之間；
    做空對稱：invalidation_price = box_low）。這個機制只在有訊號時才有意義，沒有訊號
    時是 None。

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

    # ATR 只在真的用得到、而且真的有突破時才算——沒有訊號就沒有「停損要設多遠」的問題，
    # 沒必要每次呼叫都白算一次 ATR。
    atr_value = None
    if stop_loss_mode == "atr" and (raw_long_breakout or raw_short_breakout) and volume_confirmed:
        atr_value = compute_atr(candles, atr_period)
    use_atr_stop = stop_loss_mode == "atr" and atr_value is not None and atr_value > 0

    signal = None
    stop_loss = None
    take_profit_1 = None
    take_profit_2 = None
    invalidation_price = None
    if raw_long_breakout and volume_confirmed:
        signal = "long"
        stop_loss = price - atr_value * atr_multiple if use_atr_stop else box_mid
        risk = price - stop_loss
        take_profit_1 = price + risk * tp1_rr
        take_profit_2 = price + risk * tp2_rr
        invalidation_price = box_high
    elif raw_short_breakout and volume_confirmed:
        signal = "short"
        stop_loss = price + atr_value * atr_multiple if use_atr_stop else box_mid
        risk = stop_loss - price
        take_profit_1 = price - risk * tp1_rr
        take_profit_2 = price - risk * tp2_rr
        invalidation_price = box_low

    return {
        "price": price,
        "ema": round(ema, 6),
        "box_high": box_high,
        "box_low": box_low,
        "signal": signal,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "invalidation_price": invalidation_price,
        "tp1_rr": tp1_rr,
        "tp2_rr": tp2_rr,
        # stop_loss_mode 是呼叫端「要求」的模式；atr_value 有實際數字才代表真的用 ATR
        # 算出停損（None 代表模式不是 "atr"、或沒有訊號、或防禦性 fallback 退回
        # box_mid 了），前端可以用「atr_value is not None」判斷這筆訊號實際用的是哪一種，
        # 不用另外猜 stop_loss_mode 有沒有生效。
        "stop_loss_mode": stop_loss_mode,
        "atr_value": atr_value,
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
    # 失效條件（做多）＝ box_high——介於進場價(105)跟停損(100)之間，是比停損更早的示警。
    check("long invalidation_price = box_high", sig_long["invalidation_price"], 101.0)
    check("long invalidation sits between entry and stop_loss", sig_long["stop_loss"] < sig_long["invalidation_price"] < sig_long["price"], True)

    # 3) 對稱情境：跌破盒子低點且跌破 EMA -> short
    breakout_down = flat + [{"o": 100.0, "h": 100.0, "l": 94.0, "c": 95.0}]
    sig_short = compute_signal(breakout_down, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("breakdown below box -> short", sig_short["signal"], "short")
    # entry=95, stop_loss=100 -> risk=5 -> tp1=95-5*1.5=87.5, tp2=95-5*2.0=85.0
    check("short take_profit_1 at 1.5R", sig_short["take_profit_1"], 87.5)
    check("short take_profit_2 at 2.0R", sig_short["take_profit_2"], 85.0)
    # 失效條件（做空）＝ box_low——同樣介於進場價(95)跟停損(100)之間。
    check("short invalidation_price = box_low", sig_short["invalidation_price"], 99.0)
    check("short invalidation sits between entry and stop_loss", sig_short["price"] < sig_short["invalidation_price"] < sig_short["stop_loss"], True)

    # 4) 價格仍在盒子內盤整 -> 無訊號，停損停利皆為 None
    still_inside = flat + [{"o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0}]
    sig_none = compute_signal(still_inside, ema_period=20, box_lookback=15)
    check("price inside box -> no signal", sig_none["signal"], None)
    check("no signal -> no take_profit", sig_none["take_profit_1"], None)
    check("no breakout at all -> not blocked_by_volume", sig_none["blocked_by_volume"], False)
    check("no signal -> no invalidation_price", sig_none["invalidation_price"], None)

    # 5) 量能突破確認：突破但量能不足 -> 不觸發訊號，且明確標示 blocked_by_volume
    flat_low_vol = [{"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "vol": 1000.0} for _ in range(20)]
    weak_breakout = flat_low_vol + [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 500.0}]  # 量能只有均量的一半
    sig_weak = compute_signal(weak_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=1.2)
    check("breakout with weak volume -> no signal", sig_weak["signal"], None)
    check("breakout with weak volume -> volume_confirmed False", sig_weak["volume_confirmed"], False)
    check("breakout with weak volume -> blocked_by_volume True", sig_weak["blocked_by_volume"], True)
    check("breakout blocked by volume -> no invalidation_price either (no real signal)", sig_weak["invalidation_price"], None)

    # 6) 量能突破確認：突破且量能充足 -> 正常觸發訊號
    strong_breakout = flat_low_vol + [{"o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 2000.0}]  # 量能是均量的 2 倍
    sig_strong = compute_signal(strong_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=1.2)
    check("breakout with strong volume -> long signal", sig_strong["signal"], "long")
    check("breakout with strong volume -> volume_confirmed True", sig_strong["volume_confirmed"], True)

    # 7) volume_confirm_multiple=0（預設）-> 完全不啟用量能過濾，就算量能極低也照樣觸發
    sig_disabled = compute_signal(weak_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=0.0)
    check("volume_confirm_multiple=0 -> filter disabled, signal still fires", sig_disabled["signal"], "long")

    # 7b) compute_atr -- 手算驗證：TR 恆定 2.0 時 ATR 也是 2.0，接著一根真實區間跳大到
    # 6.0 的K線，Wilder 平滑後 ATR 往上調整但不是直接跳到 6.0（平滑，不是瞬間反應）
    atr_flat_trs = [
        {"h": 10, "l": 8, "c": 9}, {"h": 11, "l": 9, "c": 10},
        {"h": 12, "l": 10, "c": 11}, {"h": 13, "l": 11, "c": 12},
    ]
    check("compute_atr: constant true range 2.0 across 3 periods -> ATR 2.0", compute_atr(atr_flat_trs, period=3), 2.0)
    atr_with_spike = atr_flat_trs + [{"h": 10, "l": 6, "c": 8}]  # 這根 TR=max(4,|10-12|,|6-12|)=6
    check("compute_atr: Wilder-smoothed after a volatility spike -> 3.33333333 (not a raw average)",
          compute_atr(atr_with_spike, period=3), 3.33333333)
    check("compute_atr: insufficient data (< period+1 candles) -> None", compute_atr(atr_flat_trs[:3], period=3), None)

    # 7c) compute_signal stop_loss_mode="atr" -- 停損改用 ATR×倍數算，不是盒子中點
    sig_atr = compute_signal(breakout_up, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0,
                              stop_loss_mode="atr", atr_period=14, atr_multiple=1.5)
    check("stop_loss_mode=atr: atr_value populated when mode is atr and signal fires", sig_atr["atr_value"], 2.28571429)
    check("stop_loss_mode=atr: stop_loss uses ATR×multiple, not box_mid", sig_atr["stop_loss"], 101.571428565)
    check("stop_loss_mode=atr: stop_loss differs from what box_mid mode would give (100.0)", sig_atr["stop_loss"] != 100.0, True)
    check("stop_loss_mode=atr: invalidation_price still uses box structure regardless of stop mode", sig_atr["invalidation_price"], 101.0)
    check("stop_loss_mode=atr: risk/reward still derived from the ATR-based stop_loss",
          round(sig_atr["take_profit_1"], 6), round(sig_atr["price"] + (sig_atr["price"] - sig_atr["stop_loss"]) * 1.5, 6))
    check("stop_loss_mode=atr: stop_loss_mode field echoes back the requested mode", sig_atr["stop_loss_mode"], "atr")

    # 7d) compute_signal stop_loss_mode="box_mid"（預設）-- 完全不受新參數影響，向後相容
    sig_default_mode = compute_signal(breakout_up, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("default stop_loss_mode is box_mid (backward compatible)", sig_default_mode["stop_loss"], 100.0)
    check("default stop_loss_mode: atr_value is None (never computed, no cost incurred)", sig_default_mode["atr_value"], None)

    # 7e) compute_signal stop_loss_mode="atr" 但資料不夠算出 ATR（box_lookback 過關但
    # atr_period 過大）-- 優雅退回 box_mid，不會讓整筆訊號判斷失敗
    sig_atr_fallback = compute_signal(breakout_up, ema_period=20, box_lookback=15, stop_loss_mode="atr", atr_period=25)
    check("stop_loss_mode=atr with insufficient ATR data -> falls back to box_mid", sig_atr_fallback["stop_loss"], 100.0)
    check("stop_loss_mode=atr with insufficient ATR data -> atr_value stays None (honest, not a fabricated fallback number)",
          sig_atr_fallback["atr_value"], None)
    check("stop_loss_mode=atr with insufficient ATR data -> signal still fires (fallback doesn't block the trade)",
          sig_atr_fallback["signal"], "long")

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
