"""背景排程（選用，預設關閉）：把「立即分析」用的同一套 background.refresh_cycle 邏輯
包成一個可選的定時任務，用 APScheduler 的 AsyncIOScheduler 掛在 app.py 的 lifespan 裡。
**預設關閉**——這跟本系統原本「用量完全由使用者點擊次數決定」的設計精神不同，需要使用者
主動開啟（見 POST /api/v1/scheduler）。開關／間隔存在 SQLite（db.get_param/set_param），
跨重啟持續生效，不用改 .env、不用重啟伺服器就能調整。

規則大腦（技術面，見 strategy.py／brain.py）每一輪排程都跑，零成本；AI 新聞情緒是否呼叫
由 ai_governor.should_skip_ai_this_cycle 決定（每日上限、連續失敗斷路器、新技術訊號優先、
預設每 N 輪才問一次）——這是回應「自動化要開、但 AI 用量必須可控、優先靠自己的規則大腦
分析」這個明確要求的具體實作，不是每次排程觸發都無條件燒一次 AI 呼叫。

跟 app.py 的 POST /api/v1/analyze 共用同一把 `_analyze_lock`：排程觸發時如果剛好使用者
正在手動分析，這一輪排程直接跳過（不排隊等待），避免兩邊互踩 STATE、重複計費——下一個
排程間隔會再試。
"""
import asyncio
import logging
import time

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import ai_governor, background, config, db, healthcheck
from .state import STATE

logger = logging.getLogger("scheduler")

JOB_ID = "auto_analyze"

_scheduler: AsyncIOScheduler | None = None
# 純記憶體計數器，跨重啟歸零——只是拿來算「每 N 輪」的節流週期用，重啟後從頭數不影響
# 正確性，頂多重啟後頭幾輪的節流節奏跟重啟前接不起來（多問或少問一次 AI），不是安全問題。
_cycle_count = 0


def is_enabled() -> bool:
    return db.get_param("SCHEDULER_ENABLED", 1.0 if config.SCHEDULER_ENABLED_DEFAULT else 0.0) != 0.0


def get_interval_seconds() -> int:
    stored = db.get_param("SCHEDULER_INTERVAL_SECONDS", float(config.SCHEDULER_INTERVAL_SECONDS_DEFAULT))
    return max(int(stored), config.SCHEDULER_MIN_INTERVAL_SECONDS)


def _set_enabled(enabled: bool, now_ms: int):
    db.set_param("SCHEDULER_ENABLED", 1.0 if enabled else 0.0, now_ms, None)


def _set_interval_seconds(seconds: int, now_ms: int) -> int:
    clamped = max(int(seconds), config.SCHEDULER_MIN_INTERVAL_SECONDS)
    db.set_param("SCHEDULER_INTERVAL_SECONDS", float(clamped), now_ms, None)
    return clamped


def _ai_usage_today(now_ms: int) -> int:
    """只讀：今天(UTC)背景排程已經呼叫過幾次 AI（見 ai_governor.current_daily_count）。"""
    stored_day = db.get_param("AI_USAGE_DAY", -1.0)
    stored_count = db.get_param("AI_USAGE_COUNT", 0.0)
    return ai_governor.current_daily_count(
        int(stored_day) if stored_day >= 0 else None, int(stored_count), now_ms
    )


def _increment_ai_usage(now_ms: int) -> int:
    stored_day = db.get_param("AI_USAGE_DAY", -1.0)
    stored_count = db.get_param("AI_USAGE_COUNT", 0.0)
    new_day, new_count = ai_governor.next_daily_count(
        int(stored_day) if stored_day >= 0 else None, int(stored_count), now_ms
    )
    db.set_param("AI_USAGE_DAY", float(new_day), now_ms, None)
    db.set_param("AI_USAGE_COUNT", float(new_count), now_ms, None)
    return new_count


def _next_run_at_ms() -> int | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return int(job.next_run_time.timestamp() * 1000)


def status() -> dict:
    """給 GET /api/v1/scheduler 用的狀態面板資料——開關、間隔、上次/下次執行時間與結果、
    今日 AI 呼叫次數與上限、AI 連續失敗次數、這一輪 AI 有沒有被跳過及原因，一次看到，
    不用查 log（見 README「背景排程」一節）。"""
    now_ms = int(time.time() * 1000)
    return {
        "enabled": is_enabled(),
        "interval_seconds": get_interval_seconds(),
        "min_interval_seconds": config.SCHEDULER_MIN_INTERVAL_SECONDS,
        "last_run_at": STATE.scheduler_last_run_at,
        "last_run_status": STATE.scheduler_last_run_status,
        "last_run_error": STATE.scheduler_last_run_error,
        "next_run_at": _next_run_at_ms(),
        "ai_calls_today": _ai_usage_today(now_ms),
        "ai_daily_cap": config.AI_DAILY_CALL_CAP,
        "ai_refresh_every_n_cycles": config.AI_REFRESH_EVERY_N_CYCLES,
        "ai_consecutive_failures": STATE.ai_consecutive_failures,
        "ai_failure_threshold": config.AI_FAILURE_THRESHOLD,
        "ai_skip_reason": STATE.ai_skip_reason,
        "healthcheck_configured": bool(config.HEALTHCHECK_PING_URL.strip()),
    }


async def _run_scheduled_cycle(client: httpx.AsyncClient, lock: asyncio.Lock):
    """實際被 APScheduler 定時呼叫的工作函式。"""
    global _cycle_count

    if lock.locked():
        # 使用者剛好手動按「立即分析」在跑——這一輪排程直接跳過，不排隊等待，避免拖長
        # 使用者那次手動點擊的等待時間；下一個排程間隔會再試。
        logger.info("scheduled cycle skipped: manual analyze already in progress")
        return

    _cycle_count += 1
    now_ms = int(time.time() * 1000)
    calls_today = _ai_usage_today(now_ms)
    skip_reason = ai_governor.should_skip_ai_this_cycle(
        cycle_count=_cycle_count,
        refresh_every_n_cycles=config.AI_REFRESH_EVERY_N_CYCLES,
        has_new_technical_signal=STATE.had_new_signal_last_cycle,
        calls_today=calls_today,
        daily_cap=config.AI_DAILY_CALL_CAP,
        consecutive_failures=STATE.ai_consecutive_failures,
        failure_threshold=config.AI_FAILURE_THRESHOLD,
    )

    async with lock:
        STATE.is_analyzing = True
        try:
            await background.refresh_cycle(client, skip_ai_reason=skip_reason)
            STATE.scheduler_last_run_status = "ok"
            STATE.scheduler_last_run_error = None
        except Exception as exc:  # noqa: BLE001 — 排程任務不能讓整個 scheduler 掛掉，下一輪還要能繼續跑
            logger.exception("scheduled analyze cycle failed")
            STATE.scheduler_last_run_status = "error"
            STATE.scheduler_last_run_error = str(exc)
        finally:
            STATE.is_analyzing = False
            STATE.scheduler_last_run_at = time.strftime("%Y-%m-%d %H:%M:%S")

    # AI 用量／斷路器計數只在「這一輪真的嘗試呼叫了 AI」才更新——被節流跳過的輪次不計費、
    # 不影響連續失敗計數（跳過本來就不是失敗）。
    if not skip_reason and STATE.last_ai_call_attempted:
        _increment_ai_usage(now_ms)
        STATE.ai_consecutive_failures = STATE.ai_consecutive_failures + 1 if STATE.last_ai_call_failed else 0

    # 死人開關 ping（選用，見 healthcheck.py）：沒設定 HEALTHCHECK_PING_URL 就完全跳過，
    # 不影響上面已經完成的排程結果。這裡的「成功/失敗」對應排程這一輪本身有沒有正常
    # 跑完（含技術面分析），跟上面的 AI 用量治理是兩件獨立的事——排程正常跑完但這輪
    # 剛好被節流跳過 AI 呼叫，對死人開關來說仍然算「排程活著」，不算失敗。
    await healthcheck.ping(client, config.HEALTHCHECK_PING_URL, success=STATE.scheduler_last_run_status == "ok")


def start(client: httpx.AsyncClient, lock: asyncio.Lock):
    """app.py 的 lifespan 開機時呼叫一次：建立排程任務（永遠建立，方便隨時用 API 開啟），
    是否真的觸發交給 is_enabled() 決定——沒開啟就馬上把這個 job 暫停住。"""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_scheduled_cycle,
        IntervalTrigger(seconds=get_interval_seconds()),
        id=JOB_ID,
        args=[client, lock],
        max_instances=1,  # 上一輪還沒結束（罕見，例如 OKX 回應異常慢）就不會疊加觸發下一輪
    )
    _scheduler.start()
    if not is_enabled():
        _scheduler.pause_job(JOB_ID)
    logger.info(
        "background scheduler ready (enabled=%s, interval=%ss) — this is opt-in, not the manual-trigger flow",
        is_enabled(), get_interval_seconds(),
    )


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def enable(now_ms: int):
    _set_enabled(True, now_ms)
    if _scheduler is not None:
        _scheduler.resume_job(JOB_ID)


def disable(now_ms: int):
    _set_enabled(False, now_ms)
    if _scheduler is not None:
        _scheduler.pause_job(JOB_ID)


def update_interval(seconds: int, now_ms: int) -> int:
    clamped = _set_interval_seconds(seconds, now_ms)
    if _scheduler is not None:
        _scheduler.reschedule_job(JOB_ID, trigger=IntervalTrigger(seconds=clamped))
    return clamped
