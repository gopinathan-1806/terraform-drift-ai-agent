"""
pytest configuration and shared fixtures.

All fixtures use mocked data — no real IBM Cloud account required.
"""
from __future__ import annotations

import json
import os

import pytest

# ---------------------------------------------------------------------------
# Ensure tests always use the test environment settings
# ---------------------------------------------------------------------------

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("SLACK_ENABLED", "false")
os.environ.setdefault("SLACK_WEBHOOK_URL", "")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("TERRAFORM_WORKING_DIR", "/tmp/test_terraform")


# ---------------------------------------------------------------------------
# Terraform plan JSON fixtures
# ---------------------------------------------------------------------------

FIXTURE_NO_DRIFT: dict = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_security_group_rule.app_https",
            "type": "ibm_is_security_group_rule",
            "name": "app_https",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["no-op"],
                "before": {"remote": "10.0.0.0/16", "port_min": 443, "port_max": 443},
                "after": {"remote": "10.0.0.0/16", "port_min": 443, "port_max": 443},
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}

FIXTURE_SINGLE_DRIFT: dict = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_security_group_rule.app_https",
            "type": "ibm_is_security_group_rule",
            "name": "app_https",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["update"],
                "before": {"remote": "10.0.0.0/16", "port_min": 443, "port_max": 443},
                "after": {"remote": "0.0.0.0/0", "port_min": 443, "port_max": 443},
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}

FIXTURE_MULTI_DRIFT: dict = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_security_group_rule.app_https",
            "type": "ibm_is_security_group_rule",
            "name": "app_https",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["update"],
                "before": {"remote": "10.0.0.0/16", "port_min": 443, "port_max": 443},
                "after": {"remote": "0.0.0.0/0", "port_min": 80, "port_max": 80},
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}

FIXTURE_REPLACE: dict = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_vpc.main",
            "type": "ibm_is_vpc",
            "name": "main",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["delete", "create"],
                "before": {"name": "prod-vpc", "address_prefix_management": "auto"},
                "after": {"name": "prod-vpc", "address_prefix_management": "manual"},
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}

FIXTURE_DELETE: dict = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_is_security_group.app",
            "type": "ibm_is_security_group",
            "name": "app",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["delete"],
                "before": {"name": "app-sg", "vpc": "vpc-abc123"},
                "after": None,
                "before_sensitive": {},
                "after_sensitive": {},
            },
        }
    ],
}

FIXTURE_SENSITIVE: dict = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [
        {
            "address": "ibm_resource_instance.kms",
            "type": "ibm_resource_instance",
            "name": "kms",
            "provider_name": "registry.terraform.io/ibm-cloud/ibm",
            "change": {
                "actions": ["update"],
                "before": {"name": "prod-kms", "parameters": {"kms_key": "old-key-id"}},
                "after": {"name": "prod-kms", "parameters": {"kms_key": "new-key-id"}},
                "before_sensitive": {"parameters": {"kms_key": True}},
                "after_sensitive": {"parameters": {"kms_key": True}},
            },
        }
    ],
}


@pytest.fixture
def tf_plan_no_drift() -> dict:
    return FIXTURE_NO_DRIFT


@pytest.fixture
def tf_plan_single_drift() -> dict:
    return FIXTURE_SINGLE_DRIFT


@pytest.fixture
def tf_plan_multi_drift() -> dict:
    return FIXTURE_MULTI_DRIFT


@pytest.fixture
def tf_plan_replace() -> dict:
    return FIXTURE_REPLACE


@pytest.fixture
def tf_plan_delete() -> dict:
    return FIXTURE_DELETE


@pytest.fixture
def tf_plan_sensitive() -> dict:
    return FIXTURE_SENSITIVE
