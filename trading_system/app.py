"""獨立全端交易訊號平台 — FastAPI 後端進入點。

啟動：uvicorn trading_system.app:app --host 127.0.0.1 --port 8000
瀏覽器打開 http://127.0.0.1:8000 即可看到儀表板（本檔案直接把 index.html 掛在 "/"）。

⚠️ 本系統只產生「監控訊號」，不含任何下單/自動化交易邏輯，不會使用任何交易所 API 金鑰
去真正開倉、平倉、動用資金。所有輸出僅供研究與參考，不是投資建議。
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from . import background
from .state import STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

INDEX_HTML = Path(__file__).resolve().parent / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(background.run_forever())
    logger.info("background refresh loop started")
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Crypto Day-Trading Signal Brain", lifespan=lifespan)

# 單人本機工具，前端用 file:// 直接開也要能連，故全開放；沒有使用者系統、沒有敏感資料。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
async def health():
    return {"ok": True, "last_update": STATE.last_update, "last_error": STATE.last_error}


@app.get("/api/v1/dashboard")
async def dashboard():
    return {
        "last_update": STATE.last_update,
        "market_sentiment": STATE.market_sentiment,
        "news_headline": STATE.news_headline,
        "news_reason": STATE.news_reason,
        "monitored": STATE.monitored,
        "signals": STATE.signals,
        "disclaimer": "僅供訊號監控參考，非投資建議；本系統不執行任何自動化下單。",
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    if INDEX_HTML.is_file():
        return INDEX_HTML.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"
