"""AI 辯論空間：使用者針對某張知識卡的內容跟 AI 來回辯論（不是單次問答），AI 扮演一個
「有觀點、但講得通就會被說服」的教練角色。跟 news_client.py 走同一套 Anthropic（預設）/OpenAI
呼叫方式，沒有金鑰時優雅退回提示訊息，不會讓功能整個掛掉。

設計成無狀態：前端在瀏覽器記憶體裡保存這輪辯論的對話歷史，每次呼叫把完整歷史一起送過來，
後端不存任何東西。這樣做兩個理由：
1. 沒有接使用者登入（見 knowledge_universe/README.md「還沒做的事」），Supabase 的
   ai_coach_sessions 表 RLS policy 要求 auth.uid()，匿名呼叫本來就寫不進去。
2. 對話歷史留在使用者自己的瀏覽器分頁，重新整理就清空——避免累積誰都能讀的辯論紀錄。

有長度上限（MAX_HISTORY_MESSAGES）：辯論每來回一次都要把整段歷史重新送給 AI，愈辯論愈長、
這一次呼叫的 token 成本愈高，設上限強制「這輪辯論該收斂了」，避免無限累積燒 token。
"""
import logging

import httpx

from . import config

logger = logging.getLogger("ai_coach")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

MAX_HISTORY_MESSAGES = 16  # 使用者/AI 合計最多 16 則（8 個來回），超過請前端提示「開新的討論」
MAX_MESSAGE_CHARS = 500

COACH_SYSTEM_TEMPLATE = """你是一位嚴謹但願意被說服的交易/投資教練，正在跟學生辯論一個知識概念，
不是單純問答——要像真人辯論一樣有自己的觀點，但學生講得通的時候要明確承認，不要各打五十大板。

這次辯論圍繞的知識卡：
標題：{title}
分類：{category_label}
核心原理：{principle}
案例：{case_study}
常見錯誤：{common_mistakes}

規則：
- 用繁體中文回覆，控制在 150 字以內。
- 學生的論點有道理就明確承認；如果有邏輯漏洞或跟核心原理矛盾，指出來並解釋為什麼。
- 不用每次都重新自我介紹或複述知識卡內容，直接進入辯論。
- 這是教學討論，不是投資建議；如果學生把辯論結果當成具體的下單依據，要提醒一句。"""


def _build_system_prompt(node: dict) -> str:
    mistakes = "、".join(node.get("common_mistakes") or []) or "（無）"
    return COACH_SYSTEM_TEMPLATE.format(
        title=node.get("title", ""),
        category_label=node.get("category_label", ""),
        principle=node.get("principle", ""),
        case_study=node.get("case_study", ""),
        common_mistakes=mistakes,
    )


def _validate_history(history: list) -> str | None:
    """回傳錯誤訊息字串，或 None 代表沒問題。"""
    if not history:
        return "請先輸入一句話開始辯論。"
    if len(history) > MAX_HISTORY_MESSAGES:
        return f"這輪辯論已經有 {len(history)} 則訊息，有點長了——建議先開新的討論，避免無限累積。"
    if history[-1].get("role") != "user":
        return "最後一則訊息必須是使用者的發言。"
    for m in history:
        if m.get("role") not in ("user", "assistant"):
            return "訊息格式錯誤。"
        if len(m.get("content", "")) > MAX_MESSAGE_CHARS:
            return f"單則訊息請控制在 {MAX_MESSAGE_CHARS} 字以內。"
    return None


async def _call_anthropic(client: httpx.AsyncClient, system: str, history: list) -> str:
    resp = await client.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": config.ANTHROPIC_MODEL, "max_tokens": 300, "system": system, "messages": history},
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block.get("text", "") for block in data.get("content", [])).strip()


async def _call_openai(client: httpx.AsyncClient, system: str, history: list) -> str:
    resp = await client.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}", "content-type": "application/json"},
        json={
            "model": config.OPENAI_MODEL,
            "max_tokens": 300,
            "messages": [{"role": "system", "content": system}, *history],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _describe_error(exc: Exception) -> str:
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


async def debate_turn(client: httpx.AsyncClient, node: dict, history: list) -> dict:
    """history: [{"role": "user"|"assistant", "content": str}, ...]，最後一則必須是最新的使用者發言。
    回傳 {"reply": str|None, "error": str|None}；error 有值時 reply 一定是 None。"""
    error = _validate_history(history)
    if error:
        return {"reply": None, "error": error}

    if config.AI_PROVIDER == "none":
        return {"reply": None, "error": "AI_PROVIDER=none，AI 辯論空間目前停用。"}
    if config.AI_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        return {"reply": None, "error": "尚未設定 ANTHROPIC_API_KEY，請至 https://console.anthropic.com/settings/keys 建立金鑰後填入 .env。"}
    if config.AI_PROVIDER == "openai" and not config.OPENAI_API_KEY:
        return {"reply": None, "error": "尚未設定 OPENAI_API_KEY，請至 https://platform.openai.com/api-keys 建立金鑰後填入 .env。"}

    system = _build_system_prompt(node)
    try:
        if config.AI_PROVIDER == "openai":
            reply = await _call_openai(client, system, history)
        else:
            reply = await _call_anthropic(client, system, history)
    except Exception as exc:  # noqa: BLE001 — 呼叫失敗要讓使用者看到原因，不能整個 500
        logger.warning("ai_coach debate_turn failed: %s", exc)
        return {"reply": None, "error": f"AI 辯論空間暫時無法回應：{_describe_error(exc)}"}

    if not reply:
        return {"reply": None, "error": "AI 回覆是空的，請再試一次。"}
    return {"reply": reply, "error": None}


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

    node = {
        "title": "均線與趨勢判斷", "category_label": "技術面",
        "principle": "短週期均線在長週期均線之上代表偏多。",
        "case_study": "20MA 站上 60MA 且同步上揚。",
        "common_mistakes": ["把均線當精準訊號", "疊加太多條均線"],
    }

    prompt = _build_system_prompt(node)
    check("system prompt includes title", "均線與趨勢判斷" in prompt, True)
    check("system prompt includes joined mistakes", "把均線當精準訊號、疊加太多條均線" in prompt, True)

    check("empty history -> error", _validate_history([]), "請先輸入一句話開始辯論。")
    check(
        "last message not from user -> error",
        _validate_history([{"role": "assistant", "content": "hi"}]),
        "最後一則訊息必須是使用者的發言。",
    )
    check(
        "too many messages -> error",
        _validate_history([{"role": "user", "content": "x"}] * (MAX_HISTORY_MESSAGES + 1)) is not None,
        True,
    )
    check(
        "message too long -> error",
        _validate_history([{"role": "user", "content": "x" * (MAX_MESSAGE_CHARS + 1)}]) is not None,
        True,
    )
    check(
        "valid single-turn history -> no error",
        _validate_history([{"role": "user", "content": "為什麼要看兩條均線？"}]),
        None,
    )
    check(
        "valid multi-turn history -> no error",
        _validate_history([
            {"role": "user", "content": "為什麼要看兩條均線？"},
            {"role": "assistant", "content": "因為單一條均線容易被雜訊誤導。"},
            {"role": "user", "content": "那三條會更準嗎？"},
        ]),
        None,
    )

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
