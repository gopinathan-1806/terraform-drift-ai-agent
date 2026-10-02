"""
Deterministic policy engine.

Evaluates Terraform drift against a configurable set of rules and assigns
an initial severity level BEFORE the AI agent is invoked.

The policy engine is 100% deterministic — it never calls an LLM.
Rules are loaded from app/policy/rules.yaml.

Evaluation order:
1. Rules are checked in order of severity (CRITICAL → HIGH → MEDIUM → LOW → INFO)
2. The first rule that matches ALL of its criteria wins for that resource
3. Resources with no matching rule receive INFO severity

Rule matching criteria (all must match):
- resource_types:   list of resource type prefixes (empty = match all)
- actions:          list of DriftAction values (empty = match all)
- attributes:       list of attribute names (match if ANY changed attribute is in this list)
- value_patterns:   list of regex patterns applied to the ACTUAL value
                    (match if ANY attribute's actual value matches ANY pattern)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.config.logging import get_logger
from app.config.settings import get_settings
from app.drift.models import DriftAction, DriftedResource, DriftSeverity

logger = get_logger("policy.engine")
settings = get_settings()


# ---------------------------------------------------------------------------
# Rule model
# ---------------------------------------------------------------------------


class PolicyRule:
    """A single policy rule loaded from rules.yaml."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = data["id"]
        self.severity: DriftSeverity = DriftSeverity(data["severity"])
        self.description: str = data.get("description", "")
        match = data.get("match", {})
        self.resource_types: list[str] = match.get("resource_types", [])
        self.actions: list[str] = match.get("actions", [])
        self.attributes: list[str] = match.get("attributes", [])
        self.value_patterns: list[str] = match.get("value_patterns", [])
        # Pre-compile value patterns for performance
        self._compiled_patterns: list[re.Pattern] = [
            re.compile(p) for p in self.value_patterns
        ]

    def matches(self, resource: DriftedResource) -> bool:
        """
        Return True if this rule applies to the given DriftedResource.

        All specified criteria must match (AND logic).
        Within a list criterion (e.g. resource_types, attributes), any match suffices (OR logic).
        An empty list for a criterion means "match any".
        """
        # 1. Resource type prefix match
        if self.resource_types:
            if not any(
                resource.resource_type.startswith(rt) for rt in self.resource_types
            ):
                return False

        # 2. Action match
        if self.actions:
            if resource.action.value not in self.actions:
                return False

        # 3. Changed attribute name match
        if self.attributes:
            changed_attr_names = {c.attribute for c in resource.changes}
            if not any(attr in changed_attr_names for attr in self.attributes):
                return False

        # 4. Value pattern match (applied to actual values of changed attributes)
        if self._compiled_patterns:
            actual_values = [
                str(c.actual) for c in resource.changes if c.actual is not None
            ]
            if not any(
                pattern.search(val)
                for pattern in self._compiled_patterns
                for val in actual_values
            ):
                return False

        return True


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PolicyEngine:
    """
    Evaluates drift against the configured policy rules.

    Rules are loaded once from the YAML file.  The evaluate() method is
    idempotent and thread-safe (read-only after initialization).
    """

    # Severity evaluation order — most severe first
    _SEVERITY_ORDER = [
        DriftSeverity.CRITICAL,
        DriftSeverity.HIGH,
        DriftSeverity.MEDIUM,
        DriftSeverity.LOW,
        DriftSeverity.INFO,
    ]

    def __init__(self, rules_path: str | None = None) -> None:
        path = Path(rules_path or settings.policy_rules_path)
        self._rules: list[PolicyRule] = self._load_rules(path)
        logger.info("Policy engine initialized", rules_count=len(self._rules), path=str(path))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def evaluate(self, resource: DriftedResource) -> DriftedResource:
        """
        Evaluate a single DriftedResource against all policy rules.

        Populates:
            resource.policy_severity
            resource.policy_matched_rules

        Returns the mutated resource (for chaining).
        """
        matched_rules: list[str] = []
        winning_severity: DriftSeverity | None = None

        # Evaluate rules in severity order so CRITICAL rules are checked first
        for rule in self._rules:
            if rule.matches(resource):
                matched_rules.append(rule.id)
                # First match determines severity (rules.yaml should be ordered by severity)
                if winning_severity is None:
                    winning_severity = rule.severity
                    logger.debug(
                        "Policy rule matched",
                        rule_id=rule.id,
                        severity=rule.severity.value,
                        resource=resource.address,
                    )

        # Apply result
        resource.policy_severity = winning_severity or DriftSeverity.INFO
        resource.policy_matched_rules = matched_rules

        logger.info(
            "Policy evaluation complete",
            resource=resource.address,
            action=resource.action.value,
            severity=resource.policy_severity.value,
            rules_matched=matched_rules,
        )
        return resource

    def evaluate_all(self, resources: list[DriftedResource]) -> list[DriftedResource]:
        """Evaluate all resources in a drift report."""
        return [self.evaluate(r) for r in resources]

    # ------------------------------------------------------------------ #
    # Rule loading
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_rules(path: Path) -> list[PolicyRule]:
        """Load policy rules from a YAML file."""
        if not path.exists():
            logger.warning("Policy rules file not found, using empty ruleset", path=str(path))
            return []

        try:
            content = path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            rules_data: list[dict] = data.get("rules", [])
            rules = [PolicyRule(r) for r in rules_data]
            logger.debug("Policy rules loaded", count=len(rules))
            return rules
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load policy rules", path=str(path), error=str(exc))
            return []
