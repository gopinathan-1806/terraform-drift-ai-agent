"""
Drift fingerprinting.

Generates deterministic SHA-256 fingerprints for drift events so that
the scheduler can avoid sending duplicate Slack notifications.

Fingerprint inputs:
    resource_address + attribute + expected_value + actual_value

This uniquely identifies a specific change on a specific resource.
If the actual value changes again, the fingerprint changes → new notification.
If the same change persists across runs, the fingerprint is unchanged → no new notification.
"""
from __future__ import annotations

import hashlib

from app.drift.models import AttributeChange, DriftedResource


class DriftFingerprint:
    """Generates and manages SHA-256 fingerprints for drift events."""

    @staticmethod
    def for_attribute_change(
        resource_address: str,
        change: AttributeChange,
    ) -> str:
        """
        Generate a SHA-256 fingerprint for a single attribute change.

        The fingerprint is stable for the same (resource, attribute, before, after) tuple.

        Args:
            resource_address: Terraform resource address, e.g. 'ibm_is_security_group_rule.app_https'
            change: The AttributeChange describing the drift.

        Returns:
            Lowercase hex SHA-256 digest string (64 characters).
        """
        # Normalize values to strings for hashing.
        # None is represented as "__NONE__" (not "None") to avoid collision
        # with an attribute whose value is the literal string "None".
        expected_str = str(change.expected) if change.expected is not None else "__NONE__"
        actual_str = str(change.actual) if change.actual is not None else "__NONE__"

        raw = f"{resource_address}::{change.attribute}::{expected_str}::{actual_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def for_resource(cls, resource: DriftedResource) -> list[str]:
        """
        Generate fingerprints for all attribute changes on a resource.

        Returns one fingerprint per AttributeChange.
        """
        return [
            cls.for_attribute_change(resource.address, change)
            for change in resource.changes
        ]

    @classmethod
    def for_report(cls, resources: list[DriftedResource]) -> dict[str, tuple[DriftedResource, AttributeChange]]:
        """
        Generate a fingerprint map for all changes in a drift report.

        Returns:
            Dict mapping fingerprint → (resource, attribute_change).
        """
        result: dict[str, tuple[DriftedResource, AttributeChange]] = {}
        for resource in resources:
            for change in resource.changes:
                fp = cls.for_attribute_change(resource.address, change)
                result[fp] = (resource, change)
        return result
