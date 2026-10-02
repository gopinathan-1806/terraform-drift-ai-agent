"""
Slack notification system.

Sends drift detection notifications to a Slack channel via Incoming Webhook.

SECURITY:
- Webhook URL comes exclusively from SLACK_WEBHOOK_URL environment variable
- Webhook URL is NEVER logged
- Never exposes secrets or credentials in message content
- Sensitive Terraform values are masked before inclusion in messages

Message types:
- NEW:      🚨 New drift detected
- CHANGED:  ⚠️  Existing drift changed
- RESOLVED: ✅  Drift resolved
- TEST:     🔔  Test notification

Message format uses Slack Block Kit for rich formatting.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config.logging import get_logger
from app.config.settings import get_settings
from app.drift.models import DriftEvent, DriftedResource, DriftSeverity, DriftStatus

logger = get_logger("notifications.slack")
settings = get_settings()

# Severity → emoji mapping for visual clarity
_SEVERITY_EMOJI = {
    DriftSeverity.CRITICAL: "🔴",
    DriftSeverity.HIGH: "🟠",
    DriftSeverity.MEDIUM: "🟡",
    DriftSeverity.LOW: "🟢",
    DriftSeverity.INFO: "⚪",
}

# Status → emoji mapping
_STATUS_EMOJI = {
    DriftStatus.NEW: "🚨",
    DriftStatus.CHANGED: "⚠️",
    DriftStatus.RESOLVED: "✅",
    DriftStatus.ACTIVE: "🔔",
}


class SlackNotificationError(RuntimeError):
    """Raised when the Slack notification fails."""


class SlackNotifier:
    """
    Sends formatted drift notifications to Slack.

    Uses the Incoming Webhook API:
    https://api.slack.com/messaging/webhooks

    The webhook URL is read from SLACK_WEBHOOK_URL and is NEVER logged.
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        # Accept explicit URL for testing; otherwise use settings
        self._webhook_url = webhook_url or settings.slack_webhook_url
        self._timeout = settings.slack_timeout_seconds

    # ------------------------------------------------------------------ #
    # Public methods
    # ------------------------------------------------------------------ #

    async def send_drift_notification(
        self,
        resource: DriftedResource,
        event: DriftEvent,
        ai_summary: str | None = None,
        ai_impact: str | None = None,
        ai_recommended_action: str | None = None,
        ai_risk_level: str | None = None,
    ) -> bool:
        """
        Send a drift notification for a single resource change.

        Returns True on success, False on failure.
        Failures are logged but never raised (drift event must not be lost).
        """
        if not settings.slack_enabled:
            logger.info("Slack notifications disabled (SLACK_ENABLED=false)")
            return True

        if not self._webhook_url:
            logger.warning("SLACK_WEBHOOK_URL not configured, skipping notification")
            return False

        blocks = self._build_drift_blocks(
            resource=resource,
            event=event,
            ai_summary=ai_summary,
            ai_impact=ai_impact,
            ai_recommended_action=ai_recommended_action,
            ai_risk_level=ai_risk_level,
        )
        return await self._post(blocks)

    async def send_resolution_notification(self, event: DriftEvent) -> bool:
        """Send a ✅ DRIFT RESOLVED notification."""
        if not settings.slack_enabled or not self._webhook_url:
            return False

        blocks = self._build_resolution_blocks(event)
        return await self._post(blocks)

    async def send_test_message(self) -> bool:
        """Send a test message to verify the Slack webhook is working."""
        if not self._webhook_url:
            return False

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "🔔 *IBM Cloud Terraform DriftGuard AI — Test Notification*\n"
                        "Slack webhook is configured and working correctly.\n"
                        f"Environment: `{settings.environment}` | "
                        f"Timestamp: `{datetime.now(timezone.utc).isoformat()}`"
                    ),
                },
            }
        ]
        return await self._post(blocks)

    # ------------------------------------------------------------------ #
    # Block builders
    # ------------------------------------------------------------------ #

    def _build_drift_blocks(
        self,
        resource: DriftedResource,
        event: DriftEvent,
        ai_summary: str | None,
        ai_impact: str | None,
        ai_recommended_action: str | None,
        ai_risk_level: str | None,
    ) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks for a drift notification."""
        status_emoji = _STATUS_EMOJI.get(event.status, "🔔")
        policy_sev = resource.policy_severity or DriftSeverity.INFO
        sev_emoji = _SEVERITY_EMOJI.get(policy_sev, "⚪")

        # Header
        header_text = f"{status_emoji} *IBM Cloud Terraform Drift Detected*"
        if event.status == DriftStatus.NEW:
            header_text = f"🚨 *NEW DRIFT — IBM Cloud Infrastructure*"
        elif event.status == DriftStatus.CHANGED:
            header_text = f"⚠️ *DRIFT CHANGED — IBM Cloud Infrastructure*"

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "IBM Cloud Terraform DriftGuard AI", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header_text},
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Environment:*\n`{settings.environment}`"},
                    {"type": "mrkdwn", "text": f"*Resource:*\n`{resource.address}`"},
                    {"type": "mrkdwn", "text": f"*Resource Type:*\n`{resource.resource_type}`"},
                    {"type": "mrkdwn", "text": f"*Action:*\n`{resource.action.value.upper()}`"},
                ],
            },
        ]

        # Changed attributes section
        if resource.changes:
            changes_lines = []
            for change in resource.changes[:10]:  # Cap at 10 to avoid message size limits
                if change.is_sensitive:
                    changes_lines.append(f"• `{change.attribute}`: [sensitive] → [sensitive]")
                else:
                    expected_str = str(change.expected)[:100]
                    actual_str = str(change.actual)[:100]
                    changes_lines.append(
                        f"• `{change.attribute}`:\n  Expected: `{expected_str}`\n  Actual: `{actual_str}`"
                    )

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Changed Attributes:*\n" + "\n".join(changes_lines),
                    },
                }
            )

        # Severity section
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Policy Risk:*\n{sev_emoji} `{policy_sev.value}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*AI Assessment:*\n`{ai_risk_level or 'Not available'}`",
                    },
                ],
            }
        )

        # AI analysis section
        if ai_summary:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*AI Summary:*\n{ai_summary}"},
                }
            )

        if ai_impact:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Potential Impact:*\n{ai_impact}"},
                }
            )

        if ai_recommended_action:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Recommended Action:*\n{ai_recommended_action}",
                    },
                }
            )

        # Footer
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Detected: `{event.last_detected_at.strftime('%Y-%m-%d %H:%M:%S UTC')}`"
                            f" | Fingerprint: `{event.fingerprint[:12]}...`"
                            f" | IBM Cloud Terraform DriftGuard AI"
                        ),
                    }
                ],
            }
        )

        return blocks

    @staticmethod
    def _build_resolution_blocks(event: DriftEvent) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks for a drift resolution notification."""
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "IBM Cloud Terraform DriftGuard AI", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "✅ *DRIFT RESOLVED — Infrastructure matches Terraform state*",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Resource:*\n`{event.resource_address}`"},
                    {"type": "mrkdwn", "text": f"*Attribute:*\n`{event.changed_attribute}`"},
                    {
                        "type": "mrkdwn",
                        "text": f"*First Detected:*\n`{event.first_detected_at.strftime('%Y-%m-%d %H:%M UTC')}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Resolved At:*\n`{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "The infrastructure configuration now matches the Terraform-managed state.",
                    }
                ],
            },
        ]

    # ------------------------------------------------------------------ #
    # HTTP transport
    # ------------------------------------------------------------------ #

    async def _post(self, blocks: list[dict[str, Any]]) -> bool:
        """
        POST the block payload to the Slack webhook URL.

        Returns True on success, False on failure.
        The webhook URL is NOT logged.
        """
        payload = {"blocks": blocks}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

            if response.status_code == 200 and response.text == "ok":
                logger.info("Slack notification sent successfully")
                return True

            logger.error(
                "Slack notification failed",
                status_code=response.status_code,
                # Do NOT log response body or webhook URL
            )
            return False

        except httpx.TimeoutException:
            logger.error("Slack notification timed out", timeout_seconds=self._timeout)
            return False
        except httpx.RequestError as exc:
            logger.error("Slack notification request failed", error_type=type(exc).__name__)
            return False
