"""
Pydantic models for Terraform plan JSON output.

These models represent the structure returned by:
    terraform show -json <plan-file>

Reference:
    https://developer.hashicorp.com/terraform/internals/json-format
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TerraformChangeDetail(BaseModel):
    """Represents the change detail for a single resource."""

    actions: list[str] = Field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    before_sensitive: dict[str, Any] | bool | None = None
    after_sensitive: dict[str, Any] | bool | None = None
    after_unknown: dict[str, Any] | bool | None = None


class TerraformResourceChange(BaseModel):
    """Represents a single resource change entry from terraform plan -json."""

    address: str
    module_address: str | None = None
    mode: str = Field(default="managed")
    type: str = Field(default="")
    name: str = Field(default="")
    provider_name: str = Field(default="")
    change: TerraformChangeDetail = Field(default_factory=TerraformChangeDetail)

    @property
    def is_no_op(self) -> bool:
        """Return True if this resource has no actual changes."""
        return self.change.actions == ["no-op"] or self.change.actions == []

    @property
    def action_summary(self) -> str:
        """Return a human-readable single action string."""
        actions = self.change.actions
        if not actions or actions == ["no-op"]:
            return "no-op"
        if actions == ["create"]:
            return "create"
        if actions == ["delete"]:
            return "delete"
        if actions == ["update"]:
            return "update"
        if set(actions) == {"create", "delete"} or actions == ["delete", "create"]:
            return "replace"
        # Fallback — join whatever Terraform returned
        return "+".join(actions)


class TerraformPlanOutput(BaseModel):
    """Top-level structure of terraform show -json output for a plan.

    For a normal plan, changed resources appear in `resource_changes`.
    For a `plan -refresh-only`, Terraform puts the detected drift in
    `resource_drift` instead — `resource_changes` is always empty in
    that case.  Both fields must be parsed.
    """

    format_version: str = Field(default="")
    terraform_version: str = Field(default="")
    resource_changes: list[TerraformResourceChange] = Field(default_factory=list)
    resource_drift: list[TerraformResourceChange] = Field(default_factory=list)
    prior_state: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None
