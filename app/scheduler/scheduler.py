"""
Drift detection scheduler.

Runs drift checks at a configurable interval using APScheduler.
Designed for:
  - Local development (run directly)
  - Docker deployment
  - Future IBM Cloud Code Engine deployment

Configuration:
  DRIFT_CHECK_INTERVAL_SECONDS (default: 300)

The scheduler runs as a background task within the FastAPI lifespan.
"""
from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config.logging import get_logger
from app.config.settings import get_settings
from app.drift.detector import DriftDetector

logger = get_logger("scheduler")
settings = get_settings()


class DriftScheduler:
    """
    Periodic drift detection scheduler.

    Wraps APScheduler to run the DriftDetector pipeline at the configured
    interval.  Uses async execution so it integrates naturally with FastAPI.
    """

    def __init__(self, detector: DriftDetector | None = None) -> None:
        self._detector = detector or DriftDetector()
        self._scheduler = AsyncIOScheduler()
        self._running = False

    def start(self) -> None:
        """Start the scheduler. Should be called during application startup."""
        interval = settings.drift_check_interval_seconds
        self._scheduler.add_job(
            self._run_check,
            trigger=IntervalTrigger(seconds=interval),
            id="drift_detection",
            name="IBM Cloud Terraform Drift Detection",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            "Drift scheduler started",
            interval_seconds=interval,
        )

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Drift scheduler stopped")

    async def run_once(self) -> None:
        """Run a single drift detection check immediately (for testing/on-demand)."""
        await self._run_check()

    async def _run_check(self) -> None:
        """Execute a drift detection run. Errors are logged but never propagated."""
        logger.info("Scheduled drift check starting")
        try:
            report = await self._detector.run()
            logger.info(
                "Scheduled drift check complete",
                execution_id=report.execution_id,
                drift_detected=report.drift_detected,
                resources_changed=report.resource_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Scheduled drift check failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
