"""AI 新聞事件大腦：抓公開財經 RSS 頭條 → 丟給 LLM 判斷多空情緒。

- 新聞來源用公開 RSS（不用金鑰），LLM 走 Anthropic Claude（預設）或 OpenAI，看 config.AI_PROVIDER。
- 沒設定金鑰、AI_PROVIDER="none"、或呼叫失敗，一律優雅退回 NEUTRAL，絕不讓整個系統掛掉。
- 呼叫頻率由 background.py 控制（config.NEWS_REFRESH_SECONDS，預設 10 分鐘一次），避免每次
  前端輪詢儀表板都重新燒 AI token。
"""
import json
import logging
import re
from xml.etree import ElementTree

import httpx

from . import config

logger = logging.getLogger("news_client")

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SENTIMENT_PROMPT = (
    "你是加密貨幣總體經濟新聞分析師。請閱讀以下新聞標題，判斷對加密貨幣市場「整體」是"
    "BULLISH（利多）、BEARISH（利空）還是 NEUTRAL（中性／無明確方向），並用一句話（繁體中文）"
    "說明理由。只回傳嚴格 JSON，不要任何其他文字：\n"
    '{"sentiment": "BULLISH|BEARISH|NEUTRAL", "reason": "一句話理由"}\n\n新聞標題：\n'
)


async def fetch_headlines(client: httpx.AsyncClient, limit: int = 6) -> list[str]:
    headlines: list[str] = []
    for url in RSS_FEEDS:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.text)
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    headlines.append(title_el.text.strip())
                if len(headlines) >= limit:
                    break
        except Exception as exc:  # noqa: BLE001 — 單一新聞源失敗不影響其他來源
            logger.warning("RSS fetch failed for %s: %s", url, exc)
        if len(headlines) >= limit:
            break
    return headlines[:limit]


def _parse_sentiment_json(text: str) -> dict | None:
    """LLM 有時會把 JSON 包在 ```json ... ``` 或前後加廢話，這裡盡量寬容地撈出來。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    sentiment = str(parsed.get("sentiment", "")).upper()
    if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
        return None
    return {"sentiment": sentiment, "reason": str(parsed.get("reason", ""))[:300]}


async def _call_anthropic(client: httpx.AsyncClient, prompt: str) -> dict | None:
    resp = await client.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []))
    return _parse_sentiment_json(text)


async def _call_openai(client: httpx.AsyncClient, prompt: str) -> dict | None:
    resp = await client.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "content-type": "application/json",
        },
        json={
            "model": config.OPENAI_MODEL,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return _parse_sentiment_json(text)


def _describe_error(exc: Exception) -> str:
    """把 Anthropic/OpenAI 回傳的錯誤 JSON（例如額度不足、金鑰失效）轉成人看得懂的一句話，
    而不是丟一整包 httpx 的 HTTP 狀態碼字串給使用者。"""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
            message = body.get("error", {}).get("message") or body.get("message")
            if message:
                return f"{message}（HTTP {response.status_code}）"
        except ValueError:
            pass
    return str(exc)


def _no_ai_result(reason: str) -> dict:
    return {"sentiment": "NEUTRAL", "headline": "AI 新聞分析未啟用", "reason": reason}


async def get_market_sentiment(client: httpx.AsyncClient) -> dict:
    """回傳 {"sentiment": "BULLISH|BEARISH|NEUTRAL", "headline": str, "reason": str}。
    永遠不拋例外——任何失敗都退回 NEUTRAL 並附上原因，讓儀表板照常運作。"""
    if config.AI_PROVIDER == "none":
        return _no_ai_result("AI_PROVIDER=none，AI 新聞分析已停用，訊號僅供技術面參考。")
    if config.AI_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        return _no_ai_result(
            "尚未設定 ANTHROPIC_API_KEY，請至 https://console.anthropic.com/settings/keys 建立金鑰後填入 .env。"
        )
    if config.AI_PROVIDER == "openai" and not config.OPENAI_API_KEY:
        return _no_ai_result(
            "尚未設定 OPENAI_API_KEY，請至 https://platform.openai.com/api-keys 建立金鑰後填入 .env。"
        )

    try:
        headlines = await fetch_headlines(client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_headlines failed: %s", exc)
        headlines = []

    if not headlines:
        return {"sentiment": "NEUTRAL", "headline": "目前無法取得新聞頭條", "reason": "RSS 來源暫時無法連線"}

    prompt = SENTIMENT_PROMPT + "\n".join(f"- {h}" for h in headlines)

    try:
        if config.AI_PROVIDER == "openai":
            parsed = await _call_openai(client, prompt)
        else:
            parsed = await _call_anthropic(client, prompt)
    except Exception as exc:  # noqa: BLE001 — AI 呼叫失敗一樣優雅退回，不讓儀表板掛掉
        logger.warning("AI sentiment call failed: %s", exc)
        return {"sentiment": "NEUTRAL", "headline": headlines[0], "reason": f"AI 分析暫時失敗：{_describe_error(exc)}"}

    if not parsed:
        return {"sentiment": "NEUTRAL", "headline": headlines[0], "reason": "AI 回覆格式無法解析，暫以中性處理"}

    return {"sentiment": parsed["sentiment"], "headline": headlines[0], "reason": parsed["reason"]}


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

    # 1) 乾淨 JSON
    check(
        "parse clean JSON",
        _parse_sentiment_json('{"sentiment": "bullish", "reason": "Fed 降息"}'),
        {"sentiment": "BULLISH", "reason": "Fed 降息"},
    )
    # 2) 包在 ```json fence 裡
    fenced = '這是我的判斷：\n```json\n{"sentiment": "BEARISH", "reason": "監管疑慮"}\n```\n謝謝'
    check(
        "parse fenced JSON",
        _parse_sentiment_json(fenced),
        {"sentiment": "BEARISH", "reason": "監管疑慮"},
    )
    # 3) 無效內容 -> None
    check("invalid content -> None", _parse_sentiment_json("我不知道"), None)
    # 4) sentiment 值不在允許集合 -> None
    check(
        "unknown sentiment value -> None",
        _parse_sentiment_json('{"sentiment": "MOON", "reason": "x"}'),
        None,
    )

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
