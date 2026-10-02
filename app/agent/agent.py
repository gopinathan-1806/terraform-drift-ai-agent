"""
AI drift analysis agent.

The AI agent receives structured drift data from the policy engine and
produces a human-readable risk assessment.

IMPORTANT DESIGN:
- The AI agent NEVER executes Terraform
- The AI agent NEVER modifies IBM Cloud infrastructure
- The AI agent NEVER has access to IBM Cloud credentials
- The AI agent NEVER has direct filesystem access
- The AI agent ONLY receives structured data prepared by the pipeline

Pipeline position:
    Terraform → Parser → Policy Engine → [AI Agent] → Slack Notification

If AI fails for any reason, a deterministic fallback notification is sent.
The drift event is NEVER lost due to AI failure.
"""
from __future__ import annotations

from typing import Any

from app.agent.prompts import DRIFT_ANALYSIS_SYSTEM_PROMPT, format_user_prompt
from app.agent.provider import FALLBACK_RESPONSE, LLMError, LLMProvider, NoOpLLMProvider, get_llm_provider
from app.config.logging import get_logger
from app.config.settings import get_settings
from app.drift.models import DriftedResource, DriftSeverity

logger = get_logger("agent.agent")
settings = get_settings()


class AIAnalysisResult:
    """Structured result from the AI analysis agent."""

    def __init__(self, data: dict[str, Any], ai_available: bool = True) -> None:
        self.summary: str = data.get("summary", FALLBACK_RESPONSE["summary"])
        self.risk_level: str = data.get("risk_level", "UNKNOWN")
        self.impact: str = data.get("impact", FALLBACK_RESPONSE["impact"])
        self.likely_reason: str = data.get("likely_reason", FALLBACK_RESPONSE["likely_reason"])
        self.recommended_action: str = data.get(
            "recommended_action", FALLBACK_RESPONSE["recommended_action"]
        )
        self.slack_message: str = data.get("slack_message", FALLBACK_RESPONSE["slack_message"])
        self.ai_available: bool = ai_available

    @property
    def severity(self) -> DriftSeverity:
        """Parse risk_level string into DriftSeverity enum, defaulting to INFO on unknown."""
        try:
            return DriftSeverity(self.risk_level.upper())
        except ValueError:
            return DriftSeverity.INFO


class DriftAnalysisAgent:
    """
    Orchestrates AI analysis of infrastructure drift.

    Receives structured drift data, formats it into prompts, and
    returns a validated AI analysis result.

    The agent operates in read-only mode:
    - No Terraform execution
    - No IBM Cloud API calls
    - No filesystem writes
    - No credential access
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider or get_llm_provider()

    async def analyze(self, resource: DriftedResource) -> AIAnalysisResult:
        """
        Analyze a single drifted resource using the AI provider.

        Returns an AIAnalysisResult. If AI fails for any reason, returns
        a deterministic fallback result — the drift event is never lost.

        Args:
            resource: A DriftedResource that has been through the policy engine.

        Returns:
            AIAnalysisResult populated with AI assessment or fallback values.
        """
        if isinstance(self._provider, NoOpLLMProvider):
            logger.info(
                "AI analysis skipped (LLM disabled)",
                resource=resource.address,
            )
            result = await self._provider.complete("", "")
            return AIAnalysisResult(result, ai_available=False)

        # Build structured prompt data
        user_prompt = format_user_prompt(
            environment=settings.environment,
            resource_address=resource.address,
            resource_type=resource.resource_type,
            action=resource.action.value,
            policy_severity=resource.policy_severity.value if resource.policy_severity else "UNKNOWN",
            changes=[
                {
                    "attribute": c.attribute,
                    "expected": c.display_expected(),
                    "actual": c.display_actual(),
                    "is_sensitive": c.is_sensitive,
                }
                for c in resource.changes
            ],
            expected_state={
                c.attribute: c.display_expected()
                for c in resource.changes
            },
            actual_state={
                c.attribute: c.display_actual()
                for c in resource.changes
            },
            matched_rules=resource.policy_matched_rules,
        )

        try:
            raw_result = await self._provider.complete(
                system_prompt=DRIFT_ANALYSIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
            # Populate resource with AI results
            result = AIAnalysisResult(raw_result, ai_available=True)
            resource.ai_severity = result.severity
            resource.ai_summary = result.summary
            resource.ai_impact = result.impact
            resource.ai_likely_reason = result.likely_reason
            resource.ai_recommended_action = result.recommended_action

            logger.info(
                "AI analysis completed",
                resource=resource.address,
                ai_risk_level=result.risk_level,
            )
            return result

        except LLMError as exc:
            # AI failure MUST NOT lose the drift event — use fallback
            logger.warning(
                "AI analysis failed, using fallback",
                resource=resource.address,
                error_type=type(exc).__name__,
                # Note: error message is logged but must never contain API key or credentials
            )
            fallback = AIAnalysisResult(dict(FALLBACK_RESPONSE), ai_available=False)
            resource.ai_summary = fallback.summary
            resource.ai_recommended_action = fallback.recommended_action
            return fallback

    async def analyze_all(self, resources: list[DriftedResource]) -> list[AIAnalysisResult]:
        """
        Analyze all drifted resources.

        Each resource is analyzed independently. AI failure for one
        resource does not prevent analysis of others.
        """
        results = []
        for resource in resources:
            result = await self.analyze(resource)
            results.append(result)
        return results
