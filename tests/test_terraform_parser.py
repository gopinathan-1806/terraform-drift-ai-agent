"""
Phase 3 — Tests for the Terraform plan JSON parser.

All scenarios use the fixtures from conftest.py.
No real Terraform binary is required.
"""
from __future__ import annotations

import pytest

from app.drift.models import DriftAction, DriftSeverity
from app.terraform.parser import TerraformParseError, TerraformParser


@pytest.fixture
def parser() -> TerraformParser:
    return TerraformParser()


# ---------------------------------------------------------------------------
# Scenario 1: No drift
# ---------------------------------------------------------------------------


def test_no_drift_returns_empty_list(parser: TerraformParser, tf_plan_no_drift: dict) -> None:
    """No-op resources should produce an empty result."""
    result = parser.parse(tf_plan_no_drift)
    assert result == []


# ---------------------------------------------------------------------------
# Scenario 2: Single attribute drift
# ---------------------------------------------------------------------------


def test_single_drift_returns_one_resource(parser: TerraformParser, tf_plan_single_drift: dict) -> None:
    result = parser.parse(tf_plan_single_drift)
    assert len(result) == 1
    resource = result[0]
    assert resource.address == "ibm_is_security_group_rule.app_https"
    assert resource.resource_type == "ibm_is_security_group_rule"
    assert resource.action == DriftAction.UPDATE


def test_single_drift_change_content(parser: TerraformParser, tf_plan_single_drift: dict) -> None:
    result = parser.parse(tf_plan_single_drift)
    resource = result[0]
    assert len(resource.changes) == 1
    change = resource.changes[0]
    assert change.attribute == "remote"
    assert change.expected == "10.0.0.0/16"
    assert change.actual == "0.0.0.0/0"
    assert change.is_sensitive is False


def test_single_drift_display_values(parser: TerraformParser, tf_plan_single_drift: dict) -> None:
    result = parser.parse(tf_plan_single_drift)
    change = result[0].changes[0]
    assert change.display_expected() == "10.0.0.0/16"
    assert change.display_actual() == "0.0.0.0/0"


# ---------------------------------------------------------------------------
# Scenario 3: Multiple attribute drift
# ---------------------------------------------------------------------------


def test_multi_drift_detects_both_attributes(parser: TerraformParser, tf_plan_multi_drift: dict) -> None:
    result = parser.parse(tf_plan_multi_drift)
    assert len(result) == 1
    changes = result[0].changes
    attribute_names = {c.attribute for c in changes}
    assert "remote" in attribute_names
    assert "port_min" in attribute_names


def test_multi_drift_correct_values(parser: TerraformParser, tf_plan_multi_drift: dict) -> None:
    result = parser.parse(tf_plan_multi_drift)
    changes_by_attr = {c.attribute: c for c in result[0].changes}
    assert changes_by_attr["remote"].expected == "10.0.0.0/16"
    assert changes_by_attr["remote"].actual == "0.0.0.0/0"
    assert changes_by_attr["port_min"].expected == 443
    assert changes_by_attr["port_min"].actual == 80


# ---------------------------------------------------------------------------
# Scenario 4: Resource replacement
# ---------------------------------------------------------------------------


def test_replace_action_mapped_correctly(parser: TerraformParser, tf_plan_replace: dict) -> None:
    result = parser.parse(tf_plan_replace)
    assert len(result) == 1
    assert result[0].action == DriftAction.REPLACE


# ---------------------------------------------------------------------------
# Scenario 5: Resource deletion
# ---------------------------------------------------------------------------


def test_delete_action_mapped_correctly(parser: TerraformParser, tf_plan_delete: dict) -> None:
    result = parser.parse(tf_plan_delete)
    assert len(result) == 1
    assert result[0].action == DriftAction.DELETE


def test_delete_reports_before_attributes(parser: TerraformParser, tf_plan_delete: dict) -> None:
    result = parser.parse(tf_plan_delete)
    changes = result[0].changes
    attribute_names = {c.attribute for c in changes}
    assert "name" in attribute_names
    assert "vpc" in attribute_names
    # All actuals should be None for deleted resources
    for change in changes:
        assert change.actual is None


# ---------------------------------------------------------------------------
# Scenario 6: Security group opened to 0.0.0.0/0
# ---------------------------------------------------------------------------


def test_public_access_change_detected(parser: TerraformParser, tf_plan_single_drift: dict) -> None:
    """The public internet CIDR change should be detected as an attribute change."""
    result = parser.parse(tf_plan_single_drift)
    remote_change = next(c for c in result[0].changes if c.attribute == "remote")
    assert remote_change.actual == "0.0.0.0/0"


# ---------------------------------------------------------------------------
# Scenario 8: Sensitive Terraform values
# ---------------------------------------------------------------------------


def test_sensitive_values_masked(parser: TerraformParser, tf_plan_sensitive: dict) -> None:
    result = parser.parse(tf_plan_sensitive)
    assert len(result) == 1
    # The display should mask sensitive changes
    for change in result[0].changes:
        if change.is_sensitive:
            assert change.display_expected() == "[sensitive]"
            assert change.display_actual() == "[sensitive]"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_non_dict_input_raises(parser: TerraformParser) -> None:
    with pytest.raises(TerraformParseError):
        parser.parse("not a dict")  # type: ignore[arg-type]


def test_empty_resource_changes_returns_empty(parser: TerraformParser) -> None:
    result = parser.parse({"format_version": "1.2", "terraform_version": "1.9.0", "resource_changes": []})
    assert result == []


def test_unknown_computed_values_skipped(parser: TerraformParser) -> None:
    """Unknown/computed after values should not generate a false drift change."""
    plan = {
        "format_version": "1.2",
        "terraform_version": "1.9.0",
        "resource_changes": [
            {
                "address": "ibm_is_instance.app",
                "type": "ibm_is_instance",
                "name": "app",
                "provider_name": "registry.terraform.io/ibm-cloud/ibm",
                "change": {
                    "actions": ["update"],
                    "before": {"name": "my-vm", "primary_network_interface": []},
                    "after": {
                        "name": "my-vm",
                        "primary_network_interface": {"unknown": True},  # computed
                    },
                    "before_sensitive": {},
                    "after_sensitive": {},
                },
            }
        ],
    }
    result = parser.parse(plan)
    # The computed field should be skipped; no change should be detected
    if result:
        attribute_names = {c.attribute for c in result[0].changes}
        assert "primary_network_interface" not in attribute_names


def test_identical_before_after_no_changes(parser: TerraformParser) -> None:
    """If before == after for all attributes, changes list should be empty."""
    plan = {
        "format_version": "1.2",
        "terraform_version": "1.9.0",
        "resource_changes": [
            {
                "address": "ibm_is_vpc.main",
                "type": "ibm_is_vpc",
                "name": "main",
                "provider_name": "registry.terraform.io/ibm-cloud/ibm",
                "change": {
                    "actions": ["update"],
                    "before": {"name": "prod-vpc", "classic_access": False},
                    "after": {"name": "prod-vpc", "classic_access": False},
                    "before_sensitive": {},
                    "after_sensitive": {},
                },
            }
        ],
    }
    result = parser.parse(plan)
    # Resource is present (action=update) but changes list is empty
    if result:
        assert result[0].changes == []


def test_create_action_reports_after_attributes(parser: TerraformParser) -> None:
    """For create actions, all after attributes should be reported with expected=None."""
    plan = {
        "format_version": "1.2",
        "terraform_version": "1.9.0",
        "resource_changes": [
            {
                "address": "ibm_is_security_group.new_sg",
                "type": "ibm_is_security_group",
                "name": "new_sg",
                "provider_name": "registry.terraform.io/ibm-cloud/ibm",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"name": "new-sg", "vpc": "vpc-abc123"},
                    "before_sensitive": {},
                    "after_sensitive": {},
                },
            }
        ],
    }
    result = parser.parse(plan)
    assert len(result) == 1
    assert result[0].action == DriftAction.CREATE
    for change in result[0].changes:
        assert change.expected is None
