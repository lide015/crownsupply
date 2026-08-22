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
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai_coach, background, config, db, news_client, okx_client, position_sizing, stock_fundamentals
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


class AnalyzeInstrumentRequest(BaseModel):
    inst_id: str

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

INDEX_HTML = Path(__file__).resolve().parent / "index.html"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 開機時讀「一次」存進記憶體，之後每次 GET / 都直接回傳這份快取，不再每個請求都重新讀硬碟。
# 這不只是效能考量：Python 的 asyncio 是單執行緒事件迴圈，任何一個請求處理常式裡的同步
# 阻塞檔案讀取，都會卡住「整個」伺服器（不只卡住這一個請求）。專案資料夾如果剛好放在
# OneDrive/Dropbox 這類雲端同步資料夾裡，同步中的檔案鎖定就可能讓 read_text() 卡住不動，
# 表現起來就像伺服器完全沒回應（連 /api/v1/health 這種完全不碰檔案的端點都連不上）——
# 這裡先把 index.html 快取掉，消除這個請求路徑上唯一一處逐請求的同步磁碟 I/O。
_INDEX_HTML_CONTENT = (
    INDEX_HTML.read_text(encoding="utf-8") if INDEX_HTML.is_file() else "<h1>index.html not found</h1>"
)

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
        "all_instruments": STATE.all_instruments,
        "signals": STATE.signals,
        "last_error": STATE.last_error,
        "win_rate_stats": STATE.win_rate_stats,
        "recent_resolved": STATE.recent_resolved,
        "kelly_suggestion": STATE.kelly_suggestion,
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


@app.post("/api/v1/analyze-instrument")
async def analyze_instrument(req: AnalyzeInstrumentRequest):
    """🔍「全部商品總覽」裡任一檔按需求做完整分析（K線→EMA/突破訊號→OI→這檔專屬新聞→多空
    共振），不用等下一輪「立即分析」重新篩選全部商品才看得到。跟自動篩選出的 TOP_N 走
    同一套邏輯（background.analyze_one_instrument），結果一樣會記錄進訊號歷史、參與勝率
    追蹤——不管是系統自動選中的還是你自己點的，標準一致。

    只針對「這一檔」多打一次小小的 AI 呼叫（不是重新分析全部商品），用量可控。"""
    item = next((i for i in STATE.all_instruments if i["instId"] == req.inst_id), None)
    if item is None:
        return JSONResponse(
            {"ok": False, "message": "找不到這個商品——可能還沒按過「立即分析」抓取商品清單，或代號不存在。"},
            status_code=404,
        )

    assert _http_client is not None
    now_ms = int(time.time() * 1000)
    news = await news_client.get_market_and_instrument_sentiment(
        _http_client,
        [{"instId": item["instId"], "query": item["instId"].split("-")[0], "label": item["name"]}],
    )
    sentiment = news["by_instrument"].get(item["instId"], news["market"])
    signal, _candles = await background.analyze_one_instrument(_http_client, item, sentiment, now_ms)
    if signal is None:
        return JSONResponse(
            {"ok": False, "message": "這檔商品目前抓不到 K 線資料，稍後再試一次。"}, status_code=502
        )

    # 併入目前的訊號清單：同一個 instId 已存在就覆蓋掉舊的，不會重複顯示兩張卡片。
    STATE.signals = [s for s in STATE.signals if s["instId"] != signal["instId"]] + [signal]
    return {"ok": True, "signal": signal}


@app.get("/api/v1/instrument/{inst_id}")
async def instrument_detail(inst_id: str):
    """單一商品詳情頁：基本資料 + 事件時間軸，**不呼叫 AI、零額外成本**——只是把已經有的
    資料（this 輪抓到的報價、如果已分析過的技術指標、資料庫裡這檔商品過去的訊號紀錄，
    美股代幣再加公司基本面）整理成一份完整回應。想要真正的技術分析／AI 新聞情緒，
    前端會在這個詳情頁裡另外提供「執行完整分析」按鈕去打 POST /api/v1/analyze-instrument
    （那支才會真的呼叫一次 AI），瀏覽詳情頁本身不會平白多花一次 AI 額度。"""
    item = next((i for i in STATE.all_instruments if i["instId"] == inst_id), None)
    if item is None:
        return JSONResponse(
            {"ok": False, "message": "找不到這個商品——可能還沒按過「立即分析」抓取商品清單，或代號不存在。"},
            status_code=404,
        )

    signal = next((s for s in STATE.signals if s["instId"] == inst_id), None)
    history = db.get_signal_history_for(inst_id, limit=10)

    fundamentals = None
    ticker = okx_client.stock_ticker(inst_id)
    if ticker and config.FINNHUB_API_KEY:
        assert _http_client is not None
        fundamentals = await stock_fundamentals.fetch_company_profile(
            _http_client, ticker, config.FINNHUB_API_KEY
        )

    return {
        "ok": True,
        "basic": item,
        "signal": signal,
        "history": history,
        "fundamentals": fundamentals,
        "fundamentals_available": bool(config.FINNHUB_API_KEY),
    }


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
    """回傳開機時就讀好、存在記憶體裡的內容（見上方 _INDEX_HTML_CONTENT），不逐請求碰硬碟。"""
    return _INDEX_HTML_CONTENT
