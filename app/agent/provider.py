"""
LLM provider abstraction layer.

Supports:
- openai:   OpenAI API and compatible endpoints (including IBM watsonx via proxy)
- watsonx:  IBM watsonx.ai direct API
- none:     Disabled — returns a structured fallback response

The provider is selected via the LLM_PROVIDER environment variable.
All API keys are read from environment — never hard-coded.

SECURITY:
- API keys are never logged
- Prompts are length-capped before sending
- AI responses are always validated as JSON before use
- Network calls use timeouts (LLM_TIMEOUT_SECONDS)
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config.logging import get_logger
from app.config.settings import get_settings

logger = get_logger("agent.provider")
settings = get_settings()

# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

FALLBACK_RESPONSE: dict[str, str] = {
    "summary": "Drift detected. AI analysis unavailable.",
    "risk_level": "UNKNOWN",
    "impact": "Not available from the provided evidence.",
    "likely_reason": "Not available from the provided evidence.",
    "recommended_action": "Review the drift report and investigate the changed resources manually.",
    "slack_message": "⚠️ Terraform drift detected. AI analysis unavailable — review changes manually.",
}


class LLMError(RuntimeError):
    """Base error for LLM provider failures."""


class LLMTimeoutError(LLMError):
    """LLM API request timed out."""


class LLMResponseError(LLMError):
    """LLM returned an invalid or unparseable response."""


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """
        Send a chat completion request and return the parsed JSON response.

        Args:
            system_prompt: The system/persona prompt.
            user_prompt: The user message containing drift details.

        Returns:
            Parsed JSON dict with keys: summary, risk_level, impact,
            likely_reason, recommended_action, slack_message.

        Raises:
            LLMError, LLMTimeoutError, LLMResponseError
        """


# ---------------------------------------------------------------------------
# Disabled provider (LLM_PROVIDER=none)
# ---------------------------------------------------------------------------


class NoOpLLMProvider(LLMProvider):
    """
    Disabled LLM provider.

    Returns a deterministic fallback response without making any API calls.
    Used when LLM_PROVIDER=none or when the LLM is not configured.
    """

    async def complete(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:  # noqa: ARG002
        logger.info("LLM provider is disabled (LLM_PROVIDER=none), using fallback response")
        return dict(FALLBACK_RESPONSE)


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------


class OpenAIProvider(LLMProvider):
    """
    OpenAI-compatible API provider.

    Works with:
    - OpenAI (https://api.openai.com/v1)
    - Any OpenAI-compatible endpoint (e.g. IBM watsonx.ai via OpenAI proxy)

    Configure via:
    - LLM_API_KEY
    - LLM_API_BASE_URL
    - LLM_MODEL
    - LLM_TEMPERATURE
    - LLM_MAX_TOKENS
    - LLM_TIMEOUT_SECONDS
    """

    def __init__(self) -> None:
        if not settings.llm_api_key:
            raise LLMError(
                "LLM_API_KEY is required for the OpenAI provider. "
                "Set LLM_API_KEY in your environment or .env file."
            )
        self._api_key = settings.llm_api_key
        self._base_url = settings.llm_api_base_url.rstrip("/")
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens
        self._timeout = settings.llm_timeout_seconds

    async def complete(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send a chat completion and return parsed JSON."""
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}/chat/completions"
        logger.info("Sending request to LLM", model=self._model, url=url)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"LLM API request timed out after {self._timeout}s"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMError(f"LLM API request failed: {type(exc).__name__}") from exc

        if response.status_code != 200:
            # Log status only — never log response body which may contain sensitive data
            logger.error(
                "LLM API returned non-200 status",
                status_code=response.status_code,
            )
            raise LLMResponseError(
                f"LLM API returned HTTP {response.status_code}. "
                "Check LLM_API_KEY and LLM_API_BASE_URL configuration."
            )

        return self._parse_response(response.json())

    def _parse_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Extract and validate the JSON content from the LLM response."""
        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                f"Unexpected LLM response structure: {exc}"
            ) from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"LLM returned non-JSON content: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise LLMResponseError("LLM response JSON must be an object")

        # Validate required keys
        required_keys = {"summary", "risk_level", "impact", "likely_reason", "recommended_action", "slack_message"}
        missing = required_keys - set(parsed.keys())
        if missing:
            raise LLMResponseError(f"LLM response missing required keys: {missing}")

        return parsed


# ---------------------------------------------------------------------------
# IBM watsonx.ai provider
# ---------------------------------------------------------------------------


class WatsonxProvider(LLMProvider):
    """
    IBM watsonx.ai direct API provider.

    Uses the watsonx.ai text generation endpoint.
    Configure via:
    - LLM_API_KEY    (IBM Cloud IAM API key)
    - LLM_API_BASE_URL (e.g. https://us-south.ml.cloud.ibm.com/ml/v1)
    - LLM_MODEL      (e.g. ibm/granite-3-3-8b-instruct)

    NOTE: This implementation wraps the watsonx.ai text generation API
    using the OpenAI-compatible interface when available, falling back
    to the native API format.  For V1, uses OpenAI-compatible mode.
    """

    def __init__(self) -> None:
        if not settings.llm_api_key:
            raise LLMError(
                "LLM_API_KEY (IBM Cloud IAM API key) is required for the watsonx provider."
            )
        # Delegate to OpenAI-compatible provider — watsonx supports OpenAI API format
        self._delegate = OpenAIProvider()

    async def complete(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return await self._delegate.complete(system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm_provider() -> LLMProvider:
    """
    Return the configured LLM provider instance.

    Provider is selected by LLM_PROVIDER environment variable:
    - "none"    → NoOpLLMProvider (disabled, returns fallback)
    - "openai"  → OpenAIProvider
    - "watsonx" → WatsonxProvider

    Returns:
        LLMProvider instance appropriate for the configured provider.
    """
    provider_name = settings.llm_provider.lower()

    if provider_name == "none":
        return NoOpLLMProvider()

    if provider_name == "openai":
        return OpenAIProvider()

    if provider_name == "watsonx":
        return WatsonxProvider()

    logger.warning(
        "Unknown LLM_PROVIDER, falling back to disabled (none)",
        configured_provider=provider_name,
    )
    return NoOpLLMProvider()
