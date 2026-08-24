"""死人開關監控（Dead Man's Switch）：如果你把背景排程（scheduler.py）開起來、長期跑在
自己的伺服器上，這支模組讓你知道「排程是不是還活著」，不用自己盯著 log 或定時手動檢查。

作法：每次排程觸發的分析輪跑完（不管成功或失敗），就對外 ping 一次設定好的網址。
用像 healthchecks.io 這種免費的第三方監控服務（也可以是任何自架的類似端點）——
邏輯很簡單：只要它在預期的時間內收到 ping，就代表「排程還活著」；超過時間沒收到，
它會主動發信/推播通知你「排程可能掛了」。這是「死人開關」思路：不是系統自己說
「我還活著」，而是外部第三方發現「太久沒聽到你的聲音」才是真正可信的失敗偵測——
如果伺服器整台當掉、Python 行程被 kill、網路斷線，系統自己是不可能通知你的。

healthchecks.io 的慣例：GET {base_url} 代表這一輪成功，GET {base_url}/fail 代表這一輪
失敗（讓你在 healthchecks.io 的介面上分得出「排程有跑但這輪分析出錯」跟「排程整個
沒在跑」這兩種不同情況）。沒設定 HEALTHCHECK_PING_URL（預設留空）就完全不會呼叫，
不影響任何其他功能——這是純選用的維運工具，不是本系統核心功能的一部分。

純函式（build_ping_url）+ 網路呼叫（ping）分離，方便單元測試——跟 funding_rate.py／
oi_tracker.py 同樣的設計。
"""
import logging

import httpx

logger = logging.getLogger("healthcheck")


def build_ping_url(base_url: str, success: bool = True) -> str:
    """組出實際要呼叫的網址。base_url 留空就回傳空字串（呼叫端據此判斷要不要跳過）。
    容忍 base_url 結尾多一個斜線（使用者複製貼上時常見），不會變成「.../fail」多一個
    重複斜線這種醜網址。"""
    base_url = (base_url or "").strip()
    if not base_url:
        return ""
    if success:
        return base_url
    return f"{base_url.rstrip('/')}/fail"


async def ping(client: httpx.AsyncClient, base_url: str, success: bool = True) -> bool:
    """對外 ping 一次。base_url 留空就直接回傳 False、不發任何請求（呼叫端不需要另外
    判斷「有沒有設定」，這裡已經處理）。任何網路例外都吞掉只記 log，絕對不能讓「監控
    本身掛了」連帶讓排程任務也失敗——這支模組的唯一職責是回報狀態，不該反過來影響
    它要監控的對象。"""
    url = build_ping_url(base_url, success)
    if not url:
        return False
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — 監控本身失敗只記 log，不能影響排程主流程
        logger.warning("healthcheck ping failed (url=%s, success=%s): %s", url, success, exc)
        return False


if __name__ == "__main__":
    _passed = 0
    _total = 0

    def check(name, actual, expected):
        global _passed, _total
        _total += 1
        ok = actual == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={actual!r} expected={expected!r}")
        if ok:
            _passed += 1

    # 1) 沒設定就回傳空字串
    check("empty base_url -> empty (disabled)", build_ping_url(""), "")
    check("None base_url -> empty (disabled)", build_ping_url(None), "")
    check("whitespace-only base_url -> empty (disabled)", build_ping_url("   "), "")

    # 2) 成功 ping 就是原網址本身
    check("success ping -> base_url unchanged", build_ping_url("https://hc-ping.com/abc123", True), "https://hc-ping.com/abc123")

    # 3) 失敗 ping 加上 /fail
    check("failure ping -> appends /fail", build_ping_url("https://hc-ping.com/abc123", False), "https://hc-ping.com/abc123/fail")

    # 4) 結尾多一個斜線也要處理乾淨，不要變成兩個斜線
    check("trailing slash handled cleanly on failure", build_ping_url("https://hc-ping.com/abc123/", False), "https://hc-ping.com/abc123/fail")
    check("trailing slash handled cleanly on success", build_ping_url("https://hc-ping.com/abc123/", True), "https://hc-ping.com/abc123/")

    # 5) 前後空白會被去掉
    check("leading/trailing whitespace stripped", build_ping_url("  https://hc-ping.com/abc123  ", True), "https://hc-ping.com/abc123")

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
