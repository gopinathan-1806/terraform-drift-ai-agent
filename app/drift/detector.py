"""
Drift detector — pipeline orchestrator.

Coordinates the full drift detection pipeline:

    1. TerraformRunner   — executes terraform plan -refresh-only + show -json
    2. TerraformParser   — parses the JSON into DriftedResource models
    3. PolicyEngine      — assigns deterministic severity to each resource
    4. DriftAnalysisAgent — AI risk analysis and human-readable explanation
    5. LocalDriftStore   — persists drift events, manages lifecycle
    6. SlackNotifier     — sends notifications for new/changed/resolved drift

Lifecycle management:
    NEW      → first detection, notify
    ACTIVE   → same drift on subsequent run, no new notification
    CHANGED  → drift changed (different actual value), notify
    RESOLVED → drift no longer present, notify if configured

IMPORTANT:
    - terraform apply is NEVER called
    - AI agent NEVER executes Terraform
    - Notifications are NEVER duplicated for identical unchanged drift
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agent.agent import DriftAnalysisAgent
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.drift.fingerprint import DriftFingerprint
from app.drift.models import (
    DriftEvent,
    DriftReport,
    DriftSeverity,
    DriftStatus,
    DriftedResource,
)
from app.notifications.slack import SlackNotifier
from app.policy.engine import PolicyEngine
from app.storage.local import LocalDriftStore
from app.terraform.parser import TerraformParser
from app.terraform.runner import TerraformRunner

logger = get_logger("drift.detector")
settings = get_settings()

# Module-level singleton for the latest report (in-memory cache for API)
_latest_report: DriftReport | None = None


class DriftDetector:
    """
    Orchestrates the full drift detection pipeline.

    Designed to be called both from the scheduler (periodic) and from
    the API endpoint (on-demand trigger).
    """

    def __init__(
        self,
        runner: TerraformRunner | None = None,
        parser: TerraformParser | None = None,
        policy_engine: PolicyEngine | None = None,
        agent: DriftAnalysisAgent | None = None,
        store: LocalDriftStore | None = None,
        notifier: SlackNotifier | None = None,
    ) -> None:
        self._runner = runner or TerraformRunner()
        self._parser = parser or TerraformParser()
        self._policy = policy_engine or PolicyEngine()
        self._agent = agent or DriftAnalysisAgent()
        self._store = store or LocalDriftStore()
        self._notifier = notifier or SlackNotifier()

    def get_latest_report(self) -> DriftReport | None:
        """Return the most recent drift report (in-memory)."""
        global _latest_report
        return _latest_report

    async def run(self) -> DriftReport:
        """
        Execute the full drift detection pipeline.

        Returns:
            DriftReport — complete result of this run.

        Never raises — all errors are captured into the report.
        """
        global _latest_report
        execution_id = str(uuid.uuid4())
        start = time.monotonic()

        logger.info(
            "Drift detection run starting",
            execution_id=execution_id,
            environment=settings.environment,
            workspace=settings.terraform_workspace,
        )

        report = DriftReport(
            execution_id=execution_id,
            environment=settings.environment,
            terraform_workspace=settings.terraform_workspace,
            drift_detected=False,
        )

        try:
            report = await self._run_pipeline(report, start)
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            report.error_message = str(exc)[:500]
            report.duration_seconds = round(duration, 3)
            logger.error(
                "Drift detection pipeline failed",
                execution_id=execution_id,
                error=str(exc)[:200],
                duration_seconds=report.duration_seconds,
            )

        _latest_report = report
        return report

    async def _run_pipeline(self, report: DriftReport, start: float) -> DriftReport:
        """Internal pipeline execution."""
        # ── Step 1: Terraform ──────────────────────────────────────────
        try:
            plan_json, tf_version = self._runner.run_drift_detection()
            report.terraform_init_ok = True
            report.terraform_validate_ok = True
            report.terraform_plan_ok = True
            report.terraform_version = tf_version
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            report.duration_seconds = round(duration, 3)
            report.error_message = f"Terraform execution failed: {exc!s}"
            logger.error("Terraform execution failed", error=str(exc)[:300])
            raise

        # ── Step 2: Parse ──────────────────────────────────────────────
        drifted_resources = self._parser.parse(plan_json)
        report.drift_detected = len(drifted_resources) > 0

        if not drifted_resources:
            duration = time.monotonic() - start
            report.duration_seconds = round(duration, 3)
            logger.info(
                "No drift detected",
                execution_id=report.execution_id,
                duration_seconds=report.duration_seconds,
            )
            # Check for previously tracked events that are now resolved
            await self._handle_resolutions(set())
            return report

        # ── Step 3: Policy engine ──────────────────────────────────────
        drifted_resources = self._policy.evaluate_all(drifted_resources)

        # ── Step 4: AI analysis ────────────────────────────────────────
        ai_results = await self._agent.analyze_all(drifted_resources)

        # ── Step 5: Lifecycle + notification ──────────────────────────
        current_fingerprints: set[str] = set()
        for resource, ai_result in zip(drifted_resources, ai_results):
            for change in resource.changes:
                fp = DriftFingerprint.for_attribute_change(resource.address, change)
                current_fingerprints.add(fp)
                await self._process_drift_event(resource, change, fp, ai_result)

        # ── Step 6: Resolve events no longer present ──────────────────
        await self._handle_resolutions(current_fingerprints)

        report.resources = drifted_resources
        duration = time.monotonic() - start
        report.duration_seconds = round(duration, 3)

        logger.info(
            "Drift detection run complete",
            execution_id=report.execution_id,
            drift_detected=report.drift_detected,
            resources_changed=len(drifted_resources),
            highest_severity=report.highest_severity.value if report.highest_severity else None,
            duration_seconds=report.duration_seconds,
        )
        return report

    async def _process_drift_event(
        self,
        resource: DriftedResource,
        change: Any,
        fingerprint: str,
        ai_result: Any,
    ) -> None:
        """
        Determine drift lifecycle status and send notification if needed.

        Lifecycle transitions:
        - No existing event AND no prior event for same resource+attribute → NEW (notify)
        - No existing event BUT prior active event for same resource+attribute → CHANGED (notify)
        - Existing ACTIVE/NEW/CHANGED with same fingerprint → ACTIVE (no notify)
        - Existing RESOLVED → NEW (notify again)
        """
        existing = self._store.get_event(fingerprint)
        now = datetime.now(timezone.utc)

        if existing is None:
            # Check whether this resource+attribute had a different active drift before
            # (i.e. the actual value changed, producing a new fingerprint → CHANGED)
            prior_event = self._find_active_event_for_attribute(
                resource.address, change.attribute, exclude_fingerprint=fingerprint
            )

            if prior_event is not None and prior_event.status in (
                DriftStatus.NEW, DriftStatus.ACTIVE, DriftStatus.CHANGED
            ):
                # Supersede the old event — mark it resolved silently, then raise CHANGED
                resolved_prior = prior_event.model_copy(
                    update={
                        "status": DriftStatus.RESOLVED,
                        "last_detected_at": now,
                    }
                )
                self._store.save_event(resolved_prior)

                event = DriftEvent(
                    fingerprint=fingerprint,
                    status=DriftStatus.CHANGED,
                    first_detected_at=prior_event.first_detected_at,
                    last_detected_at=now,
                    resource_address=resource.address,
                    changed_attribute=change.attribute,
                    expected_value=str(change.expected) if change.expected is not None else "",
                    actual_value=str(change.actual) if change.actual is not None else "",
                    policy_severity=resource.policy_severity,
                )
                self._store.save_event(event)
                logger.info(
                    "Drift value changed",
                    fingerprint=fingerprint[:12],
                    resource=resource.address,
                    attribute=change.attribute,
                )
                await self._send_drift_notification(resource, event, ai_result)
            else:
                # Brand-new drift
                event = DriftEvent(
                    fingerprint=fingerprint,
                    status=DriftStatus.NEW,
                    first_detected_at=now,
                    last_detected_at=now,
                    resource_address=resource.address,
                    changed_attribute=change.attribute,
                    expected_value=str(change.expected) if change.expected is not None else "",
                    actual_value=str(change.actual) if change.actual is not None else "",
                    policy_severity=resource.policy_severity,
                )
                self._store.save_event(event)
                logger.info(
                    "New drift event",
                    fingerprint=fingerprint[:12],
                    resource=resource.address,
                    attribute=change.attribute,
                )
                await self._send_drift_notification(resource, event, ai_result)

        elif existing.status in (DriftStatus.NEW, DriftStatus.ACTIVE, DriftStatus.CHANGED):
            # Same drift persists — update timestamp but don't re-notify
            updated = existing.model_copy(
                update={
                    "status": DriftStatus.ACTIVE,
                    "last_detected_at": now,
                }
            )
            self._store.save_event(updated)
            logger.debug(
                "Drift still active, no new notification",
                fingerprint=fingerprint[:12],
                resource=resource.address,
            )

        elif existing.status == DriftStatus.RESOLVED:
            # Previously resolved drift has reappeared
            event = existing.model_copy(
                update={
                    "status": DriftStatus.NEW,
                    "last_detected_at": now,
                }
            )
            self._store.save_event(event)
            await self._send_drift_notification(resource, event, ai_result)

    def _find_active_event_for_attribute(
        self,
        resource_address: str,
        attribute: str,
        exclude_fingerprint: str,
    ) -> "DriftEvent | None":
        """
        Search the store for an existing active event matching resource_address +
        attribute, but with a different fingerprint (meaning the actual value
        changed between runs, which produces a new fingerprint).

        Returns the matching event, or None if not found.
        """
        for event in self._store.list_events():
            if (
                event.resource_address == resource_address
                and event.changed_attribute == attribute
                and event.fingerprint != exclude_fingerprint
                and event.status in (DriftStatus.NEW, DriftStatus.ACTIVE, DriftStatus.CHANGED)
            ):
                return event
        return None

    async def _handle_resolutions(self, current_fingerprints: set[str]) -> None:
        """
        For any previously tracked drift that is no longer in the current run,
        mark it as RESOLVED and optionally send a Slack notification.
        """
        all_events = self._store.list_events()
        for event in all_events:
            if event.status in (DriftStatus.NEW, DriftStatus.ACTIVE, DriftStatus.CHANGED):
                if event.fingerprint not in current_fingerprints:
                    resolved = event.model_copy(
                        update={
                            "status": DriftStatus.RESOLVED,
                            "last_detected_at": datetime.now(timezone.utc),
                        }
                    )
                    self._store.save_event(resolved)
                    logger.info(
                        "Drift resolved",
                        fingerprint=event.fingerprint[:12],
                        resource=event.resource_address,
                    )
                    if settings.drift_notify_on_resolve:
                        await self._notifier.send_resolution_notification(resolved)

    async def _send_drift_notification(
        self,
        resource: DriftedResource,
        event: DriftEvent,
        ai_result: Any,
    ) -> None:
        """Send a Slack notification for a drift event."""
        try:
            await self._notifier.send_drift_notification(
                resource=resource,
                event=event,
                ai_summary=ai_result.summary if ai_result else None,
                ai_impact=ai_result.impact if ai_result else None,
                ai_recommended_action=ai_result.recommended_action if ai_result else None,
                ai_risk_level=ai_result.risk_level if ai_result else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Slack notification failed (drift event preserved)",
                resource=resource.address,
                error_type=type(exc).__name__,
            )
