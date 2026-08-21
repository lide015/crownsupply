"""分析迴圈：「OKX 篩選 → 抓 K 線 → 技術面訊號 → 融合 AI 新聞情緒」跑一輪，結果寫進
state.STATE。刻意**不是**背景排程——沒有 while True + sleep 的自動輪詢，只有 app.py 的
`POST /api/v1/analyze` 端點在使用者按下「立即分析」時才會呼叫 refresh_cycle() 一次。
這樣 OKX／AI API 的用量完全由使用者手動觸發次數決定，不會有背景空轉的隱藏消耗。

每一輪也會順便：
1. 回頭檢查之前產生、還沒結算的訊號後來是中停利還是停損（純看 OKX 歷史 K 線，零 AI 成本）。
2. 停損時用 outcome_tracker 的純規則判斷可能的失效原因（零 AI 成本）。
3. 累積夠多已驗證訊號後，勝率偏低就透過 strategy_tuner 自動調高篩選門檻（見該模組說明）。
"""
import logging
import time

import httpx

from . import brain, config, db, news_client, okx_client, outcome_tracker, strategy, strategy_tuner
from .state import STATE

logger = logging.getLogger("background")


async def _refresh_news(client: httpx.AsyncClient):
    """每次呼叫都是使用者主動按下按鈕的結果，所以每次都抓最新新聞、重新判斷情緒，
    不做時間快取節流（節流的意義在自動背景輪詢；手動觸發本身就是節流）。"""
    sentiment = await news_client.get_market_sentiment(client)
    STATE.market_sentiment = sentiment["sentiment"]
    STATE.news_headline = sentiment["headline"]
    STATE.news_reason = sentiment["reason"]


async def _resolve_open_signals(client: httpx.AsyncClient):
    """回頭檢查還沒結算的舊訊號：抓該商品訊號產生「之後」的已收盤 K 線，模擬先中停利
    還是停損。純規則判斷（outcome_tracker.simulate_resolution），不呼叫任何 AI，零額外
    token 成本——只多花幾次免費的 OKX K 線查詢。"""
    now_ms = int(time.time() * 1000)
    expire_ms = int(config.SIGNAL_EXPIRE_HOURS * 3600 * 1000)

    for row in db.get_open_signals():
        try:
            candles = await okx_client.fetch_confirmed_candles(
                client, row["inst_id"], bar=config.CANDLE_BAR, limit=config.RESOLUTION_LOOKBACK_CANDLES
            )
        except Exception as exc:  # noqa: BLE001 — 單一商品查不到不能拖垮整輪追蹤
            logger.warning("resolution candle fetch failed for %s: %s", row["inst_id"], exc)
            continue

        after = [c for c in candles if c["ts"] > row["created_at"]]
        resolution, price, resolved_at, bars = outcome_tracker.simulate_resolution(
            row["signal_type"], row["entry_price"], row["stop_loss"],
            row["take_profit_1"], row["take_profit_2"], after,
        )

        if resolution is None:
            if now_ms - row["created_at"] > expire_ms:
                last_price = candles[-1]["c"] if candles else row["entry_price"]
                db.resolve_signal(row["id"], "expired", now_ms, last_price, None)
            continue

        failure_reason = outcome_tracker.classify_failure_reason(row, bars) if resolution == "hit_sl" else None
        db.resolve_signal(row["id"], resolution, resolved_at, price, failure_reason)


def _maybe_record_new_signal(item: dict, tech: dict, candles: list, fused: dict, sentiment: dict, now_ms: int):
    """tech 有實際多空方向時才記錄；同一商品同方向已經有未結算的紀錄就不要重複插入
    （使用者連續點「立即分析」時，同一個突破不該每次都被算成一筆新紀錄）。"""
    signal_type = tech["signal"]
    if signal_type is None:
        return
    if db.get_open_signal_for(item["instId"], signal_type):
        return
    db.insert_signal({
        "inst_id": item["instId"],
        "name": item["name"],
        "asset_class": item["asset_class"],
        "signal_type": signal_type,
        "created_at": candles[-1]["ts"] if candles else now_ms,
        "entry_price": tech["price"],
        "stop_loss": tech["stop_loss"],
        "take_profit_1": tech["take_profit_1"],
        "take_profit_2": tech["take_profit_2"],
        "ema": tech["ema"],
        "box_high": tech["box_high"],
        "box_low": tech["box_low"],
        "ai_sentiment": sentiment["sentiment"],
        "action_label": fused["action"],
        "color": fused["color"],
    })


async def _refresh_signals(client: httpx.AsyncClient):
    now_ms = int(time.time() * 1000)

    # 自動優化過的門檻（如果有）存在 SQLite 裡，跨重啟持續生效；沒調整過就用 config.py 預設值。
    effective_min_amplitude = db.get_param("MIN_AMPLITUDE_PCT", config.MIN_AMPLITUDE_PCT)
    # 記錄「上次調整當下累積了幾筆已驗證訊號」，避免使用者連續點兩次「立即分析」、
    # 中間完全沒有新訊號結算，卻被同一批舊資料重複觸發調整（見 strategy_tuner 說明）。
    last_tune_sample_count = db.get_param("MIN_AMPLITUDE_PCT__sample_count", 0)

    win_rate_stats = outcome_tracker.compute_win_rate(db.get_all_resolved_for_stats())
    tuning = strategy_tuner.maybe_auto_tune(win_rate_stats, effective_min_amplitude, int(last_tune_sample_count))
    if tuning:
        db.set_param(tuning["param"], tuning["new_value"], now_ms, tuning["reason"])
        db.set_param("MIN_AMPLITUDE_PCT__sample_count", win_rate_stats["total"], now_ms, None)
        effective_min_amplitude = tuning["new_value"]
        logger.info("auto-tuned %s: %s -> %s", tuning["param"], tuning["old_value"], tuning["new_value"])
    STATE.tuning_note = tuning["reason"] if tuning else None
    STATE.win_rate_stats = win_rate_stats
    STATE.effective_min_amplitude_pct = effective_min_amplitude
    # 訊號歷史純讀 DB、跟 OKX 網路呼叫無關，先設好——就算接下來的 OKX 篩選失敗，
    # 使用者還是看得到歷史成效，不會因為這次分析失敗就連歷史紀錄都不見了。
    STATE.recent_resolved = db.get_recent_resolved(20)

    tickers = await okx_client.fetch_swap_tickers(client)
    monitored = okx_client.screen_active_instruments(
        tickers,
        min_vol_usdt=config.MIN_VOL_USDT,
        min_amplitude_pct=effective_min_amplitude,
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
            "asset_class": item["asset_class"],
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

        if tech is not None:
            try:
                _maybe_record_new_signal(item, tech, candles, fused, sentiment, now_ms)
            except Exception as exc:  # noqa: BLE001 — 記錄歷史失敗不該讓這輪分析整個掛掉
                logger.warning("recording signal history failed for %s: %s", inst_id, exc)

    STATE.signals = signals
    STATE.last_update = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE.has_run = True


async def refresh_cycle(client: httpx.AsyncClient):
    """完整跑一輪分析：新聞情緒 → 回頭結算舊訊號 → 商品篩選（可能已被自動優化調整）→
    每檔的技術訊號 → 多空共振 → 記錄新訊號。由 app.py 在收到 POST /api/v1/analyze 時
    呼叫，一次請求對應一輪，不重複、不背景自動跑。"""
    try:
        await _refresh_news(client)
    except Exception as exc:  # noqa: BLE001 — 新聞失敗不影響技術面訊號照常更新
        logger.warning("news refresh failed, keeping previous sentiment: %s", exc)

    try:
        await _resolve_open_signals(client)
    except Exception as exc:  # noqa: BLE001 — 舊訊號結算失敗不該擋住本輪新訊號的產生
        logger.warning("resolving open signals failed: %s", exc)

    try:
        await _refresh_signals(client)
        STATE.last_error = None
    except Exception as exc:  # noqa: BLE001 — 失敗要讓使用者在儀表板上看到原因，不能悶掉
        logger.warning("signal refresh cycle failed: %s", exc)
        STATE.last_error = str(exc)
