"""訊號觸發通知：新產生的強烈多空共振訊號透過 Email 主動推播，補 Telegram
（telegram_notify.py）之外的另一個管道——有些人比較常看 Email、不是每個人都用 Telegram。

沒設定 SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/EMAIL_FROM/EMAIL_TO 時完全停用、優雅跳過，
不影響任何其他功能，跟這個系統其他所有可選功能的慣例一致。

⚠️ Python 標準庫的 `smtplib` 是同步阻塞 API，沒有原生 asyncio 版本——直接在 async 函式
裡呼叫會卡住整個伺服器的事件迴圈（這個系統其他地方已經因為類似的同步阻塞踩過坑，見
app.py 對 index.html 讀取快取的說明）。這裡用 `asyncio.to_thread()` 把真正寄信的動作丟到
獨立執行緒跑，寄一封信的延遲不會卡住伺服器同時處理的其他請求。
"""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from . import config

logger = logging.getLogger("email_notify")


def is_configured() -> bool:
    return bool(
        config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD
        and config.EMAIL_FROM and config.EMAIL_TO
    )


def build_signal_email(signal: dict) -> tuple[str, str]:
    """回傳 (subject, body)。純函式、不牽涉網路，方便測試——跟 telegram_notify.py 的
    build_signal_message 是同一份資訊，只是排成 Email 主旨/內文兩段。"""
    direction = "做多" if signal.get("signal_type") == "long" else "做空"
    name = signal.get("name", signal.get("instId", ""))
    subject = f"[Gold Trader LITE] {name} {direction}訊號：{signal.get('action', '')}"
    lines = [
        str(signal.get("action", "")),
        f"{name}　{direction}",
        f"開倉價 {signal.get('price')}",
        f"停損 {signal.get('stop_loss')}　停利1 {signal.get('take_profit_1')}　停利2 {signal.get('take_profit_2')}",
    ]
    if signal.get("net_rr") is not None:
        lines.append(f"淨盈虧比 {signal['net_rr']}")
    lines.append("")
    lines.append("⚠️ 僅供訊號監控參考，非投資建議，本系統不會自動下單。")
    return subject, "\n".join(lines)


def _send_smtp_blocking(subject: str, body: str) -> None:
    """真正會阻塞的那一段——連線、登入、寄信——丟進 asyncio.to_thread() 執行，不要
    直接在事件迴圈裡呼叫這個函式。"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO

    server = (
        smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
        if config.SMTP_USE_SSL
        else smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
    )
    try:
        if not config.SMTP_USE_SSL:
            server.starttls()
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.sendmail(config.EMAIL_FROM, [config.EMAIL_TO], msg.as_string())
    finally:
        server.quit()


async def send_text(subject: str, body: str) -> bool:
    """低階發送：純文字主旨/內文，訊號通知（send_signal_notification）跟警報
    （alerts.py／background.py）共用同一份發送邏輯。回傳是否真的送出；沒設定金鑰、或
    發送失敗都回傳 False，自己吞掉所有例外。"""
    if not is_configured():
        return False
    try:
        await asyncio.to_thread(_send_smtp_blocking, subject, body)
        return True
    except Exception as exc:  # noqa: BLE001 — 通知失敗不能讓分析流程掛掉
        logger.warning("Email notification failed: %s", exc)
        return False


async def send_signal_notification(signal: dict) -> bool:
    """回傳是否真的送出。沒設定金鑰、或發送失敗都回傳 False——呼叫端不需要另外處理
    例外，這個函式自己吞掉所有失敗情況，通知只是附加功能，絕對不能拖垮主要分析流程。"""
    subject, body = build_signal_email(signal)
    return await send_text(subject, body)


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

    # 1) is_configured：5 個欄位都要有值才算已設定
    _orig = (config.SMTP_HOST, config.SMTP_USERNAME, config.SMTP_PASSWORD, config.EMAIL_FROM, config.EMAIL_TO)
    config.SMTP_HOST = config.SMTP_USERNAME = config.SMTP_PASSWORD = config.EMAIL_FROM = config.EMAIL_TO = ""
    check("all empty -> not configured", is_configured(), False)
    config.SMTP_HOST, config.SMTP_USERNAME = "smtp.example.com", "me@example.com"
    check("only 2 of 5 fields set -> not configured", is_configured(), False)
    config.SMTP_PASSWORD, config.EMAIL_FROM, config.EMAIL_TO = "pw", "me@example.com", "target@example.com"
    check("all 5 fields set -> configured", is_configured(), True)
    (config.SMTP_HOST, config.SMTP_USERNAME, config.SMTP_PASSWORD, config.EMAIL_FROM, config.EMAIL_TO) = _orig  # 還原

    # 2) build_signal_email：主旨/內文要包含關鍵資訊
    sig = {
        "action": "🔥 強烈做多 (STRONG LONG)", "name": "BTC-USDT", "instId": "BTC-USDT-SWAP",
        "signal_type": "long", "price": 100.0, "stop_loss": 95.0,
        "take_profit_1": 107.5, "take_profit_2": 115.0, "net_rr": 1.45,
    }
    subject, body = build_signal_email(sig)
    check("subject includes instrument name", "BTC-USDT" in subject, True)
    check("subject includes direction", "做多" in subject, True)
    check("subject includes action label", "強烈做多" in subject, True)
    check("body includes entry price", "100.0" in body, True)
    check("body includes stop_loss", "95.0" in body, True)
    check("body includes net_rr when present", "淨盈虧比 1.45" in body, True)
    check("body includes disclaimer", "非投資建議" in body, True)

    # 3) short 方向對稱正確
    short_subject, short_body = build_signal_email({**sig, "signal_type": "short"})
    check("short signal subject shows 做空", "做空" in short_subject, True)

    # 4) net_rr 不存在時（None）不該出現「淨盈虧比」那一行
    no_rr_sig = {k: v for k, v in sig.items() if k != "net_rr"}
    _, no_rr_body = build_signal_email(no_rr_sig)
    check("no net_rr field -> no 淨盈虧比 line", "淨盈虧比" in no_rr_body, False)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
