"""
AI prompt templates for the drift analysis agent.

These prompts are carefully engineered to enforce the AI guardrails:
- Never invent actors, timestamps, resource IDs
- Distinguish facts vs. inferences
- Use cautious language ("Terraform indicates...", "Potential impact...")
- Return strict JSON only
- Never execute commands or access infrastructure
"""
from __future__ import annotations

DRIFT_ANALYSIS_SYSTEM_PROMPT = """\
You are a cloud infrastructure security analyst assistant specializing in IBM Cloud and Terraform.

Your role is to analyze Terraform infrastructure drift — changes detected between the Terraform-managed
expected state and the actual current state of IBM Cloud resources.

CRITICAL RULES (MUST be followed without exception):

1. You MUST return ONLY valid JSON. No preamble, no explanation outside the JSON.
2. You MUST NOT invent or assume:
   - Who made the change (do not name users, roles, or actors unless explicitly provided)
   - When the change was made (do not invent timestamps)
   - Resource IDs or ARNs not provided to you
   - Terraform configuration details not shown to you
   - Approvals, tickets, or GitHub PRs
   - Security vulnerabilities without sufficient evidence
3. If information is unavailable, use: "Not available from the provided evidence."
4. You MUST distinguish between:
   - OBSERVED FACT: What Terraform reports as different
   - INFERRED IMPACT: What could potentially happen as a result
   - RECOMMENDATION: What should be done
5. Use careful language:
   - "Terraform indicates..." or "The current configuration shows..."
   - "Potential impact..." or "This change may..."
   - "It is recommended to..." or "Consider reviewing..."
6. You MUST NOT execute Terraform, access IBM Cloud, or call any external API.
7. You MUST NOT expose API keys, tokens, or credentials in your response.
8. Risk level must be one of: LOW, MEDIUM, HIGH, CRITICAL

RESPONSE FORMAT (strict JSON, no other content):
{
    "summary": "<one or two sentence factual summary of what changed>",
    "risk_level": "<LOW|MEDIUM|HIGH|CRITICAL>",
    "impact": "<description of potential impact, using 'Potential impact...' language>",
    "likely_reason": "<possible explanations for the change, using cautious language>",
    "recommended_action": "<specific, actionable recommendation>",
    "slack_message": "<concise plain-text message suitable for Slack notification>"
}
"""

DRIFT_ANALYSIS_USER_PROMPT_TEMPLATE = """\
Analyze the following Terraform infrastructure drift on IBM Cloud.

Environment: {environment}
Resource Address: {resource_address}
Resource Type: {resource_type}
Drift Action: {action}
Policy Severity (pre-determined): {policy_severity}

Changed Attributes:
{changes_formatted}

Terraform Expected State (before):
{expected_state}

Actual Current State (after):
{actual_state}

Policy Rules Matched:
{matched_rules}

Please analyze this drift and respond with the required JSON format.
Remember: you are analyzing what Terraform reports. Do not invent context.
"""


def format_user_prompt(
    environment: str,
    resource_address: str,
    resource_type: str,
    action: str,
    policy_severity: str,
    changes: list[dict],
    expected_state: dict,
    actual_state: dict,
    matched_rules: list[str],
) -> str:
    """
    Format the user prompt for drift analysis.

    Enforces maximum prompt length to prevent token overflow.
    """
    from app.config.settings import get_settings  # noqa: PLC0415

    settings = get_settings()

    changes_lines = []
    for c in changes:
        if c.get("is_sensitive"):
            changes_lines.append(f"  - {c['attribute']}: [sensitive] → [sensitive]")
        else:
            changes_lines.append(
                f"  - {c['attribute']}: {c.get('expected', 'null')} → {c.get('actual', 'null')}"
            )

    import json  # noqa: PLC0415

    prompt = DRIFT_ANALYSIS_USER_PROMPT_TEMPLATE.format(
        environment=environment,
        resource_address=resource_address,
        resource_type=resource_type,
        action=action,
        policy_severity=policy_severity,
        changes_formatted="\n".join(changes_lines) or "  (no specific attributes identified)",
        expected_state=json.dumps(
            {k: "[sensitive]" if _is_sensitive_key(k) else v for k, v in expected_state.items()},
            indent=2,
        )[:1000],
        actual_state=json.dumps(
            {k: "[sensitive]" if _is_sensitive_key(k) else v for k, v in actual_state.items()},
            indent=2,
        )[:1000],
        matched_rules=", ".join(matched_rules) or "none",
    )

    # Enforce maximum prompt length
    max_chars = settings.llm_max_prompt_chars
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars] + "\n\n[TRUNCATED — prompt exceeded maximum length]"

    return prompt


# Keys that should never appear in prompts
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "password",
        "secret",
        "credential",
        "iam_token",
        "ibmcloud_api_key",
        "private_key",
    }
)


def _is_sensitive_key(key: str) -> bool:
    return key.lower() in _SENSITIVE_KEYS
