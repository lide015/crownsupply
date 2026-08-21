"""背景重新整理迴圈：定期重跑「OKX 篩選 → 抓 K 線 → 技術面訊號 → 融合 AI 新聞情緒」，
結果寫進 state.STATE。前端 /api/v1/dashboard 只讀快取，不會每次請求都重打 OKX/AI API。

新聞情緒呼叫頻率由 config.NEWS_REFRESH_SECONDS 獨立控制（預設 10 分鐘），跟商品/K線的
config.REFRESH_SECONDS（預設 30 秒）分開，避免每 30 秒燒一次 AI token。
"""
import asyncio
import logging
import time

import httpx

from . import brain, config, news_client, okx_client, strategy
from .state import STATE

logger = logging.getLogger("background")


async def _refresh_news(client: httpx.AsyncClient):
    now = time.time()
    if now - STATE.last_news_refresh_ts < config.NEWS_REFRESH_SECONDS and STATE.last_news_refresh_ts > 0:
        return  # 還沒到重新整理的時間，沿用快取，不重打 AI API
    sentiment = await news_client.get_market_sentiment(client)
    STATE.market_sentiment = sentiment["sentiment"]
    STATE.news_headline = sentiment["headline"]
    STATE.news_reason = sentiment["reason"]
    STATE.last_news_refresh_ts = now


async def _refresh_signals(client: httpx.AsyncClient):
    tickers = await okx_client.fetch_swap_tickers(client)
    monitored = okx_client.screen_active_instruments(
        tickers,
        min_vol_usdt=config.MIN_VOL_USDT,
        min_amplitude_pct=config.MIN_AMPLITUDE_PCT,
        top_n=config.TOP_N,
        extra_keywords=config.EXTRA_INSTRUMENT_KEYWORDS,
    )
    STATE.monitored = monitored

    sentiment = {
        "sentiment": STATE.market_sentiment,
        "headline": STATE.news_headline,
        "reason": STATE.news_reason,
    }

    signals = []
    for item in monitored:
        inst_id = item["instId"]
        try:
            candles = await okx_client.fetch_confirmed_candles(
                client, inst_id, bar=config.CANDLE_BAR, limit=config.CANDLE_LIMIT
            )
            tech = strategy.compute_signal(candles, ema_period=config.EMA_PERIOD, box_lookback=config.BOX_LOOKBACK)
        except Exception as exc:  # noqa: BLE001 — 單一商品失敗不能拖垮整輪更新
            logger.warning("signal calc failed for %s: %s", inst_id, exc)
            continue

        fused = brain.fuse(tech, sentiment)
        signals.append({
            "name": item["name"],
            "instId": inst_id,
            "price": tech["price"] if tech else item["price"],
            "ema": tech["ema"] if tech else None,
            "box_high": tech["box_high"] if tech else None,
            "box_low": tech["box_low"] if tech else None,
            "stop_loss": tech["stop_loss"] if tech else None,
            "vol_usdt": item["vol_usdt"],
            "amplitude_pct": item["amplitude_pct"],
            **fused,
        })

    STATE.signals = signals
    STATE.last_update = time.strftime("%Y-%m-%d %H:%M:%S")


async def refresh_cycle(client: httpx.AsyncClient):
    try:
        await _refresh_news(client)
    except Exception as exc:  # noqa: BLE001 — 新聞失敗不影響技術面訊號照常更新
        logger.warning("news refresh failed, keeping previous sentiment: %s", exc)

    try:
        await _refresh_signals(client)
        STATE.last_error = None
    except Exception as exc:  # noqa: BLE001 — 整輪失敗也不能讓背景任務死掉，下一輪重試
        logger.warning("signal refresh cycle failed: %s", exc)
        STATE.last_error = str(exc)


async def run_forever():
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        while True:
            await refresh_cycle(client)
            await asyncio.sleep(config.REFRESH_SECONDS)
