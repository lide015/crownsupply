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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai_coach, background, config, db, position_sizing
from .state import STATE


class CoachMessage(BaseModel):
    role: str
    content: str


class CoachRequest(BaseModel):
    node: dict
    history: list[CoachMessage]


class PositionSizeRequest(BaseModel):
    account_balance: float
    risk_pct: float
    entry_price: float
    stop_loss_price: float
    leverage_cap: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

INDEX_HTML = Path(__file__).resolve().parent / "index.html"
STATIC_DIR = Path(__file__).resolve().parent / "static"

_http_client: httpx.AsyncClient | None = None
_analyze_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    db.init_db()  # 訊號歷史／自動優化參數的 SQLite（見 db.py），純本地檔案，不連網
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

if STATIC_DIR.is_dir():
    # 自己編譯好的 Tailwind CSS（見 README「前端樣式」），不再依賴 cdn.tailwindcss.com——
    # 那個 CDN 版本是 Tailwind 官方自己都說「僅供原型測試」的執行期 JIT script，會在頁面
    # 載入當下才連網編譯樣式，網路較嚴（防火牆/某些地區）連不上就整頁沒有樣式。
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
        "win_rate_stats": STATE.win_rate_stats,
        "recent_resolved": STATE.recent_resolved,
        "tuning_note": STATE.tuning_note,
        "effective_min_amplitude_pct": STATE.effective_min_amplitude_pct,
        "market_pulse": STATE.market_pulse,
        "ranking": STATE.ranking,
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


@app.post("/api/v1/position-size")
async def position_size(req: PositionSizeRequest):
    """🧮 倉位計算機：純本地計算，不打任何外部 API、零成本，可以放心即時呼叫（前端用
    debounce 節流只是為了操作體驗，不是因為這個端點有任何用量疑慮）。公式只寫一份在
    position_sizing.py，前後端不會各寫一份、日後改一邊忘記改另一邊而兜不起來。"""
    result = position_sizing.calc_position_size(
        req.account_balance, req.risk_pct, req.entry_price, req.stop_loss_price, req.leverage_cap
    )
    if result is None:
        return JSONResponse(
            {"ok": False, "message": "輸入不合理：資金/風險%/價格需為正數，且進場價不能等於停損價。"},
            status_code=400,
        )
    if req.take_profit_1 is not None:
        result["reward_at_tp1"] = position_sizing.calc_reward_at_target(
            result["position_size"], req.entry_price, req.take_profit_1
        )
    if req.take_profit_2 is not None:
        result["reward_at_tp2"] = position_sizing.calc_reward_at_target(
            result["position_size"], req.entry_price, req.take_profit_2
        )
    return {"ok": True, **result}


@app.post("/api/v1/coach")
async def coach(req: CoachRequest):
    """AI 辯論空間：每次呼叫都要帶完整對話歷史（無狀態，見 ai_coach.py 說明），不會存進
    任何資料庫。回傳 {"reply": str|None, "error": str|None}。"""
    assert _http_client is not None
    history = [{"role": m.role, "content": m.content} for m in req.history]
    return await ai_coach.debate_turn(_http_client, req.node, history)


@app.get("/", response_class=HTMLResponse)
async def index():
    if INDEX_HTML.is_file():
        return INDEX_HTML.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"
