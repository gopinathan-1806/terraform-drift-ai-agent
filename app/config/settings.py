"""
Application settings using Pydantic Settings.

All secrets are sourced from environment variables.
Non-secret configuration can be extended via config.yaml.
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for IBM Cloud Terraform DriftGuard AI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    app_name: str = Field(default="IBM Cloud Terraform DriftGuard AI")
    app_version: str = Field(default="0.1.0")
    environment: str = Field(default="development", description="Target environment label (e.g. stage, production)")
    log_level: str = Field(default="INFO")
    log_format: Literal["json", "text"] = Field(default="json")

    # ------------------------------------------------------------------ #
    # Terraform
    # ------------------------------------------------------------------ #
    terraform_working_dir: str = Field(
        default="./terraform",
        description="Path to the Terraform configuration directory",
    )
    terraform_bin: str = Field(
        default="terraform",
        description="Path or name of the Terraform binary",
    )
    terraform_timeout_seconds: int = Field(
        default=300,
        description="Maximum seconds allowed for any single Terraform command",
    )
    terraform_max_output_bytes: int = Field(
        default=10_485_760,  # 10 MB
        description="Maximum allowed byte size of Terraform command output",
    )
    terraform_workspace: str = Field(
        default="default",
        description="Terraform workspace name",
    )

    # ------------------------------------------------------------------ #
    # IBM Cloud
    # ------------------------------------------------------------------ #
    ibmcloud_api_key: str = Field(
        default="",
        description="IBM Cloud API key — passed to Terraform as TF_VAR_ibmcloud_api_key (never logged)",
    )
    ibmcloud_region: str = Field(
        default="us-south",
        description="IBM Cloud region",
    )

    # ── Stage endpoint overrides ──────────────────────────────────────
    # These redirect the IBM Terraform provider to Stage/Dev endpoints.
    # Leave empty ("") to use the provider's default production endpoints.
    ibmcloud_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_API_ENDPOINT (e.g. https://test.cloud.ibm.com for Stage)",
    )
    ibmcloud_iam_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_IAM_API_ENDPOINT (e.g. https://iam.test.cloud.ibm.com for Stage)",
    )
    ibmcloud_is_ng_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_IS_NG_API_ENDPOINT (VPC/IS endpoint, e.g. https://us-south-stage01.iaasdev.cloud.ibm.com/v1)",
    )
    ibmcloud_gt_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_GT_API_ENDPOINT (Global Tagging, e.g. https://tags.global-search-tagging.test.cloud.ibm.com)",
    )
    ibmcloud_gs_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_GS_API_ENDPOINT (Global Search, e.g. https://api.global-search-tagging.test.cloud.ibm.com)",
    )
    ibmcloud_resource_controller_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT (e.g. https://resource-controller.test.cloud.ibm.com)",
    )
    ibmcloud_resource_management_api_endpoint: str = Field(
        default="",
        description="Override IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT (e.g. https://resource-controller.test.cloud.ibm.com)",
    )

    # ------------------------------------------------------------------ #
    # Drift detection
    # ------------------------------------------------------------------ #
    drift_check_interval_seconds: int = Field(
        default=300,
        description="How often the scheduler runs a drift check (seconds)",
    )
    drift_notify_on_resolve: bool = Field(
        default=True,
        description="Whether to send a Slack notification when drift is resolved",
    )
    drift_state_dir: str = Field(
        default="./.driftguard/state",
        description="Directory for persisting drift fingerprints locally",
    )

    # ------------------------------------------------------------------ #
    # Policy engine
    # ------------------------------------------------------------------ #
    policy_rules_path: str = Field(
        default="./app/policy/rules.yaml",
        description="Path to the YAML file containing policy rules",
    )

    # ------------------------------------------------------------------ #
    # AI / LLM provider
    # ------------------------------------------------------------------ #
    llm_provider: Literal["openai", "watsonx", "none"] = Field(
        default="none",
        description="LLM provider to use for AI analysis (openai | watsonx | none)",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for the configured LLM provider (never logged)",
    )
    llm_api_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the LLM API (supports OpenAI-compatible endpoints)",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model name/ID to use for AI analysis",
    )
    llm_temperature: float = Field(default=0.1)
    llm_max_tokens: int = Field(default=1024)
    llm_timeout_seconds: int = Field(
        default=60,
        description="Maximum seconds to wait for an LLM API response",
    )
    llm_max_prompt_chars: int = Field(
        default=8000,
        description="Maximum characters allowed in a single LLM prompt",
    )

    # ------------------------------------------------------------------ #
    # Slack
    # ------------------------------------------------------------------ #
    slack_webhook_url: str = Field(
        default="",
        description="Slack Incoming Webhook URL (never logged)",
    )
    slack_timeout_seconds: int = Field(default=10)
    slack_enabled: bool = Field(
        default=True,
        description="Master switch to enable/disable Slack notifications",
    )

    # ------------------------------------------------------------------ #
    # API server
    # ------------------------------------------------------------------ #
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8080)
    api_reload: bool = Field(default=False)

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @field_validator("drift_check_interval_seconds")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 10:
            raise ValueError("drift_check_interval_seconds must be >= 10")
        return v


def get_settings() -> Settings:
    """Return a cached Settings instance.

    Uses a module-level singleton so pydantic-settings reads .env only once.
    """
    return _settings


# Module-level singleton — instantiated once at import time.
_settings = Settings()
