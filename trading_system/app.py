"""獨立全端交易訊號平台 — FastAPI 後端進入點。

啟動：uvicorn trading_system.app:app --host 127.0.0.1 --port 8000
瀏覽器打開 http://127.0.0.1:8000 即可看到儀表板（本檔案直接把 index.html 掛在 "/"）。

⚠️ 本系統只產生「監控訊號」，不含任何下單/自動化交易邏輯，不會使用任何交易所 API 金鑰
去真正開倉、平倉、動用資金。所有輸出僅供研究與參考，不是投資建議。

不會自動在背景輪詢：完全由使用者按下「立即分析」（POST /api/v1/analyze）觸發，
一次點擊對應一輪 OKX＋AI 呼叫，用量自己掌控。
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from . import background, config
from .state import STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

INDEX_HTML = Path(__file__).resolve().parent / "index.html"

_http_client: httpx.AsyncClient | None = None
_analyze_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    # 只是建立可重複使用的連線池，開機當下不打任何 OKX/AI API——完全被動，等按鈕觸發。
    _http_client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"})
    logger.info("http client ready, waiting for manual /api/v1/analyze trigger (no auto background polling)")
    try:
        yield
    finally:
        await _http_client.aclose()


app = FastAPI(title="Crypto Day-Trading Signal Brain", lifespan=lifespan)

# 單人本機工具，前端用 file:// 直接開也要能連，故全開放；沒有使用者系統、沒有敏感資料。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _dashboard_payload() -> dict:
    return {
        "last_update": STATE.last_update,
        "has_run": STATE.has_run,
        "is_analyzing": STATE.is_analyzing,
        "market_sentiment": STATE.market_sentiment,
        "news_headline": STATE.news_headline,
        "news_reason": STATE.news_reason,
        "monitored": STATE.monitored,
        "signals": STATE.signals,
        "last_error": STATE.last_error,
        "disclaimer": "僅供訊號監控參考，非投資建議；本系統不執行任何自動化下單，也不會自動在背景分析。",
    }


@app.get("/api/v1/config")
async def frontend_config():
    """給前端「知識宇宙」分頁用的公開設定——anon/publishable key 本來就設計成給前端直接
    使用，不是密鑰，這裡回傳完全沒有資安疑慮（真正的機密如 service role key 從不會出現在這）。"""
    return {"supabase_url": config.SUPABASE_URL, "supabase_anon_key": config.SUPABASE_ANON_KEY}


@app.get("/api/v1/health")
async def health():
    return {"ok": True, "last_update": STATE.last_update, "last_error": STATE.last_error}


@app.get("/api/v1/dashboard")
async def dashboard():
    """只讀最近一次「立即分析」的結果，不會觸發新的分析、不打任何外部 API。"""
    return _dashboard_payload()


@app.post("/api/v1/analyze")
async def analyze():
    """使用者按下「立即分析」時呼叫：跑一輪 OKX 篩選＋K線＋AI 新聞情緒，即時回傳結果。
    用 lock 擋掉短時間內重複點擊造成的同時兩輪請求（浪費 API 用量、且會互踩 STATE）。"""
    if _analyze_lock.locked():
        return JSONResponse({"ok": False, "message": "上一輪分析還在進行中，請稍候再試。"}, status_code=409)

    async with _analyze_lock:
        STATE.is_analyzing = True
        try:
            assert _http_client is not None
            await background.refresh_cycle(_http_client)
        finally:
            STATE.is_analyzing = False

    return _dashboard_payload()


@app.get("/", response_class=HTMLResponse)
async def index():
    if INDEX_HTML.is_file():
        return INDEX_HTML.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"
