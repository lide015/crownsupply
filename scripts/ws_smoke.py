"""Companion to smoke.ps1 — connects to /ws and waits up to 90s for a real snapshot message.
Uses `websockets`, which ships as a dependency of uvicorn[standard] (no extra install needed).
"""
import asyncio
import json
import sys

import websockets

WS_URL = "ws://127.0.0.1:8788/ws"
TIMEOUT_SECONDS = 90


async def main() -> int:
    async with websockets.connect(WS_URL) as ws:
        deadline = asyncio.get_event_loop().time() + TIMEOUT_SECONDS
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                print("timed out waiting for a snapshot message")
                return 1
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            data = json.loads(msg)
            if "quotes" in data:
                print("received snapshot:", list(data.keys()))
                return 0
            # heartbeat or other control message — keep waiting for a real snapshot
            print("skipping non-snapshot message:", data.get("type", data))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
