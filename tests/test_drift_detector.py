"""
Phase 8 — Tests for the drift detector pipeline and lifecycle management.

Tests cover:
- Scenario 11: Duplicate drift detection (same drift twice → no second notification)
- Scenario 12: Drift resolution (drift disappears → RESOLVED notification)
- Full pipeline with mocked Terraform
- Error handling (Terraform failure → error in report, no exception raised)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.drift.detector import DriftDetector
from app.drift.models import AttributeChange, DriftAction, DriftedResource, DriftEvent, DriftSeverity, DriftStatus
from app.storage.local import LocalDriftStore
from app.terraform.parser import TerraformParser
from app.terraform.runner import TerraformInitError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SINGLE_DRIFT_PLAN = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_security_group_rule.app_https",
            "type": "ibm_is_security_group_rule",
            "name": "app_https",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["update"],
                "before": {"remote": "10.0.0.0/16"},
                "after": {"remote": "0.0.0.0/0"},
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}

NO_DRIFT_PLAN = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_security_group_rule.app_https",
            "type": "ibm_is_security_group_rule",
            "name": "app_https",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["no-op"],
                "before": {"remote": "10.0.0.0/16"},
                "after": {"remote": "10.0.0.0/16"},
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}


def _make_detector(tmp_path, plan_json=SINGLE_DRIFT_PLAN, terraform_fails=False):
    """Build a DriftDetector with mocked dependencies."""
    from app.agent.agent import DriftAnalysisAgent
    from app.agent.provider import NoOpLLMProvider
    from app.notifications.slack import SlackNotifier
    from app.policy.engine import PolicyEngine
    from app.terraform.runner import TerraformRunner

    # Mock runner
    runner = MagicMock(spec=TerraformRunner)
    if terraform_fails:
        runner.run_drift_detection.side_effect = TerraformInitError("Terraform init failed")
    else:
        runner.run_drift_detection.return_value = (plan_json, "1.9.0")

    # Real parser, policy engine, agent (noop)
    parser = TerraformParser()
    policy = PolicyEngine(rules_path="app/policy/rules.yaml")
    agent = DriftAnalysisAgent(provider=NoOpLLMProvider())

    # Real store (tmp)
    store = LocalDriftStore(state_dir=str(tmp_path / "state"))

    # Mock notifier
    notifier = AsyncMock(spec=SlackNotifier)
    notifier.send_drift_notification.return_value = True
    notifier.send_resolution_notification.return_value = True

    return DriftDetector(
        runner=runner,
        parser=parser,
        policy_engine=policy,
        agent=agent,
        store=store,
        notifier=notifier,
    ), notifier


# ---------------------------------------------------------------------------
# Basic pipeline tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_detects_drift(tmp_path) -> None:
    """Pipeline should detect drift and return report with resources."""
    detector, _ = _make_detector(tmp_path)
    report = await detector.run()

    assert report.drift_detected is True
    assert report.resource_count == 1
    assert report.resources[0].address == "ibm_is_security_group_rule.app_https"
    assert report.terraform_plan_ok is True


@pytest.mark.asyncio
async def test_pipeline_no_drift(tmp_path) -> None:
    """Pipeline should return no drift when all resources are no-op."""
    detector, _ = _make_detector(tmp_path, plan_json=NO_DRIFT_PLAN)
    report = await detector.run()

    assert report.drift_detected is False
    assert report.resource_count == 0


@pytest.mark.asyncio
async def test_pipeline_sets_policy_severity(tmp_path) -> None:
    """Policy engine should assign severity to drifted resources."""
    detector, _ = _make_detector(tmp_path)
    report = await detector.run()

    resource = report.resources[0]
    assert resource.policy_severity is not None
    assert resource.policy_severity in (DriftSeverity.CRITICAL, DriftSeverity.HIGH)


@pytest.mark.asyncio
async def test_pipeline_new_drift_sends_notification(tmp_path) -> None:
    """First detection should send a Slack notification."""
    detector, notifier = _make_detector(tmp_path)
    await detector.run()

    notifier.send_drift_notification.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 11: Duplicate drift detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_drift_no_second_notification(tmp_path) -> None:
    """
    Scenario 11: Running the same drift twice should NOT send a second notification.

    First run: NEW → notify
    Second run: ACTIVE → no notify
    """
    detector, notifier = _make_detector(tmp_path)

    # First run — should notify
    await detector.run()
    assert notifier.send_drift_notification.call_count == 1

    # Second run with same drift — should NOT notify again
    await detector.run()
    assert notifier.send_drift_notification.call_count == 1  # Still just 1


@pytest.mark.asyncio
async def test_duplicate_drift_marks_event_active(tmp_path) -> None:
    """After the second run, the event should be ACTIVE."""
    detector, _ = _make_detector(tmp_path)
    await detector.run()  # First: NEW
    await detector.run()  # Second: ACTIVE

    events = detector._store.list_events()
    assert len(events) == 1
    assert events[0].status == DriftStatus.ACTIVE


# ---------------------------------------------------------------------------
# Scenario 12: Drift resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drift_resolution_notifies(tmp_path) -> None:
    """
    Scenario 12: When drift disappears, status should become RESOLVED
    and a resolution notification should be sent.
    """
    detector, notifier = _make_detector(tmp_path)

    # First run: detect drift
    await detector.run()
    assert notifier.send_drift_notification.call_count == 1

    # Second run: no drift (resource is back to expected state)
    runner_mock = detector._runner
    runner_mock.run_drift_detection.return_value = (NO_DRIFT_PLAN, "1.9.0")
    await detector.run()

    # Resolution notification should have been sent
    notifier.send_resolution_notification.assert_called_once()

    # Event should be RESOLVED
    events = detector._store.list_events()
    assert any(e.status == DriftStatus.RESOLVED for e in events)


@pytest.mark.asyncio
async def test_resolved_drift_no_re_resolve(tmp_path) -> None:
    """A RESOLVED event should not trigger another resolution notification on next no-drift run."""
    detector, notifier = _make_detector(tmp_path)

    await detector.run()  # detect drift
    detector._runner.run_drift_detection.return_value = (NO_DRIFT_PLAN, "1.9.0")
    await detector.run()  # resolve

    # Run again with no drift — should NOT send resolution again
    await detector.run()
    assert notifier.send_resolution_notification.call_count == 1  # Still 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terraform_failure_captured_in_report(tmp_path) -> None:
    """Terraform failure should be captured in report, not raised."""
    detector, notifier = _make_detector(tmp_path, terraform_fails=True)

    report = await detector.run()

    # Should NOT raise
    assert report.error_message is not None
    assert "Terraform" in report.error_message or "init" in report.error_message.lower()
    assert report.drift_detected is False

    # Should NOT have sent notifications
    notifier.send_drift_notification.assert_not_called()


@pytest.mark.asyncio
async def test_slack_failure_does_not_lose_drift(tmp_path) -> None:
    """Slack failure should not prevent drift from being saved to the store."""
    detector, notifier = _make_detector(tmp_path)
    notifier.send_drift_notification.return_value = False  # Slack fails

    report = await detector.run()

    # Drift should still be detected
    assert report.drift_detected is True

    # Event should still be saved to store
    events = detector._store.list_events()
    assert len(events) >= 1
