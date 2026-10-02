"""
Phase 1 — Smoke tests for project structure and configuration.

Verifies that all packages import correctly and settings load
without requiring any external services.
"""
from __future__ import annotations


def test_settings_load() -> None:
    """Settings should load from environment without errors."""
    from app.config.settings import get_settings

    s = get_settings()
    assert s.app_name == "IBM Cloud Terraform DriftGuard AI"
    assert s.app_version == "0.1.0"
    assert s.environment == "test"
    assert s.llm_provider == "none"


def test_settings_log_level_validation() -> None:
    """Invalid log level should raise ValueError."""
    import pytest
    from pydantic import ValidationError
    from app.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(log_level="INVALID")


def test_drift_models_import() -> None:
    """Drift models should import and instantiate cleanly."""
    from app.drift.models import (
        AttributeChange,
        DriftAction,
        DriftedResource,
        DriftEvent,
        DriftReport,
        DriftSeverity,
        DriftStatus,
    )

    change = AttributeChange(attribute="remote", expected="10.0.0.0/16", actual="0.0.0.0/0")
    assert change.display_expected() == "10.0.0.0/16"
    assert change.display_actual() == "0.0.0.0/0"

    sensitive_change = AttributeChange(
        attribute="api_key",
        expected="old-key",
        actual="new-key",
        is_sensitive=True,
    )
    assert sensitive_change.display_expected() == "[sensitive]"
    assert sensitive_change.display_actual() == "[sensitive]"


def test_terraform_models_import() -> None:
    """Terraform models should import and instantiate cleanly."""
    from app.terraform.models import TerraformResourceChange, TerraformChangeDetail

    rc = TerraformResourceChange(
        address="ibm_is_security_group_rule.app_https",
        type="ibm_is_security_group_rule",
        name="app_https",
        change=TerraformChangeDetail(
            actions=["update"],
            before={"remote": "10.0.0.0/16"},
            after={"remote": "0.0.0.0/0"},
        ),
    )
    assert rc.action_summary == "update"
    assert not rc.is_no_op


def test_terraform_model_no_op() -> None:
    """A no-op resource change should be identified correctly."""
    from app.terraform.models import TerraformResourceChange, TerraformChangeDetail

    rc = TerraformResourceChange(
        address="ibm_is_security_group_rule.app_https",
        type="ibm_is_security_group_rule",
        name="app_https",
        change=TerraformChangeDetail(actions=["no-op"]),
    )
    assert rc.is_no_op
    assert rc.action_summary == "no-op"


def test_terraform_model_replace() -> None:
    """Replace action should be identified from delete+create actions."""
    from app.terraform.models import TerraformResourceChange, TerraformChangeDetail

    rc = TerraformResourceChange(
        address="ibm_is_vpc.main",
        type="ibm_is_vpc",
        name="main",
        change=TerraformChangeDetail(actions=["delete", "create"]),
    )
    assert rc.action_summary == "replace"


def test_drift_report_highest_severity() -> None:
    """DriftReport.highest_severity should return the most severe level."""
    from app.drift.models import DriftReport, DriftedResource, DriftAction, DriftSeverity

    report = DriftReport(
        environment="test",
        terraform_workspace="default",
        drift_detected=True,
        resources=[
            DriftedResource(
                address="ibm_is_security_group_rule.app_https",
                resource_type="ibm_is_security_group_rule",
                resource_name="app_https",
                action=DriftAction.UPDATE,
                policy_severity=DriftSeverity.HIGH,
            ),
            DriftedResource(
                address="ibm_is_vpc.main",
                resource_type="ibm_is_vpc",
                resource_name="main",
                action=DriftAction.UPDATE,
                policy_severity=DriftSeverity.MEDIUM,
            ),
        ],
    )
    assert report.highest_severity == DriftSeverity.HIGH


def test_storage_interface_contract(tmp_path) -> None:
    """LocalDriftStore should implement the DriftStoreInterface contract."""
    from app.storage.local import LocalDriftStore
    from app.storage.interface import DriftStoreInterface

    store = LocalDriftStore(state_dir=str(tmp_path / "state"))
    assert isinstance(store, DriftStoreInterface)
    assert store.list_events() == []
    assert store.get_event("a" * 64) is None


def test_fastapi_app_creates() -> None:
    """FastAPI app should be created without errors."""
    from app.main import create_app

    app = create_app()
    assert app.title == "IBM Cloud Terraform DriftGuard AI"


def test_health_route_exists() -> None:
    """Health endpoint should return 200."""
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
