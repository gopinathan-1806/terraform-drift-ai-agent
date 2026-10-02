"""
Terraform plan JSON parser.

Parses the output of:
    terraform show -json <plan-file>

Converts the raw Terraform JSON into normalized DriftedResource models.

Key responsibilities:
- Validate the top-level JSON structure
- Ignore no-op resource changes
- Identify changed attributes by diffing `before` vs `after`
- Handle sensitive values (before_sensitive / after_sensitive)
- Handle nested/complex attribute structures
- Map Terraform actions → DriftAction enum
- Return a list of DriftedResource instances ready for the policy engine

This module ONLY reads/parses data — it never executes Terraform.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.config.logging import get_logger
from app.drift.models import AttributeChange, DriftAction, DriftedResource
from app.terraform.models import TerraformPlanOutput, TerraformResourceChange

logger = get_logger("terraform.parser")


class TerraformParseError(ValueError):
    """Raised when the Terraform JSON cannot be parsed."""


class TerraformParser:
    """
    Parses terraform show -json output into normalized drift models.

    Usage:
        parser = TerraformParser()
        resources = parser.parse(plan_json_dict)
    """

    def parse(self, plan_json: dict[str, Any]) -> list[DriftedResource]:
        """
        Parse a terraform show -json plan dict.

        Returns a list of DriftedResource instances for all changed resources.
        Resources with action "no-op" are excluded.

        Args:
            plan_json: The dict returned by json.loads(terraform show -json output)

        Returns:
            List of DriftedResource with populated `changes`.

        Raises:
            TerraformParseError: If the JSON structure is invalid.
        """
        plan = self._parse_plan(plan_json)
        drifted: list[DriftedResource] = []

        # For `terraform plan -refresh-only`, actual drift appears in
        # `resource_drift`, NOT `resource_changes` (which is always empty).
        # For a normal plan, drift appears in `resource_changes`.
        # Merge both, dedup by address so we never double-report.
        seen_addresses: set[str] = set()
        all_resource_changes = list(plan.resource_drift) + list(plan.resource_changes)

        for rc in all_resource_changes:
            if rc.address in seen_addresses:
                continue

            if rc.is_no_op:
                logger.debug("Skipping no-op resource", address=rc.address)
                continue

            action = self._map_action(rc.action_summary)
            if action == DriftAction.NO_OP:
                continue

            changes = self._extract_changes(rc)
            if not changes:
                # Resource entry present but no attribute-level differences — skip
                logger.debug("Skipping resource with no attribute changes", address=rc.address)
                continue

            seen_addresses.add(rc.address)
            resource = DriftedResource(
                address=rc.address,
                resource_type=rc.type,
                resource_name=rc.name,
                module_address=rc.module_address,
                action=action,
                changes=changes,
            )
            drifted.append(resource)
            logger.info(
                "Drift detected",
                address=rc.address,
                action=action.value,
                changed_attributes=[c.attribute for c in changes],
            )

        return drifted

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_plan(plan_json: dict[str, Any]) -> TerraformPlanOutput:
        """Validate and parse the raw plan JSON into a TerraformPlanOutput model."""
        if not isinstance(plan_json, dict):
            raise TerraformParseError("Terraform plan JSON must be a dict at the top level")

        try:
            return TerraformPlanOutput.model_validate(plan_json)
        except ValidationError as exc:
            raise TerraformParseError(f"Terraform plan JSON validation failed: {exc}") from exc

    @staticmethod
    def _map_action(action_str: str) -> DriftAction:
        """Map a Terraform action string to a DriftAction enum value."""
        mapping = {
            "create": DriftAction.CREATE,
            "update": DriftAction.UPDATE,
            "delete": DriftAction.DELETE,
            "replace": DriftAction.REPLACE,
            "no-op": DriftAction.NO_OP,
        }
        return mapping.get(action_str, DriftAction.UPDATE)

    def _extract_changes(self, rc: TerraformResourceChange) -> list[AttributeChange]:
        """
        Compare `before` and `after` dicts and return changed AttributeChange instances.

        For delete actions where `after` is None, all `before` attributes are considered changed.
        For create actions where `before` is None, all `after` attributes are considered changed.
        For update/replace, only attributes that differ are included.

        Sensitive values are masked — they are flagged but the value is NOT included in logs
        or the returned model.
        """
        before = rc.change.before or {}
        after = rc.change.after or {}
        before_sensitive = rc.change.before_sensitive or {}
        after_sensitive = rc.change.after_sensitive or {}

        # For delete: report all before attributes as changing to None
        if rc.action_summary == "delete":
            return self._changes_for_delete(before, before_sensitive)

        # For create: report all after attributes as changing from None
        if rc.action_summary == "create":
            return self._changes_for_create(after, after_sensitive)

        # For update/replace: diff before vs after
        return self._diff_attributes(before, after, before_sensitive, after_sensitive)

    @staticmethod
    def _is_sensitive(sensitive_map: Any, key: str) -> bool:
        """
        Return True if the given key is marked sensitive.

        Terraform sensitive maps can be:
        - A dict like {"field": true} or {"field": {"nested_key": true}}
        - A boolean True (entire resource is sensitive)
        """
        if isinstance(sensitive_map, bool):
            return sensitive_map
        if isinstance(sensitive_map, dict):
            val = sensitive_map.get(key, False)
            if isinstance(val, bool):
                return val
            if isinstance(val, dict):
                return bool(val)  # nested object means something is sensitive
        return False

    def _diff_attributes(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        before_sensitive: Any,
        after_sensitive: Any,
    ) -> list[AttributeChange]:
        """Return AttributeChange entries for attributes that differ between before and after."""
        changes: list[AttributeChange] = []
        all_keys = set(before.keys()) | set(after.keys())

        for key in sorted(all_keys):
            bval = before.get(key)
            aval = after.get(key)

            # Skip unknown/computed values (Terraform marks these as dicts with unknown=true)
            if isinstance(aval, dict) and aval.get("unknown") is True:
                continue

            if bval == aval:
                continue  # No change for this attribute

            sensitive = self._is_sensitive(before_sensitive, key) or self._is_sensitive(
                after_sensitive, key
            )

            changes.append(
                AttributeChange(
                    attribute=key,
                    expected=self._flatten_value(bval),
                    actual=self._flatten_value(aval),
                    is_sensitive=sensitive,
                )
            )

        return changes

    def _changes_for_delete(
        self,
        before: dict[str, Any],
        before_sensitive: Any,
    ) -> list[AttributeChange]:
        """For deleted resources, report all before attributes changing to None."""
        return [
            AttributeChange(
                attribute=key,
                expected=self._flatten_value(val),
                actual=None,
                is_sensitive=self._is_sensitive(before_sensitive, key),
            )
            for key, val in sorted(before.items())
        ]

    def _changes_for_create(
        self,
        after: dict[str, Any],
        after_sensitive: Any,
    ) -> list[AttributeChange]:
        """For created resources, report all after attributes changing from None."""
        return [
            AttributeChange(
                attribute=key,
                expected=None,
                actual=self._flatten_value(val),
                is_sensitive=self._is_sensitive(after_sensitive, key),
            )
            for key, val in sorted(after.items())
        ]

    @staticmethod
    def _flatten_value(value: Any) -> Any:
        """
        Flatten complex nested values to a JSON-safe representation.

        Terraform returns nested dicts/lists for complex attributes.
        We stringify dicts/lists for clean display in Slack messages.
        """
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        # For lists/dicts, produce a compact string representation
        try:
            return json.dumps(value, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
