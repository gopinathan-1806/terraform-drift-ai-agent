"""
Phase 4 — Tests for drift fingerprinting and local state store.
"""
from __future__ import annotations

import tempfile

import pytest

from app.drift.fingerprint import DriftFingerprint
from app.drift.models import AttributeChange, DriftAction, DriftedResource, DriftEvent, DriftSeverity, DriftStatus
from app.storage.local import LocalDriftStore


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------


def _make_change(attribute: str, expected: str, actual: str) -> AttributeChange:
    return AttributeChange(attribute=attribute, expected=expected, actual=actual)


def test_fingerprint_is_deterministic() -> None:
    """Same inputs must always produce the same fingerprint."""
    change = _make_change("remote", "10.0.0.0/16", "0.0.0.0/0")
    fp1 = DriftFingerprint.for_attribute_change("ibm_is_security_group_rule.app_https", change)
    fp2 = DriftFingerprint.for_attribute_change("ibm_is_security_group_rule.app_https", change)
    assert fp1 == fp2


def test_fingerprint_is_sha256_hex() -> None:
    """Fingerprint must be a 64-character hex string."""
    change = _make_change("remote", "10.0.0.0/16", "0.0.0.0/0")
    fp = DriftFingerprint.for_attribute_change("ibm_is_security_group_rule.app_https", change)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_different_address_different_fingerprint() -> None:
    change = _make_change("remote", "10.0.0.0/16", "0.0.0.0/0")
    fp1 = DriftFingerprint.for_attribute_change("resource.a", change)
    fp2 = DriftFingerprint.for_attribute_change("resource.b", change)
    assert fp1 != fp2


def test_different_attribute_different_fingerprint() -> None:
    fp1 = DriftFingerprint.for_attribute_change("resource.a", _make_change("port_min", "443", "80"))
    fp2 = DriftFingerprint.for_attribute_change("resource.a", _make_change("port_max", "443", "80"))
    assert fp1 != fp2


def test_different_expected_different_fingerprint() -> None:
    fp1 = DriftFingerprint.for_attribute_change("resource.a", _make_change("remote", "10.0.0.0/8", "0.0.0.0/0"))
    fp2 = DriftFingerprint.for_attribute_change("resource.a", _make_change("remote", "10.0.0.0/16", "0.0.0.0/0"))
    assert fp1 != fp2


def test_different_actual_different_fingerprint() -> None:
    fp1 = DriftFingerprint.for_attribute_change("resource.a", _make_change("remote", "10.0.0.0/16", "0.0.0.0/0"))
    fp2 = DriftFingerprint.for_attribute_change("resource.a", _make_change("remote", "10.0.0.0/16", "192.168.0.0/16"))
    assert fp1 != fp2


def test_for_resource_returns_one_per_change() -> None:
    resource = DriftedResource(
        address="ibm_is_security_group_rule.app_https",
        resource_type="ibm_is_security_group_rule",
        resource_name="app_https",
        action=DriftAction.UPDATE,
        changes=[
            _make_change("remote", "10.0.0.0/16", "0.0.0.0/0"),
            _make_change("port_min", "443", "80"),
        ],
    )
    fps = DriftFingerprint.for_resource(resource)
    assert len(fps) == 2
    assert fps[0] != fps[1]


# ---------------------------------------------------------------------------
# Duplicate drift detection (Scenario 11)
# ---------------------------------------------------------------------------


def test_same_drift_same_fingerprint_no_duplicate(tf_plan_single_drift: dict) -> None:
    """
    Running the same drift twice should produce identical fingerprints,
    enabling deduplication.
    """
    from app.terraform.parser import TerraformParser

    parser = TerraformParser()
    resources_run1 = parser.parse(tf_plan_single_drift)
    resources_run2 = parser.parse(tf_plan_single_drift)

    fps1 = DriftFingerprint.for_report(resources_run1)
    fps2 = DriftFingerprint.for_report(resources_run2)

    assert set(fps1.keys()) == set(fps2.keys())


# ---------------------------------------------------------------------------
# Local store tests
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path) -> LocalDriftStore:
    """Return a LocalDriftStore using a temporary directory."""
    return LocalDriftStore(state_dir=str(tmp_path / "drift_state"))


def _make_event(fp: str = "a" * 64) -> DriftEvent:
    return DriftEvent(
        fingerprint=fp,
        resource_address="ibm_is_security_group_rule.app_https",
        changed_attribute="remote",
        expected_value="10.0.0.0/16",
        actual_value="0.0.0.0/0",
        policy_severity=DriftSeverity.HIGH,
    )


def test_store_save_and_get(store: LocalDriftStore) -> None:
    event = _make_event()
    store.save_event(event)
    retrieved = store.get_event(event.fingerprint)
    assert retrieved is not None
    assert retrieved.fingerprint == event.fingerprint
    assert retrieved.resource_address == event.resource_address


def test_store_get_missing_returns_none(store: LocalDriftStore) -> None:
    result = store.get_event("b" * 64)
    assert result is None


def test_store_list_empty(store: LocalDriftStore) -> None:
    assert store.list_events() == []


def test_store_list_returns_all(store: LocalDriftStore) -> None:
    e1 = _make_event("a" * 64)
    e2 = _make_event("b" * 64)
    store.save_event(e1)
    store.save_event(e2)
    events = store.list_events()
    assert len(events) == 2


def test_store_delete_removes_event(store: LocalDriftStore) -> None:
    event = _make_event()
    store.save_event(event)
    store.delete_event(event.fingerprint)
    assert store.get_event(event.fingerprint) is None


def test_store_delete_nonexistent_is_silent(store: LocalDriftStore) -> None:
    """Deleting a non-existent event should not raise."""
    store.delete_event("c" * 64)  # should not raise


def test_store_update_event(store: LocalDriftStore) -> None:
    """Saving the same fingerprint twice should overwrite."""
    event = _make_event()
    store.save_event(event)

    updated = event.model_copy(update={"status": DriftStatus.ACTIVE})
    store.save_event(updated)

    retrieved = store.get_event(event.fingerprint)
    assert retrieved is not None
    assert retrieved.status == DriftStatus.ACTIVE


def test_store_invalid_fingerprint_raises(store: LocalDriftStore) -> None:
    """Non-hex fingerprint should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid fingerprint"):
        store.get_event("not-a-valid-fingerprint!")
