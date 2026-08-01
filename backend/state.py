"""In-process memory cache (latest snapshot / fng / indicators) + WebSocket connection manager."""
import asyncio
import logging

logger = logging.getLogger("state")


class AppState:
    def __init__(self):
        self.latest_snapshot: dict | None = None
        self.fng_cache: dict | None = None
        self.indicators_cache: dict | None = None
        self.quote_source: str = "coingecko"
        self.consecutive_failures: int = 0
        self.last_fetch_ts: int | None = None


class ConnectionManager:
    def __init__(self):
        self._connections: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket):
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: str):
        async with self._lock:
            targets = list(self._connections)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception as exc:  # noqa: BLE001 — drop dead connections quietly
                logger.info("dropping websocket connection: %s", exc)
                await self.disconnect(ws)


STATE = AppState()
MANAGER = ConnectionManager()
