"""
Pydantic models for the normalized drift layer.

These are the internal representations produced by the drift parser
after processing raw Terraform plan JSON.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DriftAction(str, Enum):
    """The type of change Terraform has identified for a resource."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE = "replace"
    NO_OP = "no-op"


class DriftSeverity(str, Enum):
    """Severity levels used by both the policy engine and the AI agent."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class DriftStatus(str, Enum):
    """Lifecycle status of a drift event."""

    NEW = "NEW"
    ACTIVE = "ACTIVE"
    CHANGED = "CHANGED"
    RESOLVED = "RESOLVED"


class AttributeChange(BaseModel):
    """A single attribute that has drifted from its Terraform-expected value."""

    attribute: str
    expected: Any = Field(description="Value in Terraform state (before)")
    actual: Any = Field(description="Value currently on the cloud resource (after)")
    is_sensitive: bool = Field(default=False)

    def display_expected(self) -> str:
        return "[sensitive]" if self.is_sensitive else str(self.expected)

    def display_actual(self) -> str:
        return "[sensitive]" if self.is_sensitive else str(self.actual)


class DriftedResource(BaseModel):
    """A resource that has drifted from its Terraform-managed state."""

    address: str = Field(description="Full Terraform resource address, e.g. ibm_is_security_group_rule.app_https")
    resource_type: str = Field(description="Terraform resource type, e.g. ibm_is_security_group_rule")
    resource_name: str = Field(description="Terraform resource name component")
    module_address: str | None = None
    action: DriftAction
    changes: list[AttributeChange] = Field(default_factory=list)

    # Populated by the policy engine
    policy_severity: DriftSeverity | None = None
    policy_matched_rules: list[str] = Field(default_factory=list)

    # Populated by the AI agent
    ai_severity: DriftSeverity | None = None
    ai_summary: str | None = None
    ai_impact: str | None = None
    ai_likely_reason: str | None = None
    ai_recommended_action: str | None = None


class DriftReport(BaseModel):
    """The complete result of a single drift detection run."""

    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str
    terraform_workspace: str
    drift_detected: bool
    resources: list[DriftedResource] = Field(default_factory=list)
    terraform_version: str | None = None
    duration_seconds: float | None = None

    # Execution metadata
    terraform_init_ok: bool = False
    terraform_validate_ok: bool = False
    terraform_plan_ok: bool = False
    error_message: str | None = None

    @property
    def resource_count(self) -> int:
        return len(self.resources)

    @property
    def highest_severity(self) -> DriftSeverity | None:
        """Return the highest policy_severity across all drifted resources."""
        order = [DriftSeverity.CRITICAL, DriftSeverity.HIGH, DriftSeverity.MEDIUM, DriftSeverity.LOW, DriftSeverity.INFO]
        for sev in order:
            if any(r.policy_severity == sev for r in self.resources):
                return sev
        return None


class DriftEvent(BaseModel):
    """
    A persistent drift event that tracks lifecycle across multiple runs.

    Stored in local state and keyed by fingerprint.
    """

    fingerprint: str
    status: DriftStatus = DriftStatus.NEW
    first_detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_notified_at: datetime | None = None
    resource_address: str
    changed_attribute: str
    expected_value: str
    actual_value: str
    policy_severity: DriftSeverity | None = None
