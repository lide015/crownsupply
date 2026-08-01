"""M6: OKX public WebSocket — direct real-time price ticks pushed straight to the frontend.
Supplementary to the 60s CoinGecko/OKX-REST snapshot pipeline (unchanged); does not touch
snapshots/db/indicators. Uses `websockets`, already installed transitively via
uvicorn[standard] — no new top-level dependency.
"""
import asyncio
import json
import logging

import websockets

from .state import MANAGER, STATE

logger = logging.getLogger("okx_ws")

OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_INST = {"BTC-USDT": "BTC", "ETH-USDT": "ETH", "SOL-USDT": "SOL", "BNB-USDT": "BNB"}

RECONNECT_BACKOFF_START = 2
RECONNECT_BACKOFF_MAX = 60
KEEPALIVE_SECONDS = 20


async def run_okx_ws_forever():
    backoff = RECONNECT_BACKOFF_START
    while True:
        try:
            async with websockets.connect(OKX_WS_URL) as ws:
                await ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [{"channel": "tickers", "instId": inst} for inst in OKX_INST],
                }))
                logger.info("okx ws connected, subscribed to tickers")
                backoff = RECONNECT_BACKOFF_START

                keepalive = asyncio.create_task(_keepalive_loop(ws))
                try:
                    async for raw in ws:
                        await _handle_message(raw)
                finally:
                    keepalive.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — reconnect on any failure, never crash the app
            logger.warning("okx ws disconnected, retrying in %ss: %s", backoff, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)


async def _keepalive_loop(ws):
    while True:
        await asyncio.sleep(KEEPALIVE_SECONDS)
        await ws.send("ping")


async def _handle_message(raw: str):
    if raw in ("ping", "pong"):
        return
    try:
        msg = json.loads(raw)
    except ValueError:
        return
    if msg.get("event") == "error":
        logger.warning("okx ws error event: %s", msg)
        return

    for row in msg.get("data") or []:
        symbol = OKX_INST.get(row.get("instId"))
        if not symbol:
            continue
        try:
            last = float(row["last"])
            open24 = float(row["open24h"])
        except (KeyError, TypeError, ValueError):
            continue
        chg24 = (last / open24 - 1.0) * 100.0 if open24 else 0.0

        STATE.live_ticks[symbol] = {"usd": last, "chg24": chg24}
        await MANAGER.broadcast(json.dumps({"type": "tick", "symbol": symbol, "usd": last, "chg24": chg24}))
