"""多空共振大腦：把 strategy.py 的技術面訊號跟 news_client.py 的 AI 新聞情緒融合成
最終的「行動建議」。純函式、零網路呼叫，方便單元測試。

⚠️ 重要：本模組只產生「訊號與建議」，不含下單邏輯，不會動用任何交易所 API 金鑰去真正
開倉/平倉。所有輸出都只供人工參考，不是投資建議，也不是自動化交易系統。
"""

COLOR_GRAY = "gray"
COLOR_GREEN = "green"
COLOR_RED = "red"
COLOR_YELLOW = "yellow"
COLOR_BLUE = "blue"


def fuse(
    tech: dict | None,
    sentiment: dict,
    fee_info: dict | None = None,
    min_net_rr: float = 1.0,
    htf_trend: str | None = None,
    circuit_breaker: dict | None = None,
    exposure_gate: dict | None = None,
    volatility_gate: dict | None = None,
    direction_concentration_gate: dict | None = None,
) -> dict:
    """tech: strategy.compute_signal() 的回傳值（可能是 None）。
    sentiment: 一個帶 "sentiment" 欄位的 dict——實際上是 news_client.get_market_and_instrument_sentiment()
    裡「這一檔商品」對應的判讀結果（沒有專屬新聞時已 fallback 成整體市場判斷），也相容
    get_market_sentiment() 的整體市場回傳值。
    fee_info: fee_calc.compute_fee_adjusted_rr() 的回傳值（可能是 None，代表沒有 TP1 目標
    可以算，或呼叫端選擇不計算）——扣掉當沖來回手續費之後，這筆訊號是不是還「划算」，
    是比純技術面/新聞面共振更後面一關的把關：就算技術面突破、新聞情緒也共振，如果
    停損盒子窄到手續費會吃光大半停利1的獲利，一樣要老實攔截，不能讓使用者衝進一筆
    「看對方向也賺不到錢」的交易。
    htf_trend: strategy.compute_trend_bias() 在更高週期（例如1小時線）算出來的大方向
    （"up"/"down"/None）——技術面在 5 分鐘線突破，但更高週期的大方向明確反向時，這種
    逆勢短線突破特別容易被雜訊洗出場，一樣要攔截成警告，不是直接當作強訊號。
    circuit_breaker: {"active": bool, "reason": str}（可能是 None，代表不啟用這個機制）——
    「今天」已經連續虧損/累積虧損達到使用者自訂上限時，不管這筆訊號技術面/新聞面/淨盈虧比
    再怎麼漂亮，都優先攔截成「今日建議停止交易」，這是跟單一訊號品質無關、更上層的紀律
    把關，所以擺在所有判斷「最前面」，連「觀望中」都會被它取代（讓使用者一眼就知道今天
    為什麼要停手，而不是看到一堆「觀望中」不知道原因）。
    exposure_gate: outcome_tracker.compute_exposure_gate() 的回傳值（可能是 None，代表
    不啟用）——現在同時開著的部位數已經達到自訂上限時攔截「新」訊號，不管這筆訊號本身
    多漂亮，帳戶整體風險已經足夠了。優先序在 circuit_breaker 之後、但在 tech 是否有
    訊號的判斷「之前」不合理（沒有訊號就沒有「要不要加碼」的問題），所以擺在
    tech-is-None 判斷之後、fee_info 判斷之前。
    volatility_gate: outcome_tracker.compute_volatility_gate() 的回傳值（可能是 None，
    代表不啟用）——這檔商品的 24h 振幅過於劇烈時攔截成警告，優先序在 htf_trend 判斷
    之後（先看方向對不對，再看波動是不是在合理範圍）。
    direction_concentration_gate: outcome_tracker.compute_direction_concentration_gate()
    的回傳值（可能是 None，代表不啟用；預設關閉，見該函式說明）——同一個方向（多或空）
    的未結算訊號數已經達到自訂上限時攔截「這個方向」的新訊號。呼叫端要先看這筆訊號的
    方向（tech["signal"]），從「多方關卡」「空方關卡」兩個算好的結果裡挑對應那一個
    傳進來——這裡不自己判斷方向，因為在還沒看到 signal 是 long 還是 short 之前，這個
    參數本身就無法決定要套用哪一個方向的關卡。優先序跟 exposure_gate 放在一起（都是
    portfolio-level、不是這筆訊號自己品質的問題），在 exposure_gate 之後。
    回傳 {"action": str, "color": str, "reason": str}。"""
    if circuit_breaker and circuit_breaker.get("active"):
        return {
            "action": "🛑 今日已達虧損上限 (DAILY LIMIT)",
            "color": COLOR_YELLOW,
            "reason": circuit_breaker.get("reason") or "今日累積虧損已達自訂上限，建議停止交易、等明天重新評估。",
        }

    if tech is None or tech.get("signal") is None:
        if tech is not None and tech.get("blocked_by_volume"):
            return {
                "action": "⚠️ 量能不足，暫不觸發 (WEAK VOLUME)",
                "color": COLOR_YELLOW,
                "reason": (
                    f"價格站穩盒子邊界、也符合 20 EMA 方向，但這根K線成交量"
                    f"（{tech.get('current_vol')}）沒有明顯放大（近期均量 {tech.get('avg_vol')}），"
                    "真正有動能的突破通常伴隨量能放大，量能不足的突破容易是雜訊假突破，暫不觸發訊號。"
                ),
            }
        return {
            "action": "觀望中",
            "color": COLOR_GRAY,
            "reason": "價格仍在盒子整理區間內，或尚未站上/跌破 20 EMA，技術面尚無訊號。",
        }

    if exposure_gate and exposure_gate.get("active"):
        return {
            "action": "⚠️ 曝險已達上限，暫緩新訊號 (EXPOSURE CAP)",
            "color": COLOR_YELLOW,
            "reason": exposure_gate.get("reason") or "目前同時開著的部位數已達自訂曝險上限，新訊號暫不建議加碼。",
        }

    if direction_concentration_gate and direction_concentration_gate.get("active"):
        return {
            "action": "⚠️ 同方向曝險過於集中，暫緩新訊號 (DIRECTION CAP)",
            "color": COLOR_YELLOW,
            "reason": direction_concentration_gate.get("reason") or "目前同方向的未結算訊號數已達自訂上限，新訊號暫不建議同方向加碼。",
        }

    if fee_info and fee_info.get("net_rr") is not None and fee_info["net_rr"] < min_net_rr:
        trapped = fee_info["net_reward_pct"] <= 0
        return {
            "action": "⚠️ 手續費侵蝕獲利，不建議進場 (FEE TRAP)" if trapped else "⚠️ 淨盈虧比過薄，謹慎評估 (THIN MARGIN)",
            "color": COLOR_YELLOW,
            "reason": (
                f"停利1目標獲利 {fee_info['gross_reward_pct']}%，扣掉來回手續費 {fee_info['round_trip_fee_pct']}% "
                f"後淨盈虧比只剩 {fee_info['net_rr']}"
                + ("（幾乎無利可圖）" if trapped else f"（低於門檻 {min_net_rr}）")
                + "，這種盤整幅度太窄的當沖機會扣完手續費不划算，不建議進場。"
            ),
        }

    mood = sentiment.get("sentiment", "NEUTRAL")
    signal = tech["signal"]

    if (htf_trend == "down" and signal == "long") or (htf_trend == "up" and signal == "short"):
        return {
            "action": "⚠️ 高週期趨勢逆向，觀望 (HTF CONFLICT)",
            "color": COLOR_YELLOW,
            "reason": (
                f"5分鐘線技術面{'突破' if signal == 'long' else '跌破'}，但更高週期的大方向是"
                f"{'下跌' if htf_trend == 'down' else '上漲'}——逆著大方向做的短線突破特別容易被"
                "回歸主趨勢的走勢洗出場，系統攔截以避免逆勢操作。"
            ),
        }

    if volatility_gate and volatility_gate.get("active"):
        return {
            "action": "⚠️ 波動過於劇烈，謹慎評估 (HIGH VOLATILITY)",
            "color": COLOR_YELLOW,
            "reason": volatility_gate.get("reason") or "24h 振幅超過自訂門檻，波動過於劇烈，建議謹慎評估。",
        }

    if signal == "long":
        if mood == "BULLISH":
            return {
                "action": "🔥 強烈做多 (STRONG LONG)",
                "color": COLOR_GREEN,
                "reason": f"技術面站穩盒子高點 {tech['box_high']} 之上，且 AI 新聞情緒判定為利多，多空共振。",
            }
        if mood == "BEARISH":
            return {
                "action": "⚠️ 潛在假突破，觀望 (STANDBY)",
                "color": COLOR_YELLOW,
                "reason": "技術面向上突破，但 AI 新聞情緒判定為利空，系統攔截以避免逆勢追高。",
            }
        return {
            "action": "📈 技術面做多（未經新聞驗證）",
            "color": COLOR_BLUE,
            "reason": f"技術面突破盒子高點 {tech['box_high']}，AI 新聞情緒中性或尚未啟用，僅供技術面參考。",
        }

    # signal == "short"
    if mood == "BEARISH":
        return {
            "action": "💥 強烈做空 (STRONG SHORT)",
            "color": COLOR_RED,
            "reason": f"技術面跌破盒子低點 {tech['box_low']} 之下，且 AI 新聞情緒判定為利空，多空共振。",
        }
    if mood == "BULLISH":
        return {
            "action": "⚠️ 潛在假跌破，觀望 (STANDBY)",
            "color": COLOR_YELLOW,
            "reason": "技術面向下跌破，但 AI 新聞情緒判定為利多，系統攔截以避免逆勢追空。",
        }
    return {
        "action": "📉 技術面做空（未經新聞驗證）",
        "color": COLOR_BLUE,
        "reason": f"技術面跌破盒子低點 {tech['box_low']}，AI 新聞情緒中性或尚未啟用，僅供技術面參考。",
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

    check("no tech signal -> 觀望中", fuse(None, {"sentiment": "NEUTRAL"})["action"], "觀望中")

    long_tech = {"signal": "long", "box_high": 100.0, "box_low": 90.0}
    check("long + BULLISH -> STRONG LONG", fuse(long_tech, {"sentiment": "BULLISH"})["color"], COLOR_GREEN)
    check("long + BEARISH -> STANDBY (假突破攔截)", fuse(long_tech, {"sentiment": "BEARISH"})["color"], COLOR_YELLOW)
    check("long + NEUTRAL -> 技術面獨立訊號", fuse(long_tech, {"sentiment": "NEUTRAL"})["color"], COLOR_BLUE)

    short_tech = {"signal": "short", "box_high": 100.0, "box_low": 90.0}
    check("short + BEARISH -> STRONG SHORT", fuse(short_tech, {"sentiment": "BEARISH"})["color"], COLOR_RED)
    check("short + BULLISH -> STANDBY (假跌破攔截)", fuse(short_tech, {"sentiment": "BULLISH"})["color"], COLOR_YELLOW)

    # 手續費把關：就算技術面+新聞面完美共振，淨盈虧比太薄/為負一樣要攔截，不能讓使用者
    # 衝進一筆「看對方向也賺不到錢」的交易。
    fee_trap = {"gross_reward_pct": 0.15, "round_trip_fee_pct": 0.1, "net_reward_pct": -0.05, "net_rr": -0.5}
    trapped_result = fuse(long_tech, {"sentiment": "BULLISH"}, fee_info=fee_trap, min_net_rr=1.0)
    check("perfect confluence but fee eats all profit -> still blocked", trapped_result["color"], COLOR_YELLOW)
    check("fee trap action mentions FEE TRAP", "FEE TRAP" in trapped_result["action"], True)

    fee_thin = {"gross_reward_pct": 3.0, "round_trip_fee_pct": 0.1, "net_reward_pct": 2.9, "net_rr": 0.6}
    thin_result = fuse(long_tech, {"sentiment": "BULLISH"}, fee_info=fee_thin, min_net_rr=1.0)
    check("thin net_rr below floor -> blocked (not FEE TRAP wording)", thin_result["color"], COLOR_YELLOW)
    check("thin margin action mentions THIN MARGIN", "THIN MARGIN" in thin_result["action"], True)

    fee_ok = {"gross_reward_pct": 7.5, "round_trip_fee_pct": 0.1, "net_reward_pct": 7.4, "net_rr": 1.45}
    ok_result = fuse(long_tech, {"sentiment": "BULLISH"}, fee_info=fee_ok, min_net_rr=1.0)
    check("healthy net_rr -> normal STRONG LONG logic applies", ok_result["color"], COLOR_GREEN)

    check("fee_info=None -> unaffected (backward compatible)", fuse(long_tech, {"sentiment": "BULLISH"}, fee_info=None)["color"], COLOR_GREEN)

    # 量能不足：技術面有效突破（signal 已經是 None，因為 strategy.py 那邊被量能過濾擋掉了），
    # 但 blocked_by_volume=True 時要給具體理由，不是含糊的「觀望中」。
    weak_vol_tech = {"signal": None, "blocked_by_volume": True, "current_vol": 500.0, "avg_vol": 1000.0}
    weak_vol_result = fuse(weak_vol_tech, {"sentiment": "NEUTRAL"})
    check("blocked_by_volume -> WEAK VOLUME action", "WEAK VOLUME" in weak_vol_result["action"], True)
    check("blocked_by_volume -> yellow (not gray 觀望中)", weak_vol_result["color"], COLOR_YELLOW)

    check("no breakout at all (blocked_by_volume False) -> plain 觀望中",
          fuse({"signal": None, "blocked_by_volume": False}, {"sentiment": "NEUTRAL"})["action"], "觀望中")

    # 多時間週期共振：5分鐘突破做多，但高週期趨勢是下跌 -> 攔截；同向則不受影響
    htf_conflict = fuse(long_tech, {"sentiment": "BULLISH"}, htf_trend="down")
    check("long signal + htf_trend down -> HTF CONFLICT blocked", "HTF CONFLICT" in htf_conflict["action"], True)
    check("htf conflict -> yellow", htf_conflict["color"], COLOR_YELLOW)

    htf_aligned = fuse(long_tech, {"sentiment": "BULLISH"}, htf_trend="up")
    check("long signal + htf_trend up (aligned) -> normal STRONG LONG", htf_aligned["color"], COLOR_GREEN)

    check("htf_trend=None -> unaffected (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, htf_trend=None)["color"], COLOR_GREEN)

    short_htf_conflict = fuse(short_tech, {"sentiment": "BEARISH"}, htf_trend="up")
    check("short signal + htf_trend up -> HTF CONFLICT blocked", "HTF CONFLICT" in short_htf_conflict["action"], True)

    # 每日虧損斷路器：優先於一切，就算技術面/新聞面完美共振也一樣攔截
    breaker_active = {"active": True, "reason": "今天已經連續 3 筆停損"}
    breaker_result = fuse(long_tech, {"sentiment": "BULLISH"}, circuit_breaker=breaker_active)
    check("circuit breaker active -> DAILY LIMIT overrides everything", "DAILY LIMIT" in breaker_result["action"], True)
    check("circuit breaker reason is passed through", "連續 3 筆停損" in breaker_result["reason"], True)

    # 斷路器也要能覆蓋「連 tech 都是 None」的情況（比單純的「觀望中」更有資訊量）
    breaker_no_tech = fuse(None, {"sentiment": "NEUTRAL"}, circuit_breaker=breaker_active)
    check("circuit breaker overrides even when tech is None", "DAILY LIMIT" in breaker_no_tech["action"], True)

    check("circuit_breaker inactive dict -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, circuit_breaker={"active": False, "reason": None})["color"], COLOR_GREEN)
    check("circuit_breaker=None -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, circuit_breaker=None)["color"], COLOR_GREEN)

    # 曝險上限關卡：達到上限時攔截新訊號，不管技術面/新聞面再漂亮——但只在真的有訊號時
    # 才需要攔截（沒有訊號就沒有「要不要加碼」的問題，不該覆蓋單純的「觀望中」）。
    exposure_active = {"active": True, "reason": "目前同時有 5 筆未結算訊號，已達自訂曝險上限 5 筆"}
    exposure_result = fuse(long_tech, {"sentiment": "BULLISH"}, exposure_gate=exposure_active)
    check("exposure gate active -> EXPOSURE CAP overrides signal quality", "EXPOSURE CAP" in exposure_result["action"], True)
    check("exposure gate active -> yellow", exposure_result["color"], COLOR_YELLOW)
    check("exposure gate reason passed through", "曝險上限 5 筆" in exposure_result["reason"], True)

    exposure_no_tech = fuse(None, {"sentiment": "NEUTRAL"}, exposure_gate=exposure_active)
    check("exposure gate does NOT override when tech has no signal (nothing to gate)", exposure_no_tech["action"], "觀望中")

    check("exposure gate active but circuit breaker also active -> circuit breaker wins (higher priority)",
          "DAILY LIMIT" in fuse(long_tech, {"sentiment": "BULLISH"}, circuit_breaker=breaker_active, exposure_gate=exposure_active)["action"], True)

    check("exposure_gate inactive dict -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, exposure_gate={"active": False, "reason": None})["color"], COLOR_GREEN)
    check("exposure_gate=None -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, exposure_gate=None)["color"], COLOR_GREEN)

    # 同方向曝險關卡（可選）：達到上限時攔截「這個方向」的新訊號——呼叫端負責挑對應方向
    # 那一份 gate 傳進來，fuse() 本身不自己判斷方向。
    direction_active = {"active": True, "reason": "目前已經有 3 筆同方向的未結算訊號，達到自訂上限 3 筆"}
    direction_result = fuse(long_tech, {"sentiment": "BULLISH"}, direction_concentration_gate=direction_active)
    check("direction concentration gate active -> DIRECTION CAP overrides signal quality", "DIRECTION CAP" in direction_result["action"], True)
    check("direction concentration gate active -> yellow", direction_result["color"], COLOR_YELLOW)
    check("direction concentration gate reason passed through", "同方向的未結算訊號" in direction_result["reason"], True)

    direction_no_tech = fuse(None, {"sentiment": "NEUTRAL"}, direction_concentration_gate=direction_active)
    check("direction concentration gate does NOT override when tech has no signal (nothing to gate)", direction_no_tech["action"], "觀望中")

    check("direction concentration gate active but exposure gate also active -> exposure gate wins (higher priority)",
          "EXPOSURE CAP" in fuse(long_tech, {"sentiment": "BULLISH"}, exposure_gate=exposure_active, direction_concentration_gate=direction_active)["action"], True)
    check("direction concentration gate active but circuit breaker also active -> circuit breaker wins (highest priority)",
          "DAILY LIMIT" in fuse(long_tech, {"sentiment": "BULLISH"}, circuit_breaker=breaker_active, direction_concentration_gate=direction_active)["action"], True)

    check("direction_concentration_gate inactive dict -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, direction_concentration_gate={"active": False, "reason": None})["color"], COLOR_GREEN)
    check("direction_concentration_gate=None -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, direction_concentration_gate=None)["color"], COLOR_GREEN)

    # 波動風控關卡：振幅過大時攔截成警告，優先序在 htf_trend 之後、mood 判斷之前
    volatility_active = {"active": True, "reason": "24h 振幅達 45.0%（超過門檻 20.0%），波動過於劇烈"}
    volatility_result = fuse(long_tech, {"sentiment": "BULLISH"}, volatility_gate=volatility_active)
    check("volatility gate active -> HIGH VOLATILITY overrides signal quality", "HIGH VOLATILITY" in volatility_result["action"], True)
    check("volatility gate active -> yellow", volatility_result["color"], COLOR_YELLOW)
    check("volatility gate reason passed through", "45.0%" in volatility_result["reason"], True)

    check("volatility gate active but htf_trend conflict also present -> htf conflict wins (higher priority)",
          "HTF CONFLICT" in fuse(long_tech, {"sentiment": "BULLISH"}, htf_trend="down", volatility_gate=volatility_active)["action"], True)

    check("volatility_gate inactive dict -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, volatility_gate={"active": False, "reason": None})["color"], COLOR_GREEN)
    check("volatility_gate=None -> no effect (backward compatible)",
          fuse(long_tech, {"sentiment": "BULLISH"}, volatility_gate=None)["color"], COLOR_GREEN)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
