"""
Phase 5 — Tests for the deterministic policy engine.

Tests cover:
- Security group opened to 0.0.0.0/0 → CRITICAL
- IAM-related change → HIGH
- Security group rule change → HIGH
- Resource replacement → HIGH
- Resource deletion → HIGH
- Instance size change → MEDIUM
- Tag change → LOW
- No matching rule → INFO (fallback)
- Rules loaded from YAML
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.drift.models import AttributeChange, DriftAction, DriftedResource, DriftSeverity
from app.policy.engine import PolicyEngine, PolicyRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RULES_PATH = "app/policy/rules.yaml"


def _make_sg_rule_resource(
    actual_remote: str = "0.0.0.0/0",
    action: DriftAction = DriftAction.UPDATE,
) -> DriftedResource:
    return DriftedResource(
        address="ibm_is_security_group_rule.app_https",
        resource_type="ibm_is_security_group_rule",
        resource_name="app_https",
        action=action,
        changes=[
            AttributeChange(attribute="remote", expected="10.0.0.0/16", actual=actual_remote)
        ],
    )


def _make_iam_resource(action: DriftAction = DriftAction.UPDATE) -> DriftedResource:
    return DriftedResource(
        address="ibm_iam_access_group_policy.admin",
        resource_type="ibm_iam_access_group_policy",
        resource_name="admin",
        action=action,
        changes=[
            AttributeChange(attribute="roles", expected='["Viewer"]', actual='["Administrator"]')
        ],
    )


def _make_instance_resource() -> DriftedResource:
    return DriftedResource(
        address="ibm_is_instance.app",
        resource_type="ibm_is_instance",
        resource_name="app",
        action=DriftAction.UPDATE,
        changes=[
            AttributeChange(attribute="profile", expected="bx2-2x8", actual="bx2-4x16")
        ],
    )


def _make_tag_resource() -> DriftedResource:
    return DriftedResource(
        address="ibm_is_vpc.main",
        resource_type="ibm_is_vpc",
        resource_name="main",
        action=DriftAction.UPDATE,
        changes=[
            AttributeChange(attribute="tags", expected='["env:stage"]', actual='["env:prod"]')
        ],
    )


def _make_vpc_delete_resource() -> DriftedResource:
    return DriftedResource(
        address="ibm_is_instance.prod_server",
        resource_type="ibm_is_instance",
        resource_name="prod_server",
        action=DriftAction.DELETE,
        changes=[
            AttributeChange(attribute="name", expected="prod-server", actual=None)
        ],
    )


def _make_replace_resource() -> DriftedResource:
    return DriftedResource(
        address="ibm_is_vpc.main",
        resource_type="ibm_is_vpc",
        resource_name="main",
        action=DriftAction.REPLACE,
        changes=[
            AttributeChange(attribute="address_prefix_management", expected="auto", actual="manual")
        ],
    )


# ---------------------------------------------------------------------------
# Tests using the real rules.yaml
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(rules_path=RULES_PATH)


def test_engine_loads_rules(engine: PolicyEngine) -> None:
    """Policy engine should load rules from YAML."""
    assert len(engine._rules) > 0


# Scenario 6: Security group opened to public internet
def test_sg_public_access_is_critical(engine: PolicyEngine) -> None:
    resource = _make_sg_rule_resource(actual_remote="0.0.0.0/0")
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.CRITICAL
    assert any("CRITICAL" in r for r in result.policy_matched_rules)


def test_sg_private_cidr_change_is_high(engine: PolicyEngine) -> None:
    """Changing remote CIDR to a private range is HIGH (sg rule change, not public)."""
    resource = _make_sg_rule_resource(actual_remote="192.168.1.0/24")
    result = engine.evaluate(resource)
    # Should match HIGH_SECURITY_GROUP_RULE_ANY_CHANGE
    assert result.policy_severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL)


# Scenario 7: IAM-related change
def test_iam_change_is_high(engine: PolicyEngine) -> None:
    resource = _make_iam_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity in (DriftSeverity.CRITICAL, DriftSeverity.HIGH)


def test_iam_delete_is_high(engine: PolicyEngine) -> None:
    resource = _make_iam_resource(action=DriftAction.DELETE)
    result = engine.evaluate(resource)
    assert result.policy_severity in (DriftSeverity.CRITICAL, DriftSeverity.HIGH)


def test_instance_size_change_is_medium(engine: PolicyEngine) -> None:
    resource = _make_instance_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.MEDIUM


def test_tag_change_is_low(engine: PolicyEngine) -> None:
    resource = _make_tag_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.LOW


def test_resource_deletion_is_high(engine: PolicyEngine) -> None:
    resource = _make_vpc_delete_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity in (DriftSeverity.CRITICAL, DriftSeverity.HIGH)


def test_resource_replacement_is_high(engine: PolicyEngine) -> None:
    resource = _make_replace_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL)


def test_matched_rules_populated(engine: PolicyEngine) -> None:
    resource = _make_sg_rule_resource()
    result = engine.evaluate(resource)
    assert len(result.policy_matched_rules) > 0


# ---------------------------------------------------------------------------
# Tests with inline YAML rules (isolated, no file dependency)
# ---------------------------------------------------------------------------


def _make_engine_from_yaml(yaml_text: str, tmp_path: Path) -> PolicyEngine:
    rules_file = tmp_path / "test_rules.yaml"
    rules_file.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return PolicyEngine(rules_path=str(rules_file))


def test_empty_rules_file_returns_info(tmp_path: Path) -> None:
    engine = _make_engine_from_yaml("rules: []", tmp_path)
    resource = _make_sg_rule_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.INFO


def test_missing_rules_file_returns_info(tmp_path: Path) -> None:
    engine = PolicyEngine(rules_path=str(tmp_path / "does_not_exist.yaml"))
    resource = _make_sg_rule_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.INFO


def test_resource_type_prefix_matching(tmp_path: Path) -> None:
    """Resource type prefix match should work (ibm_is_security_group matches ibm_is_security_group_rule)."""
    yaml_text = """
    rules:
      - id: TEST_RULE
        severity: HIGH
        description: Test
        match:
          resource_types:
            - ibm_is_security_group
          actions:
            - update
    """
    engine = _make_engine_from_yaml(yaml_text, tmp_path)
    resource = _make_sg_rule_resource()
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.HIGH


def test_action_mismatch_no_match(tmp_path: Path) -> None:
    """Rule requiring 'delete' should not match an 'update' action."""
    yaml_text = """
    rules:
      - id: TEST_RULE
        severity: CRITICAL
        description: Test
        match:
          resource_types:
            - ibm_is_security_group_rule
          actions:
            - delete
    """
    engine = _make_engine_from_yaml(yaml_text, tmp_path)
    resource = _make_sg_rule_resource(action=DriftAction.UPDATE)
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.INFO


def test_value_pattern_matching(tmp_path: Path) -> None:
    """Value pattern should match against actual values."""
    yaml_text = """
    rules:
      - id: TEST_PUBLIC
        severity: CRITICAL
        description: Test public CIDR
        match:
          resource_types: []
          actions:
            - update
          value_patterns:
            - "^0\\\\.0\\\\.0\\\\.0/0$"
    """
    engine = _make_engine_from_yaml(yaml_text, tmp_path)
    resource = _make_sg_rule_resource(actual_remote="0.0.0.0/0")
    result = engine.evaluate(resource)
    assert result.policy_severity == DriftSeverity.CRITICAL


def test_evaluate_all_processes_all_resources(engine: PolicyEngine) -> None:
    resources = [_make_sg_rule_resource(), _make_tag_resource()]
    results = engine.evaluate_all(resources)
    assert len(results) == 2
    for r in results:
        assert r.policy_severity is not None
