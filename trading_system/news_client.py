"""AI 新聞事件大腦：抓公開財經 RSS 頭條 → 丟給 LLM 判斷多空情緒。

- 新聞來源用公開 RSS（不用金鑰）：整體市場走 CoinDesk／CoinTelegraph；每個監控中的商品
  另外各自查一次 Google News RSS（同樣免費公開、不需金鑰），讓新聞判讀能對到「這檔」而不是
  只有一個套用到所有商品的籠統市場情緒——之前的版本不管訊號是哪一檔，AI 新聞情緒一律引用
  同一份「整體市場」判斷，BTC 的新聞跟一檔完全不相干的小幣訊號會顯示一模一樣的理由，這是
  不準確的；現在每檔訊號的「大腦研判」會引用真正提到那檔商品的新聞（沒查到專屬新聞才老實
  說明「套用整體市場情緒」，不會假裝有專屬新聞）。
- LLM 走 Anthropic Claude（預設）或 OpenAI，看 config.AI_PROVIDER。
- 沒設定金鑰、AI_PROVIDER="none"、或呼叫失敗，一律優雅退回 NEUTRAL，絕不讓整個系統掛掉。
- **零額外 AI 成本**：不管監控幾檔商品，整體市場 + 逐檔判讀全部塞進同一次 AI 呼叫裡一次問完，
  不是每檔商品各打一次 AI（TOP_N 檔就要燒 TOP_N 倍 token）。
- 每次分析都是使用者主動按下「立即分析」的結果，所以每次都重新抓最新新聞、重新判斷情緒，
  不做時間快取節流——節流的意義在自動背景輪詢；手動觸發本身就已經是節流，資料本來就是即時的。
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

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SENTIMENT_PROMPT = (
    "你是加密貨幣總體經濟新聞分析師。請閱讀以下新聞標題，判斷對加密貨幣市場「整體」是"
    "BULLISH（利多）、BEARISH（利空）還是 NEUTRAL（中性／無明確方向），並用一句話（繁體中文）"
    "說明理由。只回傳嚴格 JSON，不要任何其他文字：\n"
    '{"sentiment": "BULLISH|BEARISH|NEUTRAL", "reason": "一句話理由"}\n\n新聞標題：\n'
)

MULTI_SENTIMENT_PROMPT_HEADER = (
    "你是加密貨幣/股票新聞分析師。以下先給「整體市場」新聞標題，再給每個標的各自搜尋到的\n"
    "專屬新聞標題（可能是空的）。請針對「整體市場」和「每一個標的」分別判斷 BULLISH（利多）、\n"
    "BEARISH（利空）、NEUTRAL（中性/無明確方向），並用一句話（繁體中文，**limit 40 字以內**）\n"
    "說明理由——標的的理由要具體指出關聯到哪一則專屬新聞，不要只重複「整體市場情緒」這種\n"
    "空話。如果某個標的完全沒有查到專屬新聞，該標的的 sentiment 請直接沿用整體市場判斷，\n"
    "reason 老實註明「沿用整體市場情緒」，不要編造不存在的新聞。\n"
    "**輸出格式要求：緊湊的單行 JSON，不要縮排、不要換行、不要 markdown code fence**，\n"
    "理由控制在 40 字以內是為了避免輸出被截斷。\n\n"
    "只回傳嚴格 JSON，不要任何其他文字，格式如下（<instId> 要跟輸入的標的清單完全一致）：\n"
    '{"market": {"sentiment": "BULLISH|BEARISH|NEUTRAL", "reason": "一句話理由"}, '
    '"instruments": {"<instId>": {"sentiment": "BULLISH|BEARISH|NEUTRAL", "reason": "一句話理由"}, ...}}\n\n'
)


async def fetch_headlines(client: httpx.AsyncClient, limit: int = 6) -> list[str]:
    """整體市場新聞（CoinDesk／CoinTelegraph RSS）。"""
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


async def fetch_instrument_headlines(client: httpx.AsyncClient, query: str, limit: int = 5) -> list[str]:
    """單一標的的專屬新聞（Google News RSS 搜尋，免費公開、不需金鑰）。查不到就回傳空
    list——呼叫端會老實顯示「沒有找到專屬新聞」並退回整體市場情緒，不會假裝有資料。"""
    try:
        resp = await client.get(
            GOOGLE_NEWS_RSS_URL,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.text)
        headlines = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                headlines.append(title_el.text.strip())
            if len(headlines) >= limit:
                break
        return headlines
    except Exception as exc:  # noqa: BLE001 — 單一標的查不到新聞不能拖垮整輪分析
        logger.warning("instrument headline fetch failed for %r: %s", query, exc)
        return []


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


def _build_multi_prompt(market_headlines: list[str], instrument_headlines: dict) -> str:
    """instrument_headlines: {inst_id: {"label": str, "headlines": list[str]}}，
    inst_id 的插入順序就是 prompt 裡出現的順序（Python dict 保序）。"""
    parts = [MULTI_SENTIMENT_PROMPT_HEADER, "整體市場新聞標題：\n"]
    if market_headlines:
        parts += [f"- {h}\n" for h in market_headlines]
    else:
        parts.append("（無）\n")

    parts.append("\n各標的專屬新聞標題：\n")
    for inst_id, info in instrument_headlines.items():
        parts.append(f"\n[{inst_id} / {info['label']}]\n")
        if info["headlines"]:
            parts += [f"- {h}\n" for h in info["headlines"]]
        else:
            parts.append("（無專屬新聞）\n")
    return "".join(parts)


def _salvage_market_only(text: str) -> dict | None:
    """完整 JSON 解析失敗時的退路：AI 回覆通常先寫 "market" 欄位、後面才逐一列出各標的，
    如果輸出中途被截斷（例如標的數量一多、超出 max_tokens），"market" 這個子物件本身
    往往還是完整的（沒有巢狀結構，只有 sentiment/reason 兩個字串），單獨撈出來解析，
    至少保住整體市場的判斷不要整包 None——退回「查不到這檔專屬新聞」比整個中性化更準確。"""
    match = re.search(r'"market"\s*:\s*(\{[^{}]*\})', text, re.DOTALL)
    if not match:
        return None
    try:
        market_raw = json.loads(match.group(1))
    except ValueError:
        return None
    sentiment = str(market_raw.get("sentiment", "")).upper()
    if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
        return None
    return {"market": {"sentiment": sentiment, "reason": str(market_raw.get("reason", ""))[:300]}, "instruments": {}}


def _parse_multi_sentiment_json(text: str) -> dict | None:
    """回傳 {"market": {"sentiment","reason"}, "instruments": {inst_id: {"sentiment","reason"}}}，
    market 格式不對就整包回傳 None；單一標的格式不對只排除那一檔，不影響其他標的跟 market
    （呼叫端對缺席的標的會 fallback 套用 market 的判斷，見 get_market_and_instrument_sentiment）。

    完整解析失敗時（常見原因是輸出被截斷，見 _salvage_market_only 說明）會退一步試著至少
    搶救出 market 欄位，而不是整包放棄、把每一檔都變成沒有理由的中性。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return _salvage_market_only(text)
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return _salvage_market_only(text)

    market_raw = parsed.get("market")
    if not isinstance(market_raw, dict):
        return None
    market_sentiment = str(market_raw.get("sentiment", "")).upper()
    if market_sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
        return None
    market = {"sentiment": market_sentiment, "reason": str(market_raw.get("reason", ""))[:300]}

    instruments = {}
    raw_instruments = parsed.get("instruments")
    if isinstance(raw_instruments, dict):
        for inst_id, entry in raw_instruments.items():
            if not isinstance(entry, dict):
                continue
            sentiment = str(entry.get("sentiment", "")).upper()
            if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
                continue
            instruments[inst_id] = {"sentiment": sentiment, "reason": str(entry.get("reason", ""))[:300]}

    return {"market": market, "instruments": instruments}


async def _call_anthropic_text(client: httpx.AsyncClient, prompt: str, max_tokens: int = 200) -> str:
    resp = await client.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block.get("text", "") for block in data.get("content", []))


async def _call_openai_text(client: httpx.AsyncClient, prompt: str, max_tokens: int = 200) -> str:
    resp = await client.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "content-type": "application/json",
        },
        json={
            "model": config.OPENAI_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


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


def _ai_disabled_reason() -> str | None:
    """AI 沒有可用金鑰/被停用時回傳原因字串；可以呼叫返回 None 代表 AI 正常可用。"""
    if config.AI_PROVIDER == "none":
        return "AI_PROVIDER=none，AI 新聞分析已停用，訊號僅供技術面參考。"
    if config.AI_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        return "尚未設定 ANTHROPIC_API_KEY，請至 https://console.anthropic.com/settings/keys 建立金鑰後填入 .env。"
    if config.AI_PROVIDER == "openai" and not config.OPENAI_API_KEY:
        return "尚未設定 OPENAI_API_KEY，請至 https://platform.openai.com/api-keys 建立金鑰後填入 .env。"
    return None


async def get_market_sentiment(client: httpx.AsyncClient) -> dict:
    """回傳 {"sentiment": "BULLISH|BEARISH|NEUTRAL", "headline": str, "reason": str}。
    永遠不拋例外——任何失敗都退回 NEUTRAL 並附上原因，讓儀表板照常運作。

    只判斷「整體市場」情緒，不分標的；`get_market_and_instrument_sentiment` 是加了逐檔
    判讀的版本，兩者互不呼叫對方，避免同一輪分析重複打兩次 AI。"""
    disabled_reason = _ai_disabled_reason()
    if disabled_reason:
        return _no_ai_result(disabled_reason)

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
            text = await _call_openai_text(client, prompt)
        else:
            text = await _call_anthropic_text(client, prompt)
        parsed = _parse_sentiment_json(text)
    except Exception as exc:  # noqa: BLE001 — AI 呼叫失敗一樣優雅退回，不讓儀表板掛掉
        logger.warning("AI sentiment call failed: %s", exc)
        return {"sentiment": "NEUTRAL", "headline": headlines[0], "reason": f"AI 分析暫時失敗：{_describe_error(exc)}"}

    if not parsed:
        return {"sentiment": "NEUTRAL", "headline": headlines[0], "reason": "AI 回覆格式無法解析，暫以中性處理"}

    return {"sentiment": parsed["sentiment"], "headline": headlines[0], "reason": parsed["reason"]}


async def get_market_and_instrument_sentiment(client: httpx.AsyncClient, instruments: list[dict]) -> dict:
    """整體市場情緒 + 逐檔標的新聞情緒，**一次 AI 呼叫**問完，不管 instruments 有幾檔。

    instruments: [{"instId": str, "query": str, "label": str}, ...]——query 是拿去搜尋
    Google News 的關鍵字（通常是基礎代號，例如 "BTC"、"TSLA"），label 是顯示用名稱。

    回傳 {"market": {...}, "by_instrument": {instId: {...}}, "status": str}——by_instrument
    對每一個傳入的 instId 都保證有值：查得到專屬新聞、AI 也判讀出來就用專屬的；查不到新聞、
    AI 停用、或呼叫失敗，一律 fallback 套用 market 的判斷，呼叫端不用另外處理「這檔沒資料」
    的分支。

    "status" 給背景排程模式的 AI 用量治理用（見 ai_governor.py／scheduler.py）：
    "disabled"（AI 沒設定/停用，不算失敗，不該累計進連續失敗斷路器）、"no_headlines"
    （抓不到任何新聞，不是 AI 本身的錯，同樣不算失敗）、"error"（AI 呼叫或解析真的失敗，
    這個才該累計進連續失敗斷路器）、"ok"（AI 正常回應）。手動「立即分析」流程目前不讀
    這個欄位，純粹是附加資訊，不影響既有呼叫端的行為。
    """
    disabled_reason = _ai_disabled_reason()
    if disabled_reason:
        market = _no_ai_result(disabled_reason)
        return {"market": market, "by_instrument": {i["instId"]: market for i in instruments}, "status": "disabled"}

    try:
        market_headlines = await fetch_headlines(client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_headlines failed: %s", exc)
        market_headlines = []

    instrument_headlines = {}
    for inst in instruments:
        try:
            heads = await fetch_instrument_headlines(client, inst["query"])
        except Exception as exc:  # noqa: BLE001 — 單一標的失敗不能拖垮其他標的的新聞判讀
            logger.warning("instrument headline fetch failed for %s: %s", inst["instId"], exc)
            heads = []
        instrument_headlines[inst["instId"]] = {"label": inst["label"], "headlines": heads}

    has_any_headline = bool(market_headlines) or any(v["headlines"] for v in instrument_headlines.values())
    if not has_any_headline:
        fallback = {"sentiment": "NEUTRAL", "headline": "目前無法取得新聞頭條", "reason": "RSS 來源暫時無法連線"}
        return {"market": fallback, "by_instrument": {i["instId"]: fallback for i in instruments}, "status": "no_headlines"}

    prompt = _build_multi_prompt(market_headlines, instrument_headlines)
    # 每個標的的 JSON 條目（含 key、標點、40 字中文理由）實際觀察起來比原本抓的還要長，
    # 太緊的預算會讓輸出中途被截斷、變成無法解析的 JSON——寧可預留寬裕一點的用量。
    max_tokens = min(500 + 250 * len(instruments), 4000)

    try:
        if config.AI_PROVIDER == "openai":
            text = await _call_openai_text(client, prompt, max_tokens=max_tokens)
        else:
            text = await _call_anthropic_text(client, prompt, max_tokens=max_tokens)
        parsed = _parse_multi_sentiment_json(text)
    except Exception as exc:  # noqa: BLE001 — AI 呼叫失敗一樣優雅退回，不讓儀表板掛掉
        logger.warning("AI multi-sentiment call failed: %s", exc)
        market_headline = market_headlines[0] if market_headlines else "（無整體市場新聞）"
        fallback = {"sentiment": "NEUTRAL", "headline": market_headline, "reason": f"AI 分析暫時失敗：{_describe_error(exc)}"}
        return {"market": fallback, "by_instrument": {i["instId"]: fallback for i in instruments}, "status": "error"}

    if not parsed:
        market_headline = market_headlines[0] if market_headlines else "（無整體市場新聞）"
        fallback = {"sentiment": "NEUTRAL", "headline": market_headline, "reason": "AI 回覆格式無法解析，暫以中性處理"}
        return {"market": fallback, "by_instrument": {i["instId"]: fallback for i in instruments}, "status": "error"}

    market_headline = market_headlines[0] if market_headlines else "（無整體市場新聞）"
    market = {"sentiment": parsed["market"]["sentiment"], "headline": market_headline, "reason": parsed["market"]["reason"]}

    by_instrument = {}
    for inst in instruments:
        inst_id = inst["instId"]
        entry = parsed["instruments"].get(inst_id)
        info = instrument_headlines[inst_id]
        if entry and info["headlines"]:
            by_instrument[inst_id] = {"sentiment": entry["sentiment"], "headline": info["headlines"][0], "reason": entry["reason"]}
        else:
            # AI 沒回傳這檔、或這檔本來就沒查到專屬新聞 —— 一律老實 fallback 成整體市場判斷。
            by_instrument[inst_id] = {
                "sentiment": market["sentiment"],
                "headline": market["headline"],
                "reason": "沒有找到該標的專屬新聞，套用整體市場情緒。",
            }

    return {"market": market, "by_instrument": by_instrument, "status": "ok"}


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

    # 5) _build_multi_prompt：市場 + 逐檔標的都要出現在 prompt 裡
    prompt = _build_multi_prompt(
        ["Fed 降息", "ETF 資金流入創新高"],
        {
            "BTC-USDT-SWAP": {"label": "BTC-USDT", "headlines": ["Bitcoin ETF inflows surge"]},
            "XYZ-USDT-SWAP": {"label": "XYZ-USDT", "headlines": []},
        },
    )
    check("multi prompt includes market headline", "Fed 降息" in prompt, True)
    check("multi prompt includes instrument label", "BTC-USDT-SWAP / BTC-USDT" in prompt, True)
    check("multi prompt includes instrument headline", "Bitcoin ETF inflows surge" in prompt, True)
    check("multi prompt marks no-headline instrument", "（無專屬新聞）" in prompt, True)

    # 6) _build_multi_prompt：完全沒有市場新聞時的空狀態
    empty_prompt = _build_multi_prompt([], {})
    check("empty market headlines shows placeholder", "（無）" in empty_prompt, True)

    # 7) _parse_multi_sentiment_json：market 正常、其中一檔標的格式錯誤 -> 只排除那一檔
    multi_text = json.dumps({
        "market": {"sentiment": "bullish", "reason": "整體偏多"},
        "instruments": {
            "BTC-USDT-SWAP": {"sentiment": "BULLISH", "reason": "ETF 資金流入"},
            "BAD-USDT-SWAP": {"sentiment": "MOON", "reason": "無效值"},
        },
    })
    parsed_multi = _parse_multi_sentiment_json(multi_text)
    check("multi parse market ok", parsed_multi["market"]["sentiment"], "BULLISH")
    check("multi parse valid instrument kept", "BTC-USDT-SWAP" in parsed_multi["instruments"], True)
    check("multi parse invalid instrument excluded", "BAD-USDT-SWAP" in parsed_multi["instruments"], False)

    # 8) _parse_multi_sentiment_json：market 格式錯誤 -> 整包 None
    check(
        "multi parse missing market -> None",
        _parse_multi_sentiment_json('{"instruments": {}}'),
        None,
    )

    # 9) _parse_multi_sentiment_json：沒有 instruments 欄位也不該整包失敗，回傳空 dict
    market_only = _parse_multi_sentiment_json('{"market": {"sentiment": "NEUTRAL", "reason": "無明確方向"}}')
    check("multi parse missing instruments -> empty dict", market_only["instruments"], {})

    # 10) 輸出被截斷（超出 max_tokens 中途斷掉）時，_parse_multi_sentiment_json 應該退一步
    # 搶救出完整的 market 欄位，而不是整包放棄——這是實際觀察到的真實失敗模式修正。
    truncated = '{"market": {"sentiment": "BULLISH", "reason": "ETF 資金流入帶動大盤偏多"}, "instruments": {"BTC-USDT-SWAP": {"sentiment": "BULL'
    salvaged = _parse_multi_sentiment_json(truncated)
    check("truncated response salvages market sentiment", salvaged is not None and salvaged["market"]["sentiment"], "BULLISH")
    check("truncated response gives up on partial instruments (safer than guessing)", salvaged["instruments"], {})

    # 11) 徹底亂七八糟、market 也救不回來的情況 -> 老實回傳 None
    check("total garbage -> None", _parse_multi_sentiment_json("完全不是 JSON 的一段話"), None)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
