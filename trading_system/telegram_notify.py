"""訊號觸發通知：新訊號出現時透過 Telegram Bot 主動推播，不用一直開著網頁盯著看。

沒設定 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 時完全停用、優雅跳過——跟這個系統其他
所有可選功能（AI 新聞情緒、美股公司基本面）的慣例一致，缺金鑰不會讓分析流程掛掉，只是
少了這個額外功能。任何發送失敗（網路問題、Token 失效等）一樣要優雅吞掉例外，不能讓
通知這個附加功能拖垮主要的訊號分析。

建立方式：跟 Telegram 的 @BotFather 對話建立一個 Bot 拿到 Token；chat_id 最簡單的
取得方式是先跟這個 Bot 隨便說一句話，再打開瀏覽器連到
https://api.telegram.org/bot<TOKEN>/getUpdates 查回應裡的 message.chat.id。

只有「真正新產生」的訊號才會通知（見 background.py 的呼叫時機——只在
`_maybe_record_new_signal` 真的插入一筆新紀錄時才觸發，不會因為同一筆訊號還沒結算、
使用者又按了一次「立即分析」就重複通知）。
"""
import logging

import httpx

from . import config

logger = logging.getLogger("telegram_notify")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


async def send_text(client: httpx.AsyncClient, text: str) -> bool:
    """低階發送：純文字，訊號通知（send_signal_notification）跟警報（alerts.py／
    background.py）共用同一份發送邏輯，只是組出來的文字內容不一樣。回傳是否真的送出；
    沒設定金鑰、或發送失敗都回傳 False，自己吞掉所有例外——通知只是附加功能，絕對不能
    拖垮主要的分析流程。"""
    if not is_configured():
        return False
    try:
        resp = await client.post(
            TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN),
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — 通知失敗不能讓分析流程掛掉
        logger.warning("Telegram notification failed: %s", exc)
        return False


def build_signal_message(signal: dict) -> str:
    """把訊號 dict 組成一則簡潔的 Telegram 通知文字。純函式，不牽涉網路呼叫，方便測試。"""
    direction = "🟢 做多" if signal.get("signal_type") == "long" else "🔴 做空"
    lines = [
        str(signal.get("action", "")),
        f"{signal.get('name', signal.get('instId', ''))}　{direction}",
        f"開倉價 {signal.get('price')}",
        f"停損 {signal.get('stop_loss')}　停利1 {signal.get('take_profit_1')}　停利2 {signal.get('take_profit_2')}",
    ]
    if signal.get("net_rr") is not None:
        lines.append(f"淨盈虧比 {signal['net_rr']}")
    lines.append("⚠️ 僅供訊號監控參考，非投資建議，本系統不會自動下單。")
    return "\n".join(lines)


async def send_signal_notification(client: httpx.AsyncClient, signal: dict) -> bool:
    """回傳是否真的送出。沒設定金鑰、或發送失敗都回傳 False——呼叫端不需要另外處理
    例外，這個函式自己吞掉所有失敗情況，通知只是附加功能，絕對不能拖垮主要分析流程。"""
    return await send_text(client, build_signal_message(signal))


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

    # 1) is_configured：兩個都要有值才算已設定
    _orig_token, _orig_chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "", ""
    check("no token/chat_id -> not configured", is_configured(), False)
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "abc123", ""
    check("token only, no chat_id -> not configured", is_configured(), False)
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "abc123", "999"
    check("both set -> configured", is_configured(), True)
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = _orig_token, _orig_chat  # 還原，避免汙染其他測試

    # 2) build_signal_message：組出來的文字要包含關鍵資訊
    sig = {
        "action": "🔥 強烈做多 (STRONG LONG)", "name": "BTC-USDT", "instId": "BTC-USDT-SWAP",
        "signal_type": "long", "price": 100.0, "stop_loss": 95.0,
        "take_profit_1": 107.5, "take_profit_2": 115.0, "net_rr": 1.45,
    }
    msg = build_signal_message(sig)
    check("message includes action label", "強烈做多" in msg, True)
    check("message includes instrument name", "BTC-USDT" in msg, True)
    check("message includes direction emoji", "🟢 做多" in msg, True)
    check("message includes entry price", "100.0" in msg, True)
    check("message includes stop_loss", "95.0" in msg, True)
    check("message includes net_rr when present", "淨盈虧比 1.45" in msg, True)
    check("message includes disclaimer", "非投資建議" in msg, True)

    # 3) short 方向的表情符號要對稱正確
    short_sig = {**sig, "signal_type": "short"}
    check("short signal shows 🔴 做空", "🔴 做空" in build_signal_message(short_sig), True)

    # 4) net_rr 不存在時（None）不該出現「淨盈虧比」那一行
    no_rr_sig = {k: v for k, v in sig.items() if k != "net_rr"}
    check("no net_rr field -> no 淨盈虧比 line", "淨盈虧比" in build_signal_message(no_rr_sig), False)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
