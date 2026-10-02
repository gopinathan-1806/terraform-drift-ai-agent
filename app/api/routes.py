"""
FastAPI routes for IBM Cloud Terraform DriftGuard AI.

Endpoints:
  GET  /health              — liveness probe
  GET  /api/drift           — latest drift report
  POST /api/drift/check     — manually trigger a drift check
  GET  /api/drift/history   — recent drift events
  POST /api/test/slack      — send a test Slack notification

IMPORTANT: None of these endpoints expose secrets or credentials.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.config.logging import get_logger
from app.config.settings import get_settings

router = APIRouter()
logger = get_logger("api")
settings = get_settings()

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: str


class DriftCheckResponse(BaseModel):
    execution_id: str
    drift_detected: bool
    resources_changed: int
    highest_severity: str | None
    message: str


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    tags=["system"],
)
async def health() -> HealthResponse:
    """Return application health status."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/api/drift",
    summary="Latest drift report",
    tags=["drift"],
)
async def get_latest_drift() -> dict[str, Any]:
    """
    Return the most recent drift detection result.

    Returns 204 if no drift check has been run yet.
    """
    # Import here to avoid circular imports at module load time.
    from app.drift.detector import DriftDetector  # noqa: PLC0415

    detector = DriftDetector()
    report = detector.get_latest_report()
    if report is None:
        # HTTP 204 must have no body — HTTPException(204) is incorrect because
        # it attaches a JSON body, violating the HTTP spec.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return report.model_dump(mode="json")


@router.post(
    "/api/drift/check",
    response_model=DriftCheckResponse,
    summary="Trigger a drift check",
    tags=["drift"],
)
async def trigger_drift_check() -> DriftCheckResponse:
    """
    Manually trigger a Terraform drift detection run.

    This executes:
      1. terraform init
      2. terraform validate
      3. terraform plan -refresh-only
      4. terraform show -json
      5. Parse, analyze, and notify.

    NOTE: terraform apply is NEVER called.
    """
    from app.drift.detector import DriftDetector  # noqa: PLC0415

    logger.info("Manual drift check triggered via API")
    detector = DriftDetector()

    try:
        report = await detector.run()
    except Exception as exc:  # noqa: BLE001
        logger.error("Drift check failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Drift check failed. Check application logs for details.",
        ) from exc

    return DriftCheckResponse(
        execution_id=report.execution_id,
        drift_detected=report.drift_detected,
        resources_changed=report.resource_count,
        highest_severity=report.highest_severity.value if report.highest_severity else None,
        message="Drift check completed successfully." if report.terraform_plan_ok else "Drift check encountered errors.",
    )


@router.get(
    "/api/drift/history",
    summary="Drift event history",
    tags=["drift"],
)
async def get_drift_history() -> dict[str, Any]:
    """Return recent drift events from local state store."""
    from app.storage.local import LocalDriftStore  # noqa: PLC0415

    store = LocalDriftStore()
    events = store.list_events()
    return {
        "total": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }


@router.post(
    "/api/test/slack",
    summary="Send a test Slack notification",
    tags=["notifications"],
)
async def test_slack() -> dict[str, str]:
    """
    Send a test message to the configured Slack webhook.

    Useful to verify the webhook is working before running drift checks.
    """
    from app.notifications.slack import SlackNotifier  # noqa: PLC0415

    if not settings.slack_webhook_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SLACK_WEBHOOK_URL is not configured.",
        )

    notifier = SlackNotifier()
    success = await notifier.send_test_message()
    if success:
        return {"status": "ok", "message": "Test notification sent to Slack."}
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to send Slack test notification. Check SLACK_WEBHOOK_URL.",
    )
