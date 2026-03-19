"""
APScheduler-based periodic scan scheduler.

Runs market scans at configurable intervals (default: every 12 hours).
"""

import asyncio
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from config import SCAN_INTERVAL_HOURS

logger = logging.getLogger("scheduler")

scheduler = BackgroundScheduler()


def _run_scan_job():
    """Wrapper to run the async scan from the sync scheduler."""
    from main import run_scan
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_scan())
    finally:
        loop.close()


def start_scheduler():
    """Start the periodic scan scheduler."""
    scheduler.add_job(
        _run_scan_job,
        "interval",
        hours=SCAN_INTERVAL_HOURS,
        id="market_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — scanning every {SCAN_INTERVAL_HOURS} hours")


def stop_scheduler():
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
