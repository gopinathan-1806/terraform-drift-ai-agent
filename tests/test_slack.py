"""
Phase 7 — Tests for the Slack notification system.

All HTTP calls are mocked with respx.
Tests cover:
- Successful notification (NEW, CHANGED, RESOLVED)
- Slack failure (Scenario 10)
- Missing webhook URL — graceful skip
- Sensitive values masked in message
- Slack disabled setting
- Test message
"""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.drift.models import AttributeChange, DriftAction, DriftedResource, DriftEvent, DriftSeverity, DriftStatus
from app.notifications.slack import SlackNotifier
import app.notifications.slack as slack_module

TEST_WEBHOOK_URL = "https://hooks.slack.com/services/TEST/FAKE/WEBHOOK"


@pytest.fixture(autouse=True)
def enable_slack():
    """Ensure Slack is enabled for all tests in this module (test env sets it disabled)."""
    original = slack_module.settings.slack_enabled
    object.__setattr__(slack_module.settings, "slack_enabled", True)
    yield
    object.__setattr__(slack_module.settings, "slack_enabled", original)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resource(is_sensitive: bool = False) -> DriftedResource:
    return DriftedResource(
        address="ibm_is_security_group_rule.app_https",
        resource_type="ibm_is_security_group_rule",
        resource_name="app_https",
        action=DriftAction.UPDATE,
        policy_severity=DriftSeverity.CRITICAL,
        changes=[
            AttributeChange(
                attribute="remote",
                expected="10.0.0.0/16",
                actual="0.0.0.0/0",
                is_sensitive=is_sensitive,
            )
        ],
    )


def _make_event(status: DriftStatus = DriftStatus.NEW) -> DriftEvent:
    return DriftEvent(
        fingerprint="a" * 64,
        resource_address="ibm_is_security_group_rule.app_https",
        changed_attribute="remote",
        expected_value="10.0.0.0/16",
        actual_value="0.0.0.0/0",
        policy_severity=DriftSeverity.CRITICAL,
        status=status,
    )


# ---------------------------------------------------------------------------
# Successful notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_send_new_drift_success() -> None:
    """Successful Slack notification for new drift."""
    respx.post(TEST_WEBHOOK_URL).mock(return_value=Response(200, text="ok"))

    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    result = await notifier.send_drift_notification(
        resource=_make_resource(),
        event=_make_event(DriftStatus.NEW),
        ai_summary="Terraform indicates remote CIDR changed to 0.0.0.0/0.",
        ai_impact="Potential impact: public internet access enabled.",
        ai_recommended_action="Revert through Terraform if unauthorized.",
        ai_risk_level="CRITICAL",
    )
    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_send_resolution_success() -> None:
    """Successful Slack notification for drift resolution."""
    respx.post(TEST_WEBHOOK_URL).mock(return_value=Response(200, text="ok"))

    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    result = await notifier.send_resolution_notification(event=_make_event(DriftStatus.RESOLVED))
    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_send_test_message_success() -> None:
    """Test message should be sent successfully."""
    respx.post(TEST_WEBHOOK_URL).mock(return_value=Response(200, text="ok"))

    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    result = await notifier.send_test_message()
    assert result is True


# ---------------------------------------------------------------------------
# Scenario 10: Slack failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_send_notification_returns_false_on_http_error() -> None:
    """Scenario 10: Slack HTTP error should return False, not raise."""
    respx.post(TEST_WEBHOOK_URL).mock(return_value=Response(500, text="Internal Server Error"))

    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    result = await notifier.send_drift_notification(
        resource=_make_resource(),
        event=_make_event(),
    )
    assert result is False


@pytest.mark.asyncio
@respx.mock
async def test_send_notification_returns_false_on_wrong_body() -> None:
    """Slack returning 200 but not 'ok' text should return False."""
    respx.post(TEST_WEBHOOK_URL).mock(return_value=Response(200, text="channel_not_found"))

    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    result = await notifier.send_drift_notification(
        resource=_make_resource(),
        event=_make_event(),
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_notification_no_webhook_returns_false() -> None:
    """Missing webhook URL should return False without HTTP call."""
    notifier = SlackNotifier(webhook_url="")
    result = await notifier.send_drift_notification(
        resource=_make_resource(),
        event=_make_event(),
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_test_no_webhook_returns_false() -> None:
    notifier = SlackNotifier(webhook_url="")
    result = await notifier.send_test_message()
    assert result is False


# ---------------------------------------------------------------------------
# Sensitive values must NOT appear in Slack messages
# ---------------------------------------------------------------------------


def test_slack_blocks_mask_sensitive_values() -> None:
    """Sensitive attribute values must not be included in Slack blocks."""
    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    resource = _make_resource(is_sensitive=True)
    # Temporarily set actual to something identifiable
    resource.changes[0] = AttributeChange(
        attribute="api_key",
        expected="SUPER_SECRET_OLD",
        actual="SUPER_SECRET_NEW",
        is_sensitive=True,
    )
    event = _make_event()

    blocks = notifier._build_drift_blocks(
        resource=resource,
        event=event,
        ai_summary=None,
        ai_impact=None,
        ai_recommended_action=None,
        ai_risk_level=None,
    )

    # Serialize blocks to string and verify no secret values appear
    import json
    blocks_str = json.dumps(blocks)
    assert "SUPER_SECRET_OLD" not in blocks_str
    assert "SUPER_SECRET_NEW" not in blocks_str
    assert "[sensitive]" in blocks_str


# ---------------------------------------------------------------------------
# Slack disabled setting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_notification_returns_true_when_disabled(monkeypatch) -> None:
    """When SLACK_ENABLED=false, notifications should return True (silent skip)."""
    import app.notifications.slack as slack_module
    original = slack_module.settings.slack_enabled
    try:
        # Patch settings.slack_enabled
        object.__setattr__(slack_module.settings, "slack_enabled", False)
        notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
        result = await notifier.send_drift_notification(
            resource=_make_resource(),
            event=_make_event(),
        )
        assert result is True
    finally:
        object.__setattr__(slack_module.settings, "slack_enabled", original)


# ---------------------------------------------------------------------------
# Block structure validation
# ---------------------------------------------------------------------------


def test_drift_blocks_contain_required_fields() -> None:
    """Drift blocks must include resource address and severity information."""
    notifier = SlackNotifier(webhook_url=TEST_WEBHOOK_URL)
    resource = _make_resource()
    event = _make_event()
    blocks = notifier._build_drift_blocks(
        resource=resource,
        event=event,
        ai_summary="Test summary",
        ai_impact="Test impact",
        ai_recommended_action="Test recommendation",
        ai_risk_level="HIGH",
    )

    import json
    blocks_str = json.dumps(blocks)
    assert "ibm_is_security_group_rule.app_https" in blocks_str
    assert "remote" in blocks_str
    assert "CRITICAL" in blocks_str
    assert "10.0.0.0/16" in blocks_str
    assert "0.0.0.0/0" in blocks_str


def test_resolution_blocks_contain_resource_address() -> None:
    event = _make_event(DriftStatus.RESOLVED)
    blocks = SlackNotifier._build_resolution_blocks(event)

    import json
    blocks_str = json.dumps(blocks)
    assert "ibm_is_security_group_rule.app_https" in blocks_str
    assert "RESOLVED" in blocks_str or "✅" in blocks_str
