"""分析迴圈：「OKX 篩選 → 抓 K 線 → 技術面訊號 → 融合 AI 新聞情緒」跑一輪，結果寫進
state.STATE。核心邏輯不假設任何觸發方式——app.py 的 `POST /api/v1/analyze` 端點在
使用者按下「立即分析」時呼叫 refresh_cycle() 一次（不帶 skip_ai_reason，行為跟這個
系統原本的設計完全一樣：每次點擊對應一輪完整的 OKX＋AI 呼叫，用量由點擊次數決定）；
`scheduler.py` 的選用背景排程（預設關閉，見該模組說明）也呼叫同一個函式，但規則大腦
（技術面）每輪都跑、AI 新聞情緒則由 `ai_governor.py` 決定要不要問（傳入 skip_ai_reason），
避免自動化等於無上限燒 AI token。

每一輪也會順便：
1. 回頭檢查之前產生、還沒結算的訊號後來是中停利還是停損（純看 OKX 歷史 K 線，零 AI 成本）。
2. 停損時用 outcome_tracker 的純規則判斷可能的失效原因（零 AI 成本）。
3. 累積夠多已驗證訊號後，勝率偏低就透過 strategy_tuner 自動調高篩選門檻（見該模組說明）。
4. 重複利用已經抓好的 K 線算市場平均 RSI、山寨季代理指標（見 market_pulse.py），額外
   打一次免費公開的恐懼貪婪指數 API——零 AI 成本。
5. 抓每檔商品的合約未平倉量（OI），跟上次分析週期比較出變化幅度（見 oi_tracker.py），
   當「推薦強度榜」籌碼面維度的資料來源（見 ranking.py）。
6. 技術面真的有突破方向時，把停利1的目標獲利換算成扣掉當沖來回手續費之後的「淨盈虧比」
   （見 fee_calc.py）——太薄甚至倒虧就算技術面/新聞面完美共振，brain.fuse() 一樣會攔截
   成警告，不讓使用者衝進一筆「看對方向也賺不到錢」的交易。
7. 技術面突破時，順便檢查突破那根K線的成交量有沒有明顯放大（見 strategy.py 的
   volume_confirm_multiple）——量能不足的突破容易是雜訊假突破，不觸發訊號。
8. 技術面真的有突破方向時，多抓一次更高週期（預設1小時）K線確認大方向沒有明顯反向
   （見 strategy.compute_trend_bias）——逆著大趨勢做的短線突破特別容易被雜訊洗出場。
9. 每一輪先檢查「今天」已結算訊號有沒有觸及虧損上限（見
   outcome_tracker.compute_daily_circuit_breaker），觸及的話這一輪所有新訊號都會被
   brain.fuse() 攔截成「今日已達虧損上限」，不管技術面/新聞面/淨盈虧比再好看都一樣。
10. 真正「新產生」的強烈多空共振訊號（STRONG LONG/SHORT），如果有設定 Telegram
    Bot（見 telegram_notify.py）或 SMTP（見 email_notify.py），會各自主動推播一則
    通知——兩個管道互相獨立，沒設定就優雅跳過，不影響另一個。
11. 每一輪也順便算「持倉組合風險總覽」（見 outcome_tracker.compute_portfolio_exposure）：
    現在同時開著幾筆未結算訊號、有沒有同方向集中度警訊。
12. 抓每檔商品目前的資金費率（見 funding_rate.py）——加密貨幣永續合約特有的市場情緒
    指標（股票沒有），純資訊揭露，不參與 brain.fuse() 的訊號融合。
13. 使用者自訂警報（見 alerts.py）：價格漲破/跌破對每輪重抓的全部商品清單評估，訊號
    警報依附在這裡的技術分析流程上，條件成立就透過 Telegram／Email 通知。

新聞情緒判讀刻意放在「OKX 篩選出這輪實際監控哪些商品」**之後**才做（不是開頭第一步）：
要先知道這輪到底在看哪幾檔商品，才能各自搜尋「這檔」的專屬新聞，而不是每一檔訊號都套用
同一份籠統的整體市場情緒（見 news_client.py 的說明）。逐檔判讀跟整體市場判讀塞在同一次
AI 呼叫裡問完，不會因為監控檔數變多就跟著燒更多 AI token。
"""
import logging
import time

import httpx

from . import alerts, brain, config, db, email_notify, fee_calc, funding_rate, market_pulse, news_client, oi_tracker, okx_client, outcome_tracker, position_sizing, ranking, strategy, strategy_tuner, telegram_notify
from .state import STATE

BTC_INST_ID = "BTC-USDT-SWAP"  # 山寨季代理指標的比較基準（見 market_pulse.py 說明）

logger = logging.getLogger("background")


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


def _maybe_record_new_signal(item: dict, tech: dict, candles: list, fused: dict, sentiment: dict, now_ms: int) -> bool:
    """tech 有實際多空方向時才記錄；同一商品同方向已經有未結算的紀錄就不要重複插入
    （使用者連續點「立即分析」時，同一個突破不該每次都被算成一筆新紀錄）。

    回傳是否真的插入了一筆新紀錄——給呼叫端判斷要不要觸發 Telegram 通知（見
    telegram_notify.py）：只有「真正新產生」的訊號才通知，不會因為同一筆訊號還沒結算、
    使用者又分析到同一檔就重複通知。"""
    signal_type = tech["signal"]
    if signal_type is None:
        return False
    if db.get_open_signal_for(item["instId"], signal_type):
        return False
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
    return True


async def _fetch_htf_trend(client: httpx.AsyncClient, inst_id: str) -> str | None:
    """多時間週期共振用：抓更高週期（config.HTF_BAR，預設1小時）K線，判斷大方向是不是
    跟5分鐘線同向（見 strategy.compute_trend_bias）。任何失敗都優雅回傳 None（呼叫端
    視為「無法判斷」，不會擋掉本來的訊號），不讓這個附加把關拖垮主要的訊號分析。"""
    try:
        htf_candles = await okx_client.fetch_confirmed_candles(
            client, inst_id, bar=config.HTF_BAR, limit=config.HTF_CANDLE_LIMIT
        )
    except Exception as exc:  # noqa: BLE001 — 高週期趨勢只是附加把關，抓不到不影響主要訊號
        logger.warning("HTF trend candle fetch failed for %s: %s", inst_id, exc)
        return None
    return strategy.compute_trend_bias(htf_candles, config.HTF_EMA_PERIOD)


async def _fetch_oi_delta(client: httpx.AsyncClient, inst_id: str, now_ms: int) -> dict:
    """抓這檔商品目前的未平倉量，跟上次分析週期比較出變化幅度，並把這次的值存回去當
    下次的基準（見 oi_tracker.py / db.py 的 oi_snapshot 表）。任何一步失敗都回傳中性
    結果，不讓這個附加指標拖垮整輪訊號分析。"""
    try:
        current = await oi_tracker.fetch_open_interest(client, inst_id)
    except Exception as exc:  # noqa: BLE001 — OI 只是附加指標，失敗不影響主要訊號
        logger.warning("OI fetch failed for %s: %s", inst_id, exc)
        return {"oi_change_pct": None, "label": "資料不足", "is_surge": False}
    if current is None:
        return {"oi_change_pct": None, "label": "資料不足", "is_surge": False}

    delta = oi_tracker.compute_oi_delta(current["oi_ccy"], db.get_previous_oi(inst_id))
    db.set_oi_snapshot(inst_id, current["oi"], current["oi_ccy"], now_ms)
    return delta


async def _fetch_funding_rate(client: httpx.AsyncClient, inst_id: str) -> dict:
    """抓這檔商品目前的資金費率（只有永續合約有這個概念，見 funding_rate.py 說明）——
    加密貨幣永續合約特有的市場情緒指標，股票沒有。任何失敗都回傳中性結果，不讓這個
    附加指標拖垮整輪訊號分析，跟 _fetch_oi_delta 同樣的容錯模式。不影響 brain.fuse()
    的訊號融合，純資訊揭露。"""
    try:
        current = await funding_rate.fetch_funding_rate(client, inst_id)
    except Exception as exc:  # noqa: BLE001 — 資金費率只是附加指標，失敗不影響主要訊號
        logger.warning("funding rate fetch failed for %s: %s", inst_id, exc)
        return {"funding_rate_pct": None, "label": "無資料"}
    if current is None:
        return {"funding_rate_pct": None, "label": "無資料"}
    classified = funding_rate.classify_funding_rate(current["funding_rate_pct"])
    return {"funding_rate_pct": current["funding_rate_pct"], "label": classified["label"]}


def _pct_change(candles: list[dict]) -> float | None:
    if len(candles) < 2 or candles[0]["c"] <= 0:
        return None
    return (candles[-1]["c"] - candles[0]["c"]) / candles[0]["c"] * 100.0


async def _fetch_btc_pct_change(client: httpx.AsyncClient, already_fetched: dict) -> float | None:
    """山寨季代理指標的 BTC 基準報酬率（見 market_pulse.py 說明）。監控清單裡剛好有 BTC
    就直接重複利用那份資料，沒有才額外打一次免費公開的 K 線 API。"""
    if BTC_INST_ID in already_fetched:
        return already_fetched[BTC_INST_ID]
    try:
        candles = await okx_client.fetch_confirmed_candles(
            client, BTC_INST_ID, bar=config.CANDLE_BAR, limit=config.CANDLE_LIMIT
        )
    except Exception as exc:  # noqa: BLE001 — 山寨季只是附加指標，抓不到就老實回報「資料不足」
        logger.warning("BTC baseline candle fetch failed: %s", exc)
        return None
    return _pct_change(candles)


async def analyze_one_instrument(
    client: httpx.AsyncClient, item: dict, sentiment: dict, now_ms: int, circuit_breaker: dict | None = None
) -> tuple[dict | None, list, bool]:
    """對單一商品跑完整的「K線→技術訊號→OI→多空共振」流程，回傳
    (訊號 dict 或 None, candles, is_new_signal)。第三個值供呼叫端（見 _refresh_signals）
    判斷這一輪有沒有真正新產生的技術訊號，給背景排程模式的 AI 節流節奏參考（見
    ai_governor.py：新訊號應該優先問 AI，不該被固定週期卡住）——K線抓取失敗時第三個值
    固定回傳 False。

    item 需含 instId/name/asset_class/price/vol_usdt/amplitude_pct（parse_instruments() 的格式）；
    sentiment 是這檔的新聞情緒（{"sentiment","headline","reason"}）。
    circuit_breaker：outcome_tracker.compute_daily_circuit_breaker() 的回傳值（可能是
    None，代表呼叫端選擇不檢查這個機制）——見 brain.fuse() 說明，優先於所有其他判斷。

    這是 `_refresh_signals` 自動篩選迴圈、跟 `app.py` 的 `POST /api/v1/analyze-instrument`
    （使用者在「全部商品總覽」點按需求分析）**共用的同一份邏輯**——不管是系統自動選中的，
    還是使用者自己點的，都走一模一樣的計算方式跟訊號歷史記錄規則，結果不會兩套標準。
    K線抓取失敗時回傳 (None, [])，呼叫端自行決定要不要略過。"""
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
            volume_confirm_multiple=config.VOLUME_CONFIRM_MULTIPLE,
        )
    except Exception as exc:  # noqa: BLE001 — 單一商品失敗不能拖垮整輪更新
        logger.warning("signal calc failed for %s: %s", inst_id, exc)
        return None, [], False

    rsi = market_pulse.compute_rsi([c["c"] for c in candles])
    oi_delta = await _fetch_oi_delta(client, inst_id, now_ms)
    funding = await _fetch_funding_rate(client, inst_id)

    # 🧭 多時間週期共振：技術面真的有突破方向時，才需要多抓一次更高週期K線確認大方向
    # （見 strategy.compute_trend_bias 說明）——沒有突破方向就沒有「順不順勢」的問題。
    htf_trend = None
    if tech is not None and tech.get("signal") is not None:
        htf_trend = await _fetch_htf_trend(client, inst_id)

    # 💸 當沖手續費把關：技術面真的有突破方向時，才需要算「扣掉來回手續費之後」的淨盈虧比
    # （見 fee_calc.py 說明）——沒有訊號方向就沒有進場價/停利價，算了也沒有意義。
    fee_info = None
    if tech is not None and tech.get("signal") is not None and tech.get("take_profit_1") is not None:
        fee_info = fee_calc.compute_fee_adjusted_rr(
            tech["price"], tech["stop_loss"], tech["take_profit_1"], config.TAKER_FEE_PCT
        )

    fused = brain.fuse(tech, sentiment, fee_info, config.MIN_NET_RR, htf_trend, circuit_breaker)
    signal = {
        "name": item["name"],
        "instId": inst_id,
        "asset_class": item["asset_class"],
        "product_type": item.get("product_type", "swap"),
        "price": tech["price"] if tech else item["price"],
        "ema": tech["ema"] if tech else None,
        "box_high": tech["box_high"] if tech else None,
        "box_low": tech["box_low"] if tech else None,
        "stop_loss": tech["stop_loss"] if tech else None,
        "take_profit_1": tech["take_profit_1"] if tech else None,
        "take_profit_2": tech["take_profit_2"] if tech else None,
        "vol_usdt": item["vol_usdt"],
        "amplitude_pct": item["amplitude_pct"],
        "change_pct": item.get("change_pct"),
        "signal_type": tech["signal"] if tech else None,
        "ai_sentiment": sentiment["sentiment"],
        "news_headline": sentiment.get("headline"),
        "news_reason": sentiment.get("reason"),
        "rsi": rsi,
        "oi_change_pct": oi_delta["oi_change_pct"],
        "oi_label": oi_delta["label"],
        "funding_rate_pct": funding["funding_rate_pct"],
        "funding_rate_label": funding["label"],
        "net_rr": fee_info["net_rr"] if fee_info else None,
        "round_trip_fee_pct": fee_info["round_trip_fee_pct"] if fee_info else None,
        "fee_eats_pct": fee_info["fee_eats_pct"] if fee_info else None,
        "htf_trend": htf_trend,
        **fused,
    }

    is_new_signal = False
    if tech is not None:
        try:
            is_new_signal = _maybe_record_new_signal(item, tech, candles, fused, sentiment, now_ms)
        except Exception as exc:  # noqa: BLE001 — 記錄歷史失敗不該讓分析整個掛掉
            logger.warning("recording signal history failed for %s: %s", inst_id, exc)

    # 📨 訊號觸發通知：只在「真正新產生」且是多空共振強烈訊號（STRONG LONG/SHORT，也就是
    # 沒有被手續費/高週期趨勢/每日斷路器攔截成警告）時才通知，避免雜訊/警告訊號也跳通知
    # 太擾人。Telegram／Email 各自獨立、都是選用管道，兩邊內部都已經吞掉所有失敗情況，
    # 這裡再包一層純粹是雙重保險；沒設定的管道 is_configured() 一律優雅回傳 False。
    if is_new_signal and fused.get("color") in (brain.COLOR_GREEN, brain.COLOR_RED):
        try:
            await telegram_notify.send_signal_notification(client, signal)
        except Exception as exc:  # noqa: BLE001 — 通知失敗不該讓分析流程掛掉
            logger.warning("telegram notification failed for %s: %s", inst_id, exc)
        try:
            await email_notify.send_signal_notification(signal)
        except Exception as exc:  # noqa: BLE001 — 通知失敗不該讓分析流程掛掉
            logger.warning("email notification failed for %s: %s", inst_id, exc)

    return signal, candles, is_new_signal


async def _fire_alert_if_due(client: httpx.AsyncClient, alert: dict, context: dict, now_ms: int):
    """評估單一警報這輪要不要觸發（見 alerts.py 的說明：純函式判斷條件+觸發規則），
    真的要觸發就透過警報自己勾選的管道發送，最後一律記錄這次觸發嘗試（不管實際發送
    成功與否——避免管道故障時每輪都重試轟炸，跟既有訊號通知「失敗就算了，不重試」的
    慣例一致）。"""
    condition_met = alerts.evaluate_condition(alert, context)
    if not alerts.should_fire(alert, condition_met, now_ms, config.ALERT_MIN_RETRIGGER_SECONDS):
        return

    message = alerts.build_alert_message(alert, context)
    channels = alert.get("channels") or []
    if "telegram" in channels:
        try:
            await telegram_notify.send_text(client, message)
        except Exception as exc:  # noqa: BLE001 — 警報通知失敗不能拖垮整輪分析
            logger.warning("alert telegram send failed for alert %s: %s", alert["id"], exc)
    if "email" in channels:
        try:
            subject = f"[Gold Trader LITE] 警報觸發：{alert.get('name') or alert.get('inst_id', '')}"
            await email_notify.send_text(subject, message)
        except Exception as exc:  # noqa: BLE001 — 警報通知失敗不能拖垮整輪分析
            logger.warning("alert email send failed for alert %s: %s", alert["id"], exc)

    db.record_alert_trigger(alert["id"], now_ms, auto_disable=alert.get("repeat_mode") == "once")


async def _evaluate_price_alerts(client: httpx.AsyncClient, alerts_by_inst: dict, all_instruments: list, now_ms: int):
    """價格警報（price_above/price_below）對「全部商品總覽」這份清單評估——這份清單每輪
    都會重新抓（見 _refresh_signals 前半段），涵蓋 OKX 全部合約，不限於自動篩選出的監控
    清單，價格警報可以設在任何商品上，不用等它被自動選中才有機會評估。零額外 API 成本，
    純比較這輪已經抓好的價格。"""
    price_by_inst = {item["instId"]: item.get("price") for item in all_instruments}
    for inst_id, inst_alerts in alerts_by_inst.items():
        current_price = price_by_inst.get(inst_id)
        for alert in inst_alerts:
            if alert["alert_type"] not in ("price_above", "price_below"):
                continue
            await _fire_alert_if_due(client, alert, {"current_price": current_price}, now_ms)


async def _refresh_signals(client: httpx.AsyncClient, skip_ai_reason: str | None = None):
    """skip_ai_reason：非 None 時這一輪完全不呼叫 AI 新聞情緒，沿用上一輪的市場情緒
    （見 ai_governor.py／scheduler.py 說明）。手動「立即分析」（app.py 的
    POST /api/v1/analyze）呼叫時這個參數維持預設 None，行為跟原本完全一樣——這個節流
    只在背景排程模式下才會被傳入非 None 的值。"""
    now_ms = int(time.time() * 1000)

    # 🔔 使用者自訂警報（見 alerts.py）：只讀一次啟用中的警報、依 inst_id 分組，供下面
    # 價格警報（全部商品清單評估）跟訊號警報（監控清單逐檔評估）共用，避免每個商品各自
    # 查一次資料庫。
    alerts_by_inst: dict[str, list] = {}
    for alert in db.get_enabled_alerts():
        alerts_by_inst.setdefault(alert["inst_id"], []).append(alert)

    # 自動優化過的門檻（如果有）存在 SQLite 裡，跨重啟持續生效；沒調整過就用 config.py 預設值。
    effective_min_amplitude = db.get_param("MIN_AMPLITUDE_PCT", config.MIN_AMPLITUDE_PCT)
    # 記錄「上次調整當下累積了幾筆已驗證訊號」，避免使用者連續點兩次「立即分析」、
    # 中間完全沒有新訊號結算，卻被同一批舊資料重複觸發調整（見 strategy_tuner 說明）。
    last_tune_sample_count = db.get_param("MIN_AMPLITUDE_PCT__sample_count", 0)

    win_rate_stats = outcome_tracker.compute_win_rate(db.get_all_resolved_for_stats())
    tuning = strategy_tuner.maybe_auto_tune(
        win_rate_stats, effective_min_amplitude, int(last_tune_sample_count),
        floor_amplitude_pct=config.MIN_AMPLITUDE_PCT,
    )
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
    recent_resolved = db.get_recent_resolved(20)
    # 📚 每一筆停損訊號附上失效原因反推出的分類代碼，讓前端可以推薦對應的知識宇宙卡片
    # （見 outcome_tracker.categorize_failure_reason 說明）——純從已經存好的 failure_reason
    # 文字推導，不需要額外的資料庫欄位或 AI 呼叫。
    for row in recent_resolved:
        row["failure_categories"] = outcome_tracker.categorize_failure_reason(row.get("failure_reason"))
    STATE.recent_resolved = recent_resolved

    # 🛑 每日虧損斷路器：今天已結算的訊號有沒有觸及虧損上限（見
    # outcome_tracker.compute_daily_circuit_breaker 說明）。純讀 DB + 純函式計算，
    # 這一輪算出來的結果會傳給下面每一檔商品的 brain.fuse()，全部套用同一個「今天」狀態。
    circuit_breaker = outcome_tracker.compute_daily_circuit_breaker(
        db.get_resolved_today(now_ms), config.MAX_DAILY_LOSS_COUNT, config.MAX_DAILY_LOSS_R
    )
    STATE.circuit_breaker = circuit_breaker

    # 📦 持倉組合風險總覽：現在同時開著幾筆未結算訊號（見
    # outcome_tracker.compute_portfolio_exposure 說明）——每日斷路器看的是「今天已發生」，
    # 這個看的是「現在正在承受」，純讀 DB + 純函式計算，零額外成本。
    STATE.portfolio_exposure = outcome_tracker.compute_portfolio_exposure(db.get_open_signals())

    # 🧮 倉位計算機的凱利公式建議：用「本系統自己歷史上真的中停利/停損過幾次」算出來的
    # 勝率＋平均獲利倍數，不是憑空給一個數字。零額外 AI/API 成本，純讀 DB + 純函式計算。
    avg_win_r = outcome_tracker.compute_average_win_r_multiple(db.get_resolved_trades_for_kelly())
    STATE.kelly_suggestion = (
        position_sizing.calc_kelly_suggestion(win_rate_stats["win_rate_pct"], avg_win_r, win_rate_stats["total"])
        if avg_win_r is not None and win_rate_stats["win_rate_pct"] is not None
        else None
    )

    tickers = await okx_client.fetch_swap_tickers(client)
    # OKX 上「全部」永續合約的基本報價（不套門檻、不截斷）——零額外 API 成本，這份資料本來
    # 就在這一次 tickers 回應裡，只是之前直接丟掉了。給前端「全部商品總覽」瀏覽/篩選/搜尋用。
    all_instruments = okx_client.parse_instruments(tickers, config.EXTRA_INSTRUMENT_KEYWORDS, product_type="swap")

    # 現貨（SPOT）另外抓一次——多一次免費公開 API 呼叫，只用來充實「全部商品總覽」的瀏覽
    # 清單，**不會**自動進入篩選/深度分析池（自動分析只吃永續合約，見 fetch_spot_tickers
    # 說明）；抓不到就靜靜跳過，不影響其他任何功能。
    try:
        spot_tickers = await okx_client.fetch_spot_tickers(client)
        all_instruments += okx_client.parse_instruments(spot_tickers, product_type="spot")
    except Exception as exc:  # noqa: BLE001 — 現貨清單只是附加瀏覽功能，失敗不影響主要分析
        logger.warning("spot ticker fetch failed: %s", exc)

    # 📌 全市場未平倉量（OI）——只有合約（SWAP）才有這個概念，現貨沒有。給熱力圖「持倉」
    # 模式跟「全部商品總覽」用，OKX 公開端點一次拿全部（不用逐檔查），零 AI 成本。
    # 先把「上一輪」的快照讀出來存好（previous_oi_map），再抓這一輪的最新值——下面才不會
    # 因為監控清單那幾檔稍後各自又跑一次 _fetch_oi_delta（寫入新快照）而污染了這裡要用的
    # 「上一輪基準值」。實際把這一輪的值寫回資料庫，要等到這個函式最後面才做。
    previous_oi_map = db.get_all_previous_oi()
    oi_rows: list[dict] = []
    try:
        oi_rows = await oi_tracker.fetch_all_open_interest(client, "SWAP")
        oi_by_inst = {
            row["inst_id"]: oi_tracker.compute_oi_delta(row["oi_ccy"], previous_oi_map.get(row["inst_id"]))
            for row in oi_rows
        }
        oi_ccy_by_inst = {row["inst_id"]: row["oi_ccy"] for row in oi_rows}
        for item in all_instruments:
            if item["product_type"] != "swap":
                continue
            delta = oi_by_inst.get(item["instId"])
            if delta is None:
                continue
            item["oi_ccy"] = oi_ccy_by_inst[item["instId"]]
            item["oi_change_pct"] = delta["oi_change_pct"]
    except Exception as exc:  # noqa: BLE001 — 全市場 OI 是附加資料，抓不到不該擋住報價/訊號主線
        logger.warning("bulk OI fetch failed: %s", exc)

    STATE.all_instruments = all_instruments
    if alerts_by_inst:
        await _evaluate_price_alerts(client, alerts_by_inst, all_instruments, now_ms)

    monitored = okx_client.screen_active_instruments(
        tickers,
        min_vol_usdt=config.MIN_VOL_USDT,
        min_amplitude_pct=effective_min_amplitude,
        top_n=config.TOP_N,
        extra_keywords=config.EXTRA_INSTRUMENT_KEYWORDS,
    )
    STATE.monitored = monitored

    # --- 新聞情緒：現在知道這輪實際監控哪些商品了，逐檔查專屬新聞 + 整體市場，
    # 塞進同一次 AI 呼叫問完（見 news_client.py 說明，不會因為監控檔數變多而多燒 AI token）。
    news_targets = [
        {"instId": item["instId"], "query": item["instId"].split("-")[0], "label": item["name"]}
        for item in monitored
    ]
    if skip_ai_reason:
        # 🧠 背景排程模式：這一輪省 token，不呼叫 AI，規則大腦（技術面）照常運作、沿用上一輪
        # 的市場情緒（見 ai_governor.should_skip_ai_this_cycle 說明）。不算「失敗」，
        # 不會累計進 AI 連續失敗斷路器。
        stale = {"sentiment": STATE.market_sentiment, "headline": STATE.news_headline, "reason": STATE.news_reason}
        news = {"market": stale, "by_instrument": {t["instId"]: stale for t in news_targets}, "status": "skipped"}
        STATE.ai_skip_reason = skip_ai_reason
        STATE.last_ai_call_attempted = False
        STATE.last_ai_call_failed = False
    else:
        STATE.ai_skip_reason = None
        STATE.last_ai_call_attempted = True
        try:
            news = await news_client.get_market_and_instrument_sentiment(client, news_targets)
            STATE.last_ai_call_failed = news.get("status") == "error"
        except Exception as exc:  # noqa: BLE001 — 新聞失敗不影響技術面訊號照常更新，維持上一輪的情緒
            logger.warning("news refresh failed, keeping previous sentiment: %s", exc)
            stale = {"sentiment": STATE.market_sentiment, "headline": STATE.news_headline, "reason": STATE.news_reason}
            news = {"market": stale, "by_instrument": {t["instId"]: stale for t in news_targets}, "status": "error"}
            STATE.last_ai_call_failed = True
    STATE.market_sentiment = news["market"]["sentiment"]
    STATE.news_headline = news["market"]["headline"]
    STATE.news_reason = news["market"]["reason"]
    sentiment_by_inst = news["by_instrument"]

    signals = []
    rsi_values = []
    pct_changes_by_inst = {}
    any_new_signal = False
    for item in monitored:
        inst_id = item["instId"]
        sentiment = sentiment_by_inst.get(inst_id, news["market"])
        signal, candles, is_new_signal = await analyze_one_instrument(client, item, sentiment, now_ms, circuit_breaker)
        any_new_signal = any_new_signal or is_new_signal

        # 🔔 訊號警報：只對「這輪有跑過技術分析」的商品有效（監控清單自動選中的、或使用者
        # 手動分析過的），不是全市場即時監控——訊號警報依附在技術分析本身，沒被分析到的
        # 商品沒有 is_new_signal 這個判斷依據可用。這個限制在前端文案裡會明確說明。
        for alert in alerts_by_inst.get(inst_id, []):
            if alert["alert_type"] == "signal":
                await _fire_alert_if_due(client, alert, {"is_new_signal": is_new_signal}, now_ms)

        if signal is None:
            continue
        signals.append(signal)

        # 市場情緒儀表板用的附加資料：重複利用剛剛已經抓好的 K 線，不額外多打 API。
        if signal["rsi"] is not None:
            rsi_values.append(signal["rsi"])
        pct_changes_by_inst[inst_id] = _pct_change(candles)

    # 🧠 給下一輪背景排程的 AI 節流判斷用（見 ai_governor.py）：這一輪有沒有真正新產生的
    # 技術訊號。故意記在「這一輪」結束時給「下一輪」用，而不是同一輪內搶快問 AI——AI 新聞
    # 情緒判讀排在整體新聞抓取「之後」才逐檔跑（見本函式上半段的說明），此刻才知道這一輪
    # 誰是新訊號已經太晚，下一輪排程間隔通常只有幾十分鐘，一輪的延遲換取不用整檔重抓兩次
    # K線，划算。
    STATE.had_new_signal_last_cycle = any_new_signal

    STATE.signals = signals
    STATE.last_update = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE.last_update_ms = int(time.time() * 1000)
    STATE.has_run = True

    # --- 市場情緒儀表板：平均 RSI、山寨季代理指標、恐懼貪婪指數（見 market_pulse.py） ---
    rsi_stats = market_pulse.average_rsi(rsi_values)
    btc_pct_change = await _fetch_btc_pct_change(client, pct_changes_by_inst)
    alt_pct_changes = [v for k, v in pct_changes_by_inst.items() if k != BTC_INST_ID and v is not None]
    altseason = market_pulse.compute_altseason_proxy(alt_pct_changes, btc_pct_change)
    fear_greed = await market_pulse.fetch_fear_greed_index(client)
    STATE.market_pulse = {"rsi": rsi_stats, "altseason": altseason, "fear_greed": fear_greed}

    # --- 推薦強度榜：只對有實際多空方向的訊號評分排名（見 ranking.py） ---
    scored = [
        {**s, **ranking.score_signal(s, config.MIN_VOL_USDT, effective_min_amplitude)}
        for s in signals if s.get("signal_type") in ("long", "short")
    ]
    STATE.ranking = ranking.rank_signals(scored, top_n=config.RANKING_TOP_N)

    # 現在監控清單那幾檔的 _fetch_oi_delta 都跑完了（各自已經用「真正的上一輪基準值」算出
    # 正確的變化幅度），才把這一輪全市場的 OI 寫回資料庫當下次的基準——如果提早寫，前面
    # 監控清單的 db.get_previous_oi() 會讀到「這一輪」剛寫的值，變化幅度永遠算成 0%。
    if oi_rows:
        db.set_oi_snapshots_bulk(oi_rows, now_ms)


async def refresh_cycle(client: httpx.AsyncClient, skip_ai_reason: str | None = None):
    """完整跑一輪分析：回頭結算舊訊號 → 商品篩選（可能已被自動優化調整）→ 逐檔新聞情緒
    （見 _refresh_signals 內部說明，故意排在篩選「之後」才做）→ 每檔的技術訊號 → 多空共振
    → 記錄新訊號。由 app.py 在收到 POST /api/v1/analyze（手動「立即分析」，skip_ai_reason
    維持預設 None，行為跟原本完全一樣）或 scheduler.py 的背景排程任務（可能傳入非 None 的
    skip_ai_reason，見 ai_governor.py）呼叫。"""
    try:
        await _resolve_open_signals(client)
    except Exception as exc:  # noqa: BLE001 — 舊訊號結算失敗不該擋住本輪新訊號的產生
        logger.warning("resolving open signals failed: %s", exc)

    try:
        await _refresh_signals(client, skip_ai_reason=skip_ai_reason)
        STATE.last_error = None
    except Exception as exc:  # noqa: BLE001 — 失敗要讓使用者在儀表板上看到原因，不能悶掉
        logger.warning("signal refresh cycle failed: %s", exc)
        STATE.last_error = str(exc)
