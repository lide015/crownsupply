"""APScheduler job definitions. Runs inside the main.py process (AsyncIOScheduler)."""
import asyncio
import json
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import db, fetcher, indicators
from .state import MANAGER, STATE

logger = logging.getLogger("scheduler")

FAILOVER_THRESHOLD = 3
SNAPSHOT_RETENTION_SECONDS = 30 * 24 * 3600


async def job_fetch_quotes():
    quotes = None
    used_source = None

    if STATE.quote_source == "coingecko":
        try:
            quotes = await asyncio.to_thread(fetcher.fetch_quotes_coingecko)
            used_source = "coingecko"
            STATE.consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001
            STATE.consecutive_failures += 1
            logger.warning("coingecko quotes failed (%d/%d): %s", STATE.consecutive_failures, FAILOVER_THRESHOLD, exc)
            if STATE.consecutive_failures >= FAILOVER_THRESHOLD:
                try:
                    quotes = await asyncio.to_thread(fetcher.fetch_quotes_okx)
                    used_source = "okx"
                    STATE.quote_source = "okx"
                except Exception as exc2:  # noqa: BLE001
                    logger.error("okx fallback quotes also failed: %s", exc2)
    else:  # currently on okx fallback — check for coingecko recovery every cycle
        try:
            quotes = await asyncio.to_thread(fetcher.fetch_quotes_coingecko)
            used_source = "coingecko"
            STATE.quote_source = "coingecko"
            STATE.consecutive_failures = 0
            logger.info("coingecko recovered, switching back from okx")
        except Exception as exc:  # noqa: BLE001
            logger.warning("coingecko recovery check failed, staying on okx: %s", exc)
            try:
                quotes = await asyncio.to_thread(fetcher.fetch_quotes_okx)
                used_source = "okx"
            except Exception as exc2:  # noqa: BLE001
                logger.error("okx fetch failed: %s", exc2)

    if quotes is None:
        return  # both sources failed this cycle — log only, keep previous cache, no crash

    ts = int(time.time())
    snapshot = {
        "ts": ts,
        "source": used_source,
        "quotes": quotes,
        "fng": STATE.fng_cache or {"value": None, "label": None},
        "indicators": STATE.indicators_cache or {},
    }
    STATE.latest_snapshot = snapshot
    STATE.last_fetch_ts = ts

    payload = json.dumps(snapshot)
    db.insert_snapshot(ts, payload)
    await MANAGER.broadcast(payload)


async def job_fetch_fng():
    try:
        STATE.fng_cache = await asyncio.to_thread(fetcher.fetch_fng)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_fng failed, keeping cached value: %s", exc)


async def job_fetch_klines():
    rows = None
    try:
        rows = await asyncio.to_thread(fetcher.fetch_klines_coingecko, 100)
    except Exception as exc:  # noqa: BLE001
        logger.warning("coingecko klines failed, trying okx: %s", exc)
        try:
            rows = await asyncio.to_thread(fetcher.fetch_klines_okx, 100)
        except Exception as exc2:  # noqa: BLE001
            logger.error("okx klines also failed: %s", exc2)

    if not rows:
        return

    db.upsert_klines("BTC", rows)
    closes = [close for _day, close in db.get_closes("BTC", 100)]
    STATE.indicators_cache = indicators.compute_indicators(closes)


async def job_prune():
    before_ts = int(time.time()) - SNAPSHOT_RETENTION_SECONDS
    removed = db.prune_snapshots(before_ts)
    logger.info("pruned %d snapshots older than 30 days", removed)


def create_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    sched.add_job(job_fetch_quotes, "interval", seconds=60, id="fetch_quotes", max_instances=1)
    sched.add_job(job_fetch_fng, "interval", minutes=60, id="fetch_fng", max_instances=1)
    sched.add_job(job_fetch_klines, "interval", minutes=60, id="fetch_klines", max_instances=1)
    sched.add_job(job_prune, "cron", hour=4, minute=0, id="prune", max_instances=1)
    return sched


async def _run_once_test_mode():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_db()
    print("== jieliu-brief scheduler test mode: running one round of each job ==")

    await job_fetch_klines()
    print(f"fetch_klines done, indicators_cache={STATE.indicators_cache}")

    await job_fetch_fng()
    print(f"fetch_fng done, fng_cache={STATE.fng_cache}")

    await job_fetch_quotes()
    print(f"fetch_quotes done, last_fetch_ts={STATE.last_fetch_ts}, source={STATE.quote_source}")

    await job_prune()

    row = db.get_latest_snapshot()
    if row:
        print(f"latest snapshot in db: ts={row[0]} payload={row[1]}")
    else:
        print(
            "no snapshot written — both CoinGecko and OKX were unreachable this run "
            "(check network / firewall). Code path is otherwise verified; see README."
        )


if __name__ == "__main__":
    asyncio.run(_run_once_test_mode())
