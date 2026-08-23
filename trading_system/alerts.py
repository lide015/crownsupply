"""警報：讓使用者對特定商品自訂觸發條件（價格漲破/跌破門檻、或出現新技術訊號），條件
成立時透過既有的 Telegram／Email 管道通知（見 telegram_notify.send_text／
email_notify.send_text）。

⚠️ 誠實範圍說明：這不是逐秒即時監控。價格警報／訊號警報都是「每輪分析」的附加檢查——
piggyback 在既有的 analyze_one_instrument／_refresh_signals 週期上（手動「立即分析」，
或已經開啟的背景排程，見 scheduler.py），沒有另外開一個獨立的高頻輪詢迴圈。這代表：
沒開背景排程時，警報只在你按「立即分析」的當下被評估一次；開了背景排程，評估頻率就等於
排程間隔（下限 900 秒，見 config.SCHEDULER_MIN_INTERVAL_SECONDS）——是「下一輪分析時
發現條件已經成立了才通知」，不是「條件一成立馬上通知」。這個限制要老實顯示在前端文案裡，
不能包裝成即時監控。

純函式，不碰資料庫／網路——呼叫端（background.py）負責讀寫 db.py 的 alerts 表，並在
should_fire() 回傳 True 時呼叫 telegram_notify.send_text／email_notify.send_text。
"""

ALERT_TYPES = ("price_above", "price_below", "signal")


def evaluate_condition(alert: dict, context: dict) -> bool:
    """判斷這個警報的觸發條件現在是否成立（不考慮 enabled／冷卻——那是 should_fire 的
    事）。context 依 alert["alert_type"] 需要不同欄位：
    - price_above／price_below：context 需含 "current_price"（float 或 None）。
    - signal：context 需含 "is_new_signal"（bool，見
      background.analyze_one_instrument 的第三個回傳值——已經處理過「同商品同方向
      已有未結算訊號不算新」的去重，這裡不用重複判斷）。
    商品這輪抓不到報價／訊號資料時，對應欄位傳 None／False，一律視為條件不成立——沒有
    資料不能假裝條件成立誤觸發。"""
    alert_type = alert["alert_type"]
    if alert_type == "price_above":
        price = context.get("current_price")
        return price is not None and price >= alert["threshold"]
    if alert_type == "price_below":
        price = context.get("current_price")
        return price is not None and price <= alert["threshold"]
    if alert_type == "signal":
        return bool(context.get("is_new_signal"))
    return False


def should_fire(alert: dict, condition_met: bool, now_ms: int, min_retrigger_seconds: int) -> bool:
    """條件成立(condition_met=True)且符合觸發規則才回傳 True：
    - alert 沒有 enabled，一律不觸發。
    - repeat_mode == "once"：trigger_count 還是 0 才允許觸發一次——呼叫端要記得在真的
      觸發後把 enabled 設回 False（見 db.record_alert_trigger），不是靠這個函式關閉。
    - repeat_mode == "repeating"：距離上次觸發至少要過 min_retrigger_seconds 才允許再
      觸發，避免同一個條件持續成立時每輪分析都通知一次（通知疲勞）。從沒觸發過
      （last_triggered_at 是 None）視為冷卻已過，允許觸發。"""
    if not condition_met or not alert.get("enabled", True):
        return False
    if alert.get("repeat_mode") == "once":
        return alert.get("trigger_count", 0) == 0
    last = alert.get("last_triggered_at")
    if last is None:
        return True
    return (now_ms - last) >= min_retrigger_seconds * 1000


def build_alert_message(alert: dict, context: dict) -> str:
    """組出通知文字，Telegram／Email 共用同一份內容（Email 另外切一行當標題，見
    background.py 呼叫端的組裝方式）。"""
    name = alert.get("name") or alert.get("inst_id", "")
    alert_type = alert["alert_type"]
    if alert_type == "price_above":
        line = f"🔔 {name} 價格已達 {alert['threshold']}（目前 {context.get('current_price')}），你設定的「漲破」警報觸發了。"
    elif alert_type == "price_below":
        line = f"🔔 {name} 價格已跌破 {alert['threshold']}（目前 {context.get('current_price')}），你設定的「跌破」警報觸發了。"
    elif alert_type == "signal":
        line = f"🔔 {name} 出現新的技術訊號，你設定的訊號警報觸發了——詳情請到網頁上查看。"
    else:
        line = f"🔔 {name} 警報觸發了。"
    return line + "\n⚠️ 僅供監控參考，非投資建議，本系統不會自動下單。"


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

    # 1) evaluate_condition：price_above/price_below/signal 三種類型
    above = {"alert_type": "price_above", "threshold": 100.0}
    check("price_above: price at threshold -> True", evaluate_condition(above, {"current_price": 100.0}), True)
    check("price_above: price over threshold -> True", evaluate_condition(above, {"current_price": 105.0}), True)
    check("price_above: price under threshold -> False", evaluate_condition(above, {"current_price": 95.0}), False)
    check("price_above: no price data -> False (never guess)", evaluate_condition(above, {"current_price": None}), False)
    check("price_above: missing key entirely -> False", evaluate_condition(above, {}), False)

    below = {"alert_type": "price_below", "threshold": 50.0}
    check("price_below: price at threshold -> True", evaluate_condition(below, {"current_price": 50.0}), True)
    check("price_below: price under threshold -> True", evaluate_condition(below, {"current_price": 45.0}), True)
    check("price_below: price over threshold -> False", evaluate_condition(below, {"current_price": 55.0}), False)

    sig = {"alert_type": "signal"}
    check("signal: is_new_signal True -> True", evaluate_condition(sig, {"is_new_signal": True}), True)
    check("signal: is_new_signal False -> False", evaluate_condition(sig, {"is_new_signal": False}), False)
    check("signal: missing context -> False", evaluate_condition(sig, {}), False)

    check("unknown alert_type -> False", evaluate_condition({"alert_type": "bogus"}, {"current_price": 100}), False)

    # 2) should_fire：enabled/repeat_mode/冷卻
    check(
        "disabled alert never fires even if condition met",
        should_fire({"enabled": False, "repeat_mode": "repeating"}, True, 1000, 60),
        False,
    )
    check(
        "condition not met -> never fires regardless of mode",
        should_fire({"enabled": True, "repeat_mode": "once", "trigger_count": 0}, False, 1000, 60),
        False,
    )
    check(
        "once mode, never triggered before -> fires",
        should_fire({"enabled": True, "repeat_mode": "once", "trigger_count": 0}, True, 1000, 60),
        True,
    )
    check(
        "once mode, already triggered once -> does not fire again",
        should_fire({"enabled": True, "repeat_mode": "once", "trigger_count": 1}, True, 1000, 60),
        False,
    )
    check(
        "repeating mode, never triggered before (last_triggered_at=None) -> fires",
        should_fire({"enabled": True, "repeat_mode": "repeating", "last_triggered_at": None}, True, 1000, 60),
        True,
    )
    check(
        "repeating mode, cooldown not yet elapsed -> does not fire",
        should_fire({"enabled": True, "repeat_mode": "repeating", "last_triggered_at": 1000}, True, 1000 + 30_000, 60),
        False,
    )
    check(
        "repeating mode, cooldown exactly elapsed -> fires",
        should_fire({"enabled": True, "repeat_mode": "repeating", "last_triggered_at": 1000}, True, 1000 + 60_000, 60),
        True,
    )
    check(
        "repeating mode, cooldown well past -> fires",
        should_fire({"enabled": True, "repeat_mode": "repeating", "last_triggered_at": 1000}, True, 1000 + 120_000, 60),
        True,
    )

    # 3) build_alert_message：三種類型的文字內容
    msg_above = build_alert_message({"alert_type": "price_above", "threshold": 100.0, "name": "BTC-USDT"}, {"current_price": 103.5})
    check("price_above message includes name", "BTC-USDT" in msg_above, True)
    check("price_above message includes threshold", "100.0" in msg_above, True)
    check("price_above message includes current price", "103.5" in msg_above, True)
    check("price_above message says 漲破", "漲破" in msg_above, True)
    check("message includes disclaimer", "非投資建議" in msg_above, True)

    msg_below = build_alert_message({"alert_type": "price_below", "threshold": 50.0, "name": "ETH-USDT"}, {"current_price": 48.0})
    check("price_below message says 跌破", "跌破" in msg_below, True)

    msg_signal = build_alert_message({"alert_type": "signal", "name": "SOL-USDT"}, {})
    check("signal message includes name", "SOL-USDT" in msg_signal, True)
    check("signal message mentions 新的技術訊號", "新的技術訊號" in msg_signal, True)

    # name 缺席時退回 inst_id，不會顯示空字串
    msg_no_name = build_alert_message({"alert_type": "signal", "inst_id": "DOGE-USDT-SWAP"}, {})
    check("missing name falls back to inst_id", "DOGE-USDT-SWAP" in msg_no_name, True)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
