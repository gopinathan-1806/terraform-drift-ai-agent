"""
Phase 6 — Tests for the AI analysis agent.

All tests mock the LLM provider — no real API calls are made.
Tests verify:
- Agent returns correct structure
- Agent uses fallback when LLM provider is disabled
- Agent uses fallback when LLM fails (Scenario 9)
- Agent never exposes API keys
- Agent handles multiple resources
- Prompt does not include sensitive values
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.agent import AIAnalysisResult, DriftAnalysisAgent
from app.agent.provider import (
    FALLBACK_RESPONSE,
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    NoOpLLMProvider,
)
from app.drift.models import AttributeChange, DriftAction, DriftedResource, DriftSeverity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sg_resource() -> DriftedResource:
    return DriftedResource(
        address="ibm_is_security_group_rule.app_https",
        resource_type="ibm_is_security_group_rule",
        resource_name="app_https",
        action=DriftAction.UPDATE,
        policy_severity=DriftSeverity.CRITICAL,
        policy_matched_rules=["CRITICAL_SECURITY_GROUP_PUBLIC_SENSITIVE_PORTS"],
        changes=[
            AttributeChange(attribute="remote", expected="10.0.0.0/16", actual="0.0.0.0/0"),
        ],
    )


VALID_AI_RESPONSE = {
    "summary": "Terraform indicates the security group rule remote CIDR changed from 10.0.0.0/16 to 0.0.0.0/0.",
    "risk_level": "CRITICAL",
    "impact": "Potential impact: HTTPS traffic is now permitted from any IPv4 address on the public internet.",
    "likely_reason": "Not available from the provided evidence.",
    "recommended_action": "Review the manual change and revert through Terraform if unauthorized.",
    "slack_message": "🚨 CRITICAL drift: ibm_is_security_group_rule.app_https — remote changed to 0.0.0.0/0",
}


# ---------------------------------------------------------------------------
# Tests: NoOp provider (LLM disabled)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_with_noop_provider_returns_fallback() -> None:
    """When LLM_PROVIDER=none, agent should return fallback response."""
    agent = DriftAnalysisAgent(provider=NoOpLLMProvider())
    resource = _make_sg_resource()
    result = await agent.analyze(resource)

    assert result.ai_available is False
    assert "Drift detected" in result.summary or "unavailable" in result.summary.lower()


@pytest.mark.asyncio
async def test_agent_noop_does_not_call_llm() -> None:
    """NoOp provider should not make any HTTP calls."""
    provider = NoOpLLMProvider()
    with patch("httpx.AsyncClient") as mock_client:
        agent = DriftAnalysisAgent(provider=provider)
        await agent.analyze(_make_sg_resource())
        mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Successful AI response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_returns_ai_result_on_success() -> None:
    """Agent should return AI analysis when provider succeeds."""
    mock_provider = AsyncMock()
    mock_provider.complete.return_value = VALID_AI_RESPONSE

    agent = DriftAnalysisAgent(provider=mock_provider)
    resource = _make_sg_resource()
    result = await agent.analyze(resource)

    assert result.ai_available is True
    assert result.risk_level == "CRITICAL"
    assert "0.0.0.0/0" in result.summary or "CIDR" in result.summary


@pytest.mark.asyncio
async def test_agent_populates_resource_fields() -> None:
    """Agent should populate ai_* fields on the resource after analysis."""
    mock_provider = AsyncMock()
    mock_provider.complete.return_value = VALID_AI_RESPONSE

    agent = DriftAnalysisAgent(provider=mock_provider)
    resource = _make_sg_resource()
    await agent.analyze(resource)

    assert resource.ai_severity == DriftSeverity.CRITICAL
    assert resource.ai_summary is not None
    assert resource.ai_impact is not None
    assert resource.ai_recommended_action is not None


# ---------------------------------------------------------------------------
# Scenario 9: AI failure — fallback must be used
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_fallback_on_llm_error() -> None:
    """Scenario 9: AI failure should produce fallback, not raise an exception."""
    mock_provider = AsyncMock()
    mock_provider.complete.side_effect = LLMError("Connection refused")

    agent = DriftAnalysisAgent(provider=mock_provider)
    resource = _make_sg_resource()

    # Should NOT raise
    result = await agent.analyze(resource)
    assert result.ai_available is False
    assert result.summary == FALLBACK_RESPONSE["summary"]


@pytest.mark.asyncio
async def test_agent_fallback_on_timeout() -> None:
    """LLM timeout should produce fallback, not raise."""
    mock_provider = AsyncMock()
    mock_provider.complete.side_effect = LLMTimeoutError("Timeout")

    agent = DriftAnalysisAgent(provider=mock_provider)
    result = await agent.analyze(_make_sg_resource())

    assert result.ai_available is False


@pytest.mark.asyncio
async def test_agent_fallback_on_invalid_json() -> None:
    """Invalid JSON from LLM should produce fallback, not raise."""
    mock_provider = AsyncMock()
    mock_provider.complete.side_effect = LLMResponseError("Invalid JSON")

    agent = DriftAnalysisAgent(provider=mock_provider)
    result = await agent.analyze(_make_sg_resource())

    assert result.ai_available is False


@pytest.mark.asyncio
async def test_agent_analyze_all_continues_on_failure() -> None:
    """AI failure for one resource should not prevent analysis of others."""
    call_count = 0

    async def mock_complete(system_prompt, user_prompt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMError("First call fails")
        return VALID_AI_RESPONSE

    mock_provider = MagicMock()
    mock_provider.complete = mock_complete

    agent = DriftAnalysisAgent(provider=mock_provider)
    resources = [_make_sg_resource(), _make_sg_resource()]
    results = await agent.analyze_all(resources)

    assert len(results) == 2
    # First should be fallback, second should succeed
    assert results[0].ai_available is False
    assert results[1].ai_available is True


# ---------------------------------------------------------------------------
# Security tests: Sensitive values must not appear in prompts
# ---------------------------------------------------------------------------


def test_prompt_masks_sensitive_values() -> None:
    """Sensitive attribute values must not appear in the formatted prompt."""
    from app.agent.prompts import format_user_prompt

    prompt = format_user_prompt(
        environment="test",
        resource_address="ibm_resource_instance.kms",
        resource_type="ibm_resource_instance",
        action="update",
        policy_severity="HIGH",
        changes=[
            {
                "attribute": "api_key",
                "expected": "OLD_SECRET_API_KEY_VALUE",
                "actual": "NEW_SECRET_API_KEY_VALUE",
                "is_sensitive": True,
            }
        ],
        expected_state={"api_key": "[sensitive]"},
        actual_state={"api_key": "[sensitive]"},
        matched_rules=[],
    )

    assert "OLD_SECRET_API_KEY_VALUE" not in prompt
    assert "NEW_SECRET_API_KEY_VALUE" not in prompt


def test_prompt_length_is_capped() -> None:
    """Prompt should be truncated when it exceeds llm_max_prompt_chars."""
    from app.agent.prompts import format_user_prompt

    # Generate a very long actual state
    long_value = "x" * 20000
    prompt = format_user_prompt(
        environment="test",
        resource_address="resource.test",
        resource_type="ibm_is_vpc",
        action="update",
        policy_severity="LOW",
        changes=[{"attribute": "description", "expected": "short", "actual": long_value, "is_sensitive": False}],
        expected_state={"description": "short"},
        actual_state={"description": long_value},
        matched_rules=[],
    )

    from app.config.settings import get_settings

    assert len(prompt) <= get_settings().llm_max_prompt_chars + 100  # allow for truncation message


# ---------------------------------------------------------------------------
# AIAnalysisResult model tests
# ---------------------------------------------------------------------------


def test_ai_result_severity_parsing() -> None:
    result = AIAnalysisResult({"risk_level": "CRITICAL"})
    assert result.severity == DriftSeverity.CRITICAL


def test_ai_result_unknown_risk_level_defaults_to_info() -> None:
    result = AIAnalysisResult({"risk_level": "INVALID_LEVEL"})
    assert result.severity == DriftSeverity.INFO


def test_ai_result_fallback_fields() -> None:
    result = AIAnalysisResult({})
    assert result.summary == FALLBACK_RESPONSE["summary"]
    assert result.impact == FALLBACK_RESPONSE["impact"]
