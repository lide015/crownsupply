"""獨立全端交易訊號平台 — FastAPI 後端進入點。

啟動：uvicorn trading_system.app:app --host 127.0.0.1 --port 8000
瀏覽器打開 http://127.0.0.1:8000 即可看到儀表板（本檔案直接把 index.html 掛在 "/"）。

⚠️ 本系統只產生「監控訊號」，不含任何下單/自動化交易邏輯，不會使用任何交易所 API 金鑰
去真正開倉、平倉、動用資金。所有輸出僅供研究與參考，不是投資建議。

預設不會自動在背景輪詢做「分析」：技術訊號＋AI 新聞情緒完全由使用者按下「立即分析」
（POST /api/v1/analyze）觸發，一次點擊對應一輪 OKX＋AI 呼叫，用量自己掌控。
純報價（GET /api/v1/tickers）是例外：這是 OKX 免費公開的 ticker 資料，不牽涉 AI／
技術分析，前端按過一次「立即分析」之後會自動定時輪詢，讓「全部商品總覽」的價格/
成交額/振幅保持即時，跟「分析」的用量完全脫鉤。

**背景排程是選用功能，預設關閉**（見 scheduler.py／POST /api/v1/scheduler）：開啟後
會定時自動觸發跟「立即分析」一樣的分析，但規則大腦（技術面）每輪都跑、AI 新聞情緒則
由 ai_governor.py 決定要不要問（每日上限、連續失敗斷路器、優先給新訊號、預設每 N 輪
才問一次）——自動化不等於無上限燒 AI token。

**警報是選用功能**（見 alerts.py／POST /api/v1/alerts）：對特定商品自訂價格漲破/跌破
門檻、或新技術訊號出現時，透過 Telegram／Email 通知。價格警報／訊號警報都是每輪分析
（手動或已開啟的背景排程）的附加檢查，不是逐秒即時監控。
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai_coach, alerts, background, backtest, config, db, email_notify, news_client, okx_client, outcome_tracker, position_sizing, scheduler, stock_fundamentals, strategy, telegram_notify
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


class BacktestRequest(BaseModel):
    inst_id: str
    bar: str | None = None
    limit: int | None = None
    # 互動式參數回測實驗室用：不帶就用 config.py 的預設值，帶了就用這組覆蓋，方便使用者
    # 在網頁上直接試不同的 EMA週期/盒子回看根數/停利倍數/量能過濾門檻，即時比較回測結果。
    ema_period: int | None = None
    box_lookback: int | None = None
    tp1_rr: float | None = None
    tp2_rr: float | None = None
    volume_confirm_multiple: float | None = None


class BacktestAllRequest(BaseModel):
    bar: str | None = None
    limit: int | None = None


class BacktestSweepRequest(BaseModel):
    inst_id: str
    bar: str | None = None
    limit: int | None = None
    # ema_period 刻意不開放覆蓋——見 backtest.run_sweep 說明，這是策略品牌識別的核心參數，
    # 不納入掃描範圍。其餘三組參數不帶就用 backtest.py 內建的預設掃描範圍。
    box_lookback_options: list[int] | None = None
    tp_rr_options: list[list[float]] | None = None  # [[tp1_rr, tp2_rr], ...]
    volume_confirm_options: list[float] | None = None


class SchedulerConfigRequest(BaseModel):
    # 兩個欄位都選填：只想開關就只帶 enabled，只想調間隔就只帶 interval_seconds，
    # 兩個都帶就一次改好。不帶的欄位維持原樣。
    enabled: bool | None = None
    interval_seconds: int | None = None


class CreateAlertRequest(BaseModel):
    inst_id: str
    name: str | None = None
    alert_type: str
    threshold: float | None = None
    # 只有 price_above/price_below 有意義；signal 類型一律強制為 "repeating"（一次性
    # 訊號警報觸發完就不會再通知未來的新訊號，沒有意義，見 app.py 建立端點的說明）。
    repeat_mode: str | None = None
    channels: list[str]


class UpdateAlertRequest(BaseModel):
    enabled: bool


class SignalDecisionRequest(BaseModel):
    # None＝清除回「還沒表態」；db.set_signal_decision 會驗證非 None 值必須是
    # db.VALID_SIGNAL_DECISIONS 其中之一，無效值在那一層被拒絕（回 400）。
    decision: str | None = None

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
    # 背景排程任務一律建立（方便隨時用 POST /api/v1/scheduler 開啟），但預設是暫停狀態
    # （見 scheduler.start 說明）——開機當下同樣不會因為這一行多打任何 OKX/AI API。
    scheduler.start(_http_client, _analyze_lock)
    try:
        yield
    finally:
        scheduler.stop()
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


@app.get("/sw.js")
async def service_worker():
    """PWA 可安裝性用的 service worker（見 static/sw.js，不快取任何東西，純粹滿足瀏覽器
    的可安裝技術要求）。刻意從網站根目錄 /sw.js 服務，**不是**掛在 /static/sw.js 底下：
    瀏覽器規定 service worker 的控制範圍(scope)不能超出它自己所在的路徑，掛在 /static/
    底下就只能控制 /static/ 這個路徑本身，等於白註冊——manifest.json 裡 scope 設的是
    "/"，這裡的服務路徑要跟它對得起來。"""
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


def _dashboard_payload() -> dict:
    return {
        "last_update": STATE.last_update,
        "last_update_ms": STATE.last_update_ms,
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
        "circuit_breaker": STATE.circuit_breaker,
        "portfolio_exposure": STATE.portfolio_exposure,
        "exposure_gate": STATE.exposure_gate,
        "scheduler": scheduler.status(),
        "disclaimer": "僅供訊號監控參考，非投資建議；本系統不執行任何自動化下單，也不會自動在背景分析。",
    }


@app.get("/api/v1/config")
async def frontend_config():
    """給前端用的公開設定——anon/publishable key 本來就設計成給前端直接使用，不是密鑰，
    這裡回傳完全沒有資安疑慮（真正的機密如 service role key 從不會出現在這）。
    也一併回傳目前生效的策略參數預設值，給「互動式參數回測實驗室」的表單預填初始值用，
    不用在前端另外寫死一份可能跟後端對不上的數字。"""
    return {
        "supabase_url": config.SUPABASE_URL,
        "supabase_anon_key": config.SUPABASE_ANON_KEY,
        "backtest_defaults": {
            "ema_period": config.EMA_PERIOD,
            "box_lookback": config.BOX_LOOKBACK,
            "tp1_rr": config.TP1_RR,
            "tp2_rr": config.TP2_RR,
            "volume_confirm_multiple": config.VOLUME_CONFIRM_MULTIPLE,
        },
        # 🔔 警報表單只顯示使用者實際能用的通知管道（沒設定金鑰的管道選了也送不到，
        # 不該讓使用者以為選了就有效），不是機密值，純布林旗標。
        "telegram_configured": telegram_notify.is_configured(),
        "email_configured": email_notify.is_configured(),
        # 📈 走勢圖時間週期切換鈕要知道哪個週期才是「跟訊號判斷同一份 EMA」，其餘週期
        # 純瀏覽參考——不能讓前端寫死猜一個可能跟後端環境變數對不上的值。
        "candle_bar": config.CANDLE_BAR,
        # 📦 曝險上限／🌪️ 波動風控門檻——給「持倉組合風險總覽」面板顯示「X / 上限 Y」用，
        # 實際攔截邏輯已經在後端 brain.fuse() 做了（見 outcome_tracker.compute_exposure_gate／
        # compute_volatility_gate），前端這裡純粹是把數字顯示出來，不重複判斷邏輯。
        "max_open_positions": config.MAX_OPEN_POSITIONS,
        "max_amplitude_pct": config.MAX_AMPLITUDE_PCT,
    }


@app.get("/api/v1/health")
async def health():
    return {"ok": True, "last_update": STATE.last_update, "last_error": STATE.last_error}


@app.get("/api/v1/dashboard")
async def dashboard():
    """只讀最近一次「立即分析」的結果，不會觸發新的分析、不打任何外部 API。"""
    return _dashboard_payload()


@app.get("/api/v1/tickers")
async def tickers_refresh():
    """輕量報價刷新：只抓 OKX 免費公開的 ticker（24h 價格／成交額／振幅／漲跌），
    **不**呼叫 AI、**不**重算技術訊號、**不**跟 /api/v1/analyze 搶同一把鎖——前端可以放心
    每隔幾秒自動輪詢（見 index.html 的 TICKER_POLL_MS），跟詳情頁K線走勢圖的定時刷新是
    同一種「零 AI 成本、純市場報價」精神，用量不會因為開著網頁不動就一直增加。

    只更新報價相關欄位（price/vol_usdt/amplitude_pct/change_pct），OI 欄位刻意沿用上一次
    「立即分析」抓到的值（見 okx_client.merge_fresh_quotes）——OI 有自己一套跟「上一輪快照」
    比較才有意義的邏輯，這裡輪詢週期短很多，直接覆蓋會把比較基準弄亂，等下一次「立即分析」
    才會重新算 OI 異動。使用者按過至少一次「立即分析」之前，all_instruments 是空的，
    前端不會呼叫這個端點（沒有東西可以刷新）。"""
    assert _http_client is not None
    try:
        tickers = await okx_client.fetch_swap_tickers(_http_client)
        fresh = okx_client.parse_instruments(tickers, config.EXTRA_INSTRUMENT_KEYWORDS, product_type="swap")
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"抓取即時報價失敗：{exc}"}, status_code=502)

    try:
        spot_tickers = await okx_client.fetch_spot_tickers(_http_client)
        fresh += okx_client.parse_instruments(spot_tickers, product_type="spot")
    except Exception as exc:  # noqa: BLE001 — 現貨報價只是附加瀏覽資料，抓不到不影響合約報價
        logger.warning("spot ticker refresh failed: %s", exc)

    STATE.all_instruments = okx_client.merge_fresh_quotes(STATE.all_instruments, fresh)
    return {"ok": True, "all_instruments": STATE.all_instruments, "updated_at": int(time.time() * 1000)}


@app.get("/api/v1/scheduler")
async def scheduler_status():
    """背景排程狀態面板：開關、間隔、上次／下次執行時間與結果、今日 AI 呼叫次數與上限、
    AI 連續失敗次數、這一輪 AI 有沒有被跳過及原因——一次看到，不用查伺服器 log。"""
    return {"ok": True, **scheduler.status()}


@app.post("/api/v1/scheduler")
async def scheduler_configure(req: SchedulerConfigRequest):
    """開啟／關閉背景排程，或調整間隔（實際套用的間隔會被強制夾到
    config.SCHEDULER_MIN_INTERVAL_SECONDS 以上，防止設太短變成失控迴圈）。設定存進
    SQLite，跨重啟持續生效，不用改 .env、不用重啟伺服器。"""
    now_ms = int(time.time() * 1000)
    if req.enabled is True:
        scheduler.enable(now_ms)
    elif req.enabled is False:
        scheduler.disable(now_ms)
    if req.interval_seconds is not None:
        scheduler.update_interval(req.interval_seconds, now_ms)
    return {"ok": True, **scheduler.status()}


@app.get("/api/v1/alerts")
async def list_alerts():
    """🔔 警報清單，供管理面板用。零 AI 成本，純讀資料庫。"""
    return {"ok": True, "alerts": db.get_alerts()}


@app.post("/api/v1/alerts")
async def create_alert_endpoint(req: CreateAlertRequest):
    """🔔 新增警報：對特定商品自訂價格漲破/跌破門檻、或新技術訊號出現的通知。⚠️ 不是逐秒
    即時監控——價格/訊號警報都是每輪分析（手動「立即分析」或已開啟的背景排程）的附加
    檢查，見 alerts.py 說明。"""
    if req.alert_type not in alerts.ALERT_TYPES:
        return JSONResponse({"ok": False, "message": f"不支援的警報類型：{req.alert_type}"}, status_code=400)
    if req.alert_type in ("price_above", "price_below") and req.threshold is None:
        return JSONResponse({"ok": False, "message": "價格警報需要填寫門檻價位。"}, status_code=400)
    if not req.channels:
        return JSONResponse({"ok": False, "message": "請至少選擇一個通知管道。"}, status_code=400)
    for ch in req.channels:
        if ch not in ("telegram", "email"):
            return JSONResponse({"ok": False, "message": f"不支援的通知管道：{ch}"}, status_code=400)
        if ch == "telegram" and not telegram_notify.is_configured():
            return JSONResponse({"ok": False, "message": "尚未設定 Telegram Bot，無法選擇這個管道。"}, status_code=400)
        if ch == "email" and not email_notify.is_configured():
            return JSONResponse({"ok": False, "message": "尚未設定 Email SMTP，無法選擇這個管道。"}, status_code=400)
    if db.count_alerts() >= config.ALERT_MAX_TOTAL:
        return JSONResponse(
            {"ok": False, "message": f"警報數量已達上限（{config.ALERT_MAX_TOTAL}），請先刪除不需要的警報。"},
            status_code=400,
        )

    # signal 類型的「一次性」沒有意義（觸發完就不會再通知未來的新訊號，等於警報形同虛設），
    # 一律強制成 repeating；price_* 類型才照使用者選的（不帶就預設 once，比較安全的預設值）。
    repeat_mode = "repeating" if req.alert_type == "signal" else (req.repeat_mode or "once")
    if repeat_mode not in ("once", "repeating"):
        return JSONResponse({"ok": False, "message": f"不支援的重複模式：{repeat_mode}"}, status_code=400)

    created = db.create_alert({
        "inst_id": req.inst_id,
        "name": req.name or req.inst_id,
        "alert_type": req.alert_type,
        "threshold": req.threshold,
        "repeat_mode": repeat_mode,
        "channels": req.channels,
        "created_at": int(time.time() * 1000),
    })
    return {"ok": True, "alert": created}


@app.patch("/api/v1/alerts/{alert_id}")
async def update_alert_endpoint(alert_id: int, req: UpdateAlertRequest):
    """🔔 啟用/停用一個既有警報（目前只支援這個欄位；改條件請刪除重建，管理面板刻意
    精簡，見 README）。"""
    ok = db.set_alert_enabled(alert_id, req.enabled)
    if not ok:
        return JSONResponse({"ok": False, "message": "找不到這個警報。"}, status_code=404)
    return {"ok": True}


@app.delete("/api/v1/alerts/{alert_id}")
async def delete_alert_endpoint(alert_id: int):
    ok = db.delete_alert(alert_id)
    if not ok:
        return JSONResponse({"ok": False, "message": "找不到這個警報。"}, status_code=404)
    return {"ok": True}


@app.patch("/api/v1/signals/{signal_id}/decision")
async def update_signal_decision(signal_id: int, req: SignalDecisionRequest):
    """✅ 訊號核准：使用者對一筆訊號自己標記「已核准/觀察中/拒絕」（或傳 decision=null
    清除回「還沒表態」）——純粹是給使用者自己回顧用的個人紀錄，本系統仍然**不會**因為
    標記「已核准」就真的去下單，見頁首的免責聲明。

    signal_id 是 signal_history 資料庫列的 id（見 background.analyze_one_instrument
    回傳的 signal dict 裡的 signal_history_id 欄位，不是 instId）。"""
    now_ms = int(time.time() * 1000)
    try:
        ok = db.set_signal_decision(signal_id, req.decision, now_ms)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    if not ok:
        return JSONResponse({"ok": False, "message": "找不到這筆訊號紀錄。"}, status_code=404)

    # 順手把目前記憶體裡正在顯示的訊號（STATE.signals）也同步更新，使用者馬上就能在
    # 畫面上看到標籤變化，不用等下一輪「立即分析」重新整理才對得上資料庫裡的值。
    for sig in STATE.signals:
        if sig.get("signal_history_id") == signal_id:
            sig["user_decision"] = req.decision
            break

    return {"ok": True, "decision": req.decision}


@app.post("/api/v1/analyze")
async def analyze():
    """使用者按下「立即分析」時呼叫：跑一輪 OKX 篩選＋K線＋AI 新聞情緒，即時回傳結果。
    用 lock 擋掉短時間內重複點擊造成的同時兩輪請求（浪費 API 用量、且會互踩 STATE）。
    不帶 skip_ai_reason，一律照舊呼叫 AI——手動點擊不受背景排程的用量治理限制（見
    background.refresh_cycle／ai_governor.py 說明）。"""
    if _analyze_lock.locked():
        return JSONResponse({"ok": False, "message": "上一輪分析還在進行中，請稍候再試。"}, status_code=409)

    async with _analyze_lock:
        STATE.is_analyzing = True
        try:
            assert _http_client is not None
            await background.refresh_cycle(_http_client)
        finally:
            STATE.is_analyzing = False

    # 手動「立即分析」一律重置背景排程的 AI 連續失敗斷路器計數（見 state.py 說明）：
    # 手動點擊不受這個斷路器限制，本身就是一次真實的 AI 呼叫嘗試，讓排程模式帶著乾淨的
    # 計數繼續——不管這次手動呼叫本身成功與否，都不該讓排程模式一直卡在使用者已經介入過
    # 的舊狀態裡。
    STATE.ai_consecutive_failures = 0

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
    # 每日虧損斷路器／曝險上限關卡都獨立算一次（純讀 DB，零成本）——這是使用者自己點的
    # 單一商品分析，不是走 `_refresh_signals` 那輪，一樣要套用同一個「現在」的風控狀態，
    # 標準不能兩套（見這支端點 docstring 說的「不管自動選中還是自己點的，標準一致」）。
    circuit_breaker = outcome_tracker.compute_daily_circuit_breaker(
        db.get_resolved_today(now_ms), config.MAX_DAILY_LOSS_COUNT, config.MAX_DAILY_LOSS_R
    )
    exposure_gate = outcome_tracker.compute_exposure_gate(
        outcome_tracker.compute_portfolio_exposure(db.get_open_signals())["total_open"], config.MAX_OPEN_POSITIONS
    )
    signal, _candles, _is_new = await background.analyze_one_instrument(
        _http_client, item, sentiment, now_ms, circuit_breaker, exposure_gate
    )
    if signal is None:
        return JSONResponse(
            {"ok": False, "message": "這檔商品目前抓不到 K 線資料，稍後再試一次。"}, status_code=502
        )

    # 併入目前的訊號清單：同一個 instId 已存在就覆蓋掉舊的，不會重複顯示兩張卡片。
    STATE.signals = [s for s in STATE.signals if s["instId"] != signal["instId"]] + [signal]
    return {"ok": True, "signal": signal}


@app.post("/api/v1/backtest")
async def run_backtest_endpoint(req: BacktestRequest):
    """📊 歷史回測：把 strategy.py 的規則套在這檔商品「已經發生過」的歷史 K 線上重播，
    統計勝率/獲利因子/最大連續虧損（見 backtest.py 說明）。不呼叫任何 AI，只多打一次
    免費的 OKX 歷史 K 線查詢——用量可控，讓使用者不用等 outcome_tracker 累積出足夠的
    「即時」樣本，就能先看到這套規則在過去一段歷史上表現如何。

    ema_period/box_lookback/tp1_rr/tp2_rr/volume_confirm_multiple 都可以在請求裡覆蓋
    掉 config.py 的預設值（互動式參數回測實驗室用）——不帶就照常用線上分析同一組參數。"""
    assert _http_client is not None
    bar = req.bar or config.CANDLE_BAR
    limit = min(req.limit or config.BACKTEST_CANDLE_LIMIT, config.BACKTEST_CANDLE_LIMIT)
    ema_period = req.ema_period or config.EMA_PERIOD
    box_lookback = req.box_lookback or config.BOX_LOOKBACK
    tp1_rr = req.tp1_rr or config.TP1_RR
    tp2_rr = req.tp2_rr or config.TP2_RR
    volume_confirm_multiple = req.volume_confirm_multiple if req.volume_confirm_multiple is not None else config.VOLUME_CONFIRM_MULTIPLE

    try:
        candles = await okx_client.fetch_confirmed_candles(_http_client, req.inst_id, bar=bar, limit=limit)
    except Exception as exc:  # noqa: BLE001 — 單一商品查不到不該讓整個端點掛掉
        return JSONResponse({"ok": False, "message": f"抓不到 {req.inst_id} 的歷史 K 線：{exc}"}, status_code=502)

    min_len = max(ema_period, box_lookback + 1)
    if len(candles) < min_len:
        return JSONResponse(
            {"ok": False, "message": f"這檔商品在 {bar} 週期只抓到 {len(candles)} 根已收盤K線，不夠跑一次完整的 EMA+盒子週期（至少要 {min_len} 根），換更長的K線週期再試一次。"},
            status_code=422,
        )

    result = backtest.run_backtest(candles, ema_period, box_lookback, tp1_rr, tp2_rr, volume_confirm_multiple)
    return {
        "ok": True, "inst_id": req.inst_id, "bar": bar, "candle_count": len(candles),
        "params": {
            "ema_period": ema_period, "box_lookback": box_lookback,
            "tp1_rr": tp1_rr, "tp2_rr": tp2_rr, "volume_confirm_multiple": volume_confirm_multiple,
        },
        **result,
    }


@app.post("/api/v1/backtest/sweep")
async def run_backtest_sweep_endpoint(req: BacktestSweepRequest):
    """🔬 參數掃描：同一批歷史K線，把 box_lookback／(tp1_rr,tp2_rr)／volume_confirm_multiple
    的多種組合各跑一次歷史回測（見 backtest.run_sweep 說明），依品質分數排序全部回傳——
    用真實歷史資料實測找出「這批資料上表現比較好」的參數，取代憑感覺猜測。不呼叫任何 AI，
    K線只多抓一次（限制、快取邏輯跟 /api/v1/backtest 完全一致），掃描本身純粹是記憶體裡的
    運算，不會額外打 OKX API。

    額外回傳 baseline：用「現在系統實際在用」的 config.py 預設參數，對同一批K線跑一次
    單組回測——讓使用者可以直接對照「掃描出來的最佳組合」相對於「現在的預設值」到底差多少，
    不是只丟一個孤立的排行榜自己去猜。"""
    assert _http_client is not None
    bar = req.bar or config.CANDLE_BAR
    limit = min(req.limit or config.BACKTEST_CANDLE_LIMIT, config.BACKTEST_CANDLE_LIMIT)
    ema_period = config.EMA_PERIOD

    box_lookback_options = tuple(req.box_lookback_options) if req.box_lookback_options else backtest.DEFAULT_SWEEP_BOX_LOOKBACKS
    tp_rr_options = tuple(tuple(pair) for pair in req.tp_rr_options) if req.tp_rr_options else backtest.DEFAULT_SWEEP_TP_RR_PAIRS
    volume_confirm_options = tuple(req.volume_confirm_options) if req.volume_confirm_options else backtest.DEFAULT_SWEEP_VOLUME_CONFIRM_MULTIPLES

    # 防呆：使用者自訂範圍太大時，組合數可能爆炸（例如各帶 50 個選項就是 12.5 萬組）——
    # 明確拒絕並說清楚上限是多少，不要讓一次請求把伺服器卡住半天，也不是默默截斷、讓使用者
    # 誤以為掃描了完整範圍。
    combo_count = len(box_lookback_options) * len(tp_rr_options) * len(volume_confirm_options)
    max_combos = 500
    if combo_count > max_combos:
        return JSONResponse(
            {"ok": False, "message": f"參數組合數 {combo_count} 超過上限 {max_combos}，請縮小 box_lookback_options／tp_rr_options／volume_confirm_options 的範圍再試一次。"},
            status_code=422,
        )

    try:
        candles = await okx_client.fetch_confirmed_candles(_http_client, req.inst_id, bar=bar, limit=limit)
    except Exception as exc:  # noqa: BLE001 — 單一商品查不到不該讓整個端點掛掉
        return JSONResponse({"ok": False, "message": f"抓不到 {req.inst_id} 的歷史 K 線：{exc}"}, status_code=502)

    min_len = max(ema_period, max(box_lookback_options) + 1)
    if len(candles) < min_len:
        return JSONResponse(
            {"ok": False, "message": f"這檔商品在 {bar} 週期只抓到 {len(candles)} 根已收盤K線，不夠跑掃描範圍裡最長的 box_lookback（至少要 {min_len} 根），換更長的K線週期或縮小掃描範圍再試一次。"},
            status_code=422,
        )

    baseline = backtest.run_backtest(
        candles, config.EMA_PERIOD, config.BOX_LOOKBACK, config.TP1_RR, config.TP2_RR, config.VOLUME_CONFIRM_MULTIPLE,
    )
    sweep = backtest.run_sweep(candles, ema_period, box_lookback_options, tp_rr_options, volume_confirm_options)

    return {
        "ok": True, "inst_id": req.inst_id, "bar": bar, "candle_count": len(candles),
        "baseline": {
            "params": {
                "ema_period": config.EMA_PERIOD, "box_lookback": config.BOX_LOOKBACK,
                "tp1_rr": config.TP1_RR, "tp2_rr": config.TP2_RR,
                "volume_confirm_multiple": config.VOLUME_CONFIRM_MULTIPLE,
            },
            "total_trades": baseline["total_trades"], "win_rate_pct": baseline["win_rate_pct"],
            "avg_r_multiple": baseline["avg_r_multiple"], "max_consecutive_losses": baseline["max_consecutive_losses"],
            "profit_factor": baseline["profit_factor"],
        },
        **sweep,
    }


@app.post("/api/v1/backtest-all")
async def run_backtest_all_endpoint(req: BacktestAllRequest):
    """📊 批次回測排行榜：對目前監控清單（`STATE.monitored`，自動篩選出的 TOP_N 檔）
    逐一跑歷史回測，依獲利因子排序，一次看出「這套策略在哪些商品歷史表現最好」。

    刻意**不是**對「全部商品總覽」（可能兩三百檔）跑，只對監控清單那幾檔——監控清單
    本來就是通過成交額/振幅門檻篩選過的，回測這幾檔才有意義；全部商品一起跑不但慢，
    大多數商品也早就被篩選機制排除在外，回測意義不大。單一商品查不到K線就跳過，不讓
    一檔失敗擋住其他商品的結果。"""
    assert _http_client is not None
    if not STATE.monitored:
        return {"ok": True, "results": [], "message": "目前沒有監控中的商品，請先按「立即分析」跑一輪。"}

    bar = req.bar or config.CANDLE_BAR
    limit = min(req.limit or config.BACKTEST_CANDLE_LIMIT, config.BACKTEST_CANDLE_LIMIT)
    min_len = max(config.EMA_PERIOD, config.BOX_LOOKBACK + 1)

    results = []
    for item in STATE.monitored:
        inst_id = item["instId"]
        try:
            candles = await okx_client.fetch_confirmed_candles(_http_client, inst_id, bar=bar, limit=limit)
        except Exception as exc:  # noqa: BLE001 — 單一商品失敗不能拖垮整個排行榜
            logger.warning("batch backtest candle fetch failed for %s: %s", inst_id, exc)
            continue
        if len(candles) < min_len:
            continue
        result = backtest.run_backtest(
            candles, config.EMA_PERIOD, config.BOX_LOOKBACK, config.TP1_RR, config.TP2_RR,
            config.VOLUME_CONFIRM_MULTIPLE,
        )
        if result["total_trades"] == 0:
            continue
        results.append({"inst_id": inst_id, "name": item["name"], "candle_count": len(candles), **result})

    # 依獲利因子排序：沒有虧損交易（profit_factor=None）理論上表現最好，排最前面；
    # 其餘依獲利因子由高到低排序。樣本數可能偏少，前端會另外顯示交易次數讓使用者自己
    # 判斷參考價值，不會讓「剛好一筆全勝」的商品看起來比「10筆穩定正期望值」更可信。
    def _sort_key(r):
        pf = r["profit_factor"]
        return (0, 0.0) if pf is None else (1, -pf)

    results.sort(key=_sort_key)
    return {"ok": True, "bar": bar, "results": results}


@app.get("/api/v1/candles/{inst_id}")
async def get_candles(inst_id: str, bar: str | None = None, limit: int | None = None, ema_period: int | None = None):
    """📈 K線走勢圖資料，零 AI 成本，只是把 OKX 免費公開的歷史 K 線包一層給前端畫圖用。

    bar/limit **預設直接沿用 config.CANDLE_BAR/EMA_PERIOD**（前端也預設不特地覆蓋這兩個
    值）——這是刻意的選擇：走勢圖上疊加的 EMA 線，要跟「技術分析結果」顯示的 20 EMA
    是同一個週期算出來的同一個數字，兩邊如果用不同的K線週期（例如圖表用1分鐘、訊號判斷
    用5分鐘），畫出來的 EMA 線會跟真正驅動訊號的那條線對不上，可能誤導使用者——這正是
    「重點資訊要正確」的核心，寧可犧牲一點「畫面感覺更即時」，也不要顯示兩個標籤都叫
    「20 EMA」卻其實是不同東西的數字。"""
    assert _http_client is not None
    bar_ = bar or config.CANDLE_BAR
    limit_ = min(limit or config.BACKTEST_CANDLE_LIMIT, config.BACKTEST_CANDLE_LIMIT)
    ema_period_ = ema_period or config.EMA_PERIOD
    try:
        candles = await okx_client.fetch_confirmed_candles(_http_client, inst_id, bar=bar_, limit=limit_)
    except Exception as exc:  # noqa: BLE001 — 單一商品查不到不該讓整個端點掛掉
        return JSONResponse({"ok": False, "message": f"抓不到 {inst_id} 的K線：{exc}"}, status_code=502)
    ema_series = strategy.compute_ema_series(candles, ema_period_)
    return {
        "ok": True, "inst_id": inst_id, "bar": bar_, "candles": candles,
        "ema_period": ema_period_, "ema_series": ema_series,
    }


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
