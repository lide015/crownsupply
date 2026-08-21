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


def fuse(tech: dict | None, sentiment: dict) -> dict:
    """tech: strategy.compute_signal() 的回傳值（可能是 None）。
    sentiment: 一個帶 "sentiment" 欄位的 dict——實際上是 news_client.get_market_and_instrument_sentiment()
    裡「這一檔商品」對應的判讀結果（沒有專屬新聞時已 fallback 成整體市場判斷），也相容
    get_market_sentiment() 的整體市場回傳值。
    回傳 {"action": str, "color": str, "reason": str}。"""
    if tech is None or tech.get("signal") is None:
        return {
            "action": "觀望中",
            "color": COLOR_GRAY,
            "reason": "價格仍在盒子整理區間內，或尚未站上/跌破 20 EMA，技術面尚無訊號。",
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

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
