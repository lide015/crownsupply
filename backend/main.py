"""FastAPI app: REST + WebSocket + APScheduler + optional static frontend mount."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, okx_ws, scheduler
from .state import MANAGER, STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    row = db.get_latest_snapshot()
    if row:
        STATE.latest_snapshot = json.loads(row[1])
        STATE.last_fetch_ts = row[0]

    # prime the cache once at startup so /api/latest isn't empty for a full 60s
    await scheduler.job_fetch_klines()
    await scheduler.job_fetch_ohlc()
    await scheduler.job_fetch_fng()
    await scheduler.job_fetch_markets()
    await scheduler.job_fetch_quotes()

    sched = scheduler.create_scheduler()
    sched.start()
    logger.info("scheduler started")

    okx_task = asyncio.create_task(okx_ws.run_okx_ws_forever())
    logger.info("okx ws task started (M6)")

    try:
        yield
    finally:
        okx_task.cancel()
        sched.shutdown(wait=False)


app = FastAPI(title="jieliu-brief", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "last_fetch_ts": STATE.last_fetch_ts,
        "source": STATE.quote_source,
        "consecutive_failures": STATE.consecutive_failures,
    }


@app.get("/api/latest")
async def latest():
    if STATE.latest_snapshot is None:
        return {"ok": False, "message": "no data yet, waiting for first fetch cycle"}
    return STATE.latest_snapshot


@app.get("/api/history")
async def history(hours: int = 24):
    ts_from = int(time.time()) - hours * 3600
    rows = db.get_snapshots_since(ts_from, limit=720)
    return [json.loads(payload) for _ts, payload in rows]


@app.get("/api/klines")
async def klines(symbol: str = "BTC", days: int = 90):
    rows = db.get_closes(symbol.upper(), limit=days)
    return [{"day": day, "close": close} for day, close in rows]


@app.get("/api/smc")
async def smc_endpoint(symbol: str = "BTC"):
    return STATE.smc_cache


@app.get("/api/trade_plan")
async def trade_plan_endpoint(symbol: str = "BTC"):
    return STATE.trade_plan_cache


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await MANAGER.connect(websocket)
    if STATE.latest_snapshot is not None:
        await websocket.send_text(json.dumps(STATE.latest_snapshot))
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "heartbeat", "ts": int(time.time())}))
    except WebSocketDisconnect:
        pass
    finally:
        await MANAGER.disconnect(websocket)


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
