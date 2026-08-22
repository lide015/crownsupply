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


def fuse(tech: dict | None, sentiment: dict, fee_info: dict | None = None, min_net_rr: float = 1.0) -> dict:
    """tech: strategy.compute_signal() 的回傳值（可能是 None）。
    sentiment: 一個帶 "sentiment" 欄位的 dict——實際上是 news_client.get_market_and_instrument_sentiment()
    裡「這一檔商品」對應的判讀結果（沒有專屬新聞時已 fallback 成整體市場判斷），也相容
    get_market_sentiment() 的整體市場回傳值。
    fee_info: fee_calc.compute_fee_adjusted_rr() 的回傳值（可能是 None，代表沒有 TP1 目標
    可以算，或呼叫端選擇不計算）——扣掉當沖來回手續費之後，這筆訊號是不是還「划算」，
    是比純技術面/新聞面共振更後面一關的把關：就算技術面突破、新聞情緒也共振，如果
    停損盒子窄到手續費會吃光大半停利1的獲利，一樣要老實攔截，不能讓使用者衝進一筆
    「看對方向也賺不到錢」的交易。
    回傳 {"action": str, "color": str, "reason": str}。"""
    if tech is None or tech.get("signal") is None:
        return {
            "action": "觀望中",
            "color": COLOR_GRAY,
            "reason": "價格仍在盒子整理區間內，或尚未站上/跌破 20 EMA，技術面尚無訊號。",
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

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
