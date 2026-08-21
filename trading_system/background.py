"""分析迴圈：「OKX 篩選 → 抓 K 線 → 技術面訊號 → 融合 AI 新聞情緒」跑一輪，結果寫進
state.STATE。刻意**不是**背景排程——沒有 while True + sleep 的自動輪詢，只有 app.py 的
`POST /api/v1/analyze` 端點在使用者按下「立即分析」時才會呼叫 refresh_cycle() 一次。
這樣 OKX／AI API 的用量完全由使用者手動觸發次數決定，不會有背景空轉的隱藏消耗。
"""
import logging
import time

import httpx

from . import brain, config, news_client, okx_client, strategy
from .state import STATE

logger = logging.getLogger("background")


async def _refresh_news(client: httpx.AsyncClient):
    """每次呼叫都是使用者主動按下按鈕的結果，所以每次都抓最新新聞、重新判斷情緒，
    不做時間快取節流（節流的意義在自動背景輪詢；手動觸發本身就是節流）。"""
    sentiment = await news_client.get_market_sentiment(client)
    STATE.market_sentiment = sentiment["sentiment"]
    STATE.news_headline = sentiment["headline"]
    STATE.news_reason = sentiment["reason"]


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
            tech = strategy.compute_signal(
                candles,
                ema_period=config.EMA_PERIOD,
                box_lookback=config.BOX_LOOKBACK,
                tp1_rr=config.TP1_RR,
                tp2_rr=config.TP2_RR,
            )
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
            "take_profit_1": tech["take_profit_1"] if tech else None,
            "take_profit_2": tech["take_profit_2"] if tech else None,
            "vol_usdt": item["vol_usdt"],
            "amplitude_pct": item["amplitude_pct"],
            **fused,
        })

    STATE.signals = signals
    STATE.last_update = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE.has_run = True


async def refresh_cycle(client: httpx.AsyncClient):
    """完整跑一輪分析：新聞情緒 → 商品篩選 → 每檔的技術訊號 → 多空共振。
    由 app.py 在收到 POST /api/v1/analyze 時呼叫，一次請求對應一輪，不重複、不背景自動跑。"""
    try:
        await _refresh_news(client)
    except Exception as exc:  # noqa: BLE001 — 新聞失敗不影響技術面訊號照常更新
        logger.warning("news refresh failed, keeping previous sentiment: %s", exc)

    try:
        await _refresh_signals(client)
        STATE.last_error = None
    except Exception as exc:  # noqa: BLE001 — 失敗要讓使用者在儀表板上看到原因，不能悶掉
        logger.warning("signal refresh cycle failed: %s", exc)
        STATE.last_error = str(exc)
