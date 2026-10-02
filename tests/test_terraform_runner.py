"""
Phase 2 — Tests for the Terraform runner.

All tests are mocked — no real terraform binary or IBM Cloud account required.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.terraform.runner import (
    TerraformCommandNotAllowedError,
    TerraformInitError,
    TerraformNotFoundError,
    TerraformOutputTooLargeError,
    TerraformPlanError,
    TerraformResult,
    TerraformRunner,
    TerraformValidateError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a mock subprocess.CompletedProcess."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


SAMPLE_PLAN_JSON = {
    "format_version": "1.2",
    "terraform_version": "1.9.0",
    "resource_changes": [],
}


# ---------------------------------------------------------------------------
# Command allowlist tests
# ---------------------------------------------------------------------------


def test_apply_is_blocked() -> None:
    """terraform apply must be rejected before any subprocess call."""
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformCommandNotAllowedError, match="apply"):
        runner._run(["apply"])


def test_destroy_is_blocked() -> None:
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformCommandNotAllowedError, match="destroy"):
        runner._run(["destroy"])


def test_state_rm_is_blocked() -> None:
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformCommandNotAllowedError, match="state"):
        runner._run(["state"])


def test_import_is_blocked() -> None:
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformCommandNotAllowedError, match="import"):
        runner._run(["import"])


def test_taint_is_blocked() -> None:
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformCommandNotAllowedError, match="taint"):
        runner._run(["taint"])


def test_allowed_commands_do_not_raise_allowlist_error() -> None:
    """Allowed commands should pass the allowlist check (even if subprocess fails)."""
    from app.terraform.runner import _ALLOWED_SUBCOMMANDS, TerraformRunner

    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    for cmd in _ALLOWED_SUBCOMMANDS:
        # Should not raise TerraformCommandNotAllowedError
        # (may raise other errors when subprocess fails, that's expected)
        try:
            runner._assert_command_allowed(cmd)
        except TerraformCommandNotAllowedError:
            pytest.fail(f"Allowed command {cmd!r} was rejected by the allowlist")


# ---------------------------------------------------------------------------
# Runner execution tests (subprocess mocked)
# ---------------------------------------------------------------------------


@patch("subprocess.run")
def test_init_success(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(0, "Terraform has been successfully initialized!")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    result = runner.init()
    assert result.success
    assert result.return_code == 0


@patch("subprocess.run")
def test_init_failure_raises(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(1, "", "Error: Could not initialize provider")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformInitError):
        runner.init()


@patch("subprocess.run")
def test_validate_success(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(0, "Success! The configuration is valid.")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    result = runner.validate()
    assert result.success


@patch("subprocess.run")
def test_validate_failure_raises(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(1, "", "Error: Invalid configuration")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformValidateError):
        runner.validate()


@patch("subprocess.run")
def test_plan_refresh_only_success(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(0, "Plan: 0 to add, 1 to change, 0 to destroy.")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    result = runner.plan_refresh_only("/tmp/drift.tfplan")
    assert result.success
    # Ensure -refresh-only flag was included
    call_args = mock_run.call_args[0][0]
    assert "-refresh-only" in call_args


@patch("subprocess.run")
def test_plan_refresh_only_never_calls_apply(mock_run: MagicMock) -> None:
    """The plan command must never include 'apply' in the argument list."""
    mock_run.return_value = _make_result(0, "")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    runner.plan_refresh_only("/tmp/drift.tfplan")
    call_args = mock_run.call_args[0][0]
    assert "apply" not in call_args


@patch("subprocess.run")
def test_show_json_returns_parsed_dict(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(0, json.dumps(SAMPLE_PLAN_JSON))
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    result = runner.show_json("/tmp/drift.tfplan")
    assert result["terraform_version"] == "1.9.0"
    assert "resource_changes" in result


@patch("subprocess.run")
def test_show_json_invalid_json_raises(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(0, "NOT VALID JSON{{{")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    with pytest.raises(TerraformPlanError, match="invalid JSON"):
        runner.show_json("/tmp/drift.tfplan")


@patch("subprocess.run")
def test_output_too_large_raises(mock_run: MagicMock) -> None:
    """Output exceeding max_output_bytes should raise TerraformOutputTooLargeError."""
    large_output = "x" * 100
    mock_run.return_value = _make_result(0, large_output)
    # Set max to 50 bytes to trigger the guard
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform", max_output_bytes=50)
    with pytest.raises(TerraformOutputTooLargeError):
        runner.show_json("/tmp/drift.tfplan")


def test_terraform_not_found_raises() -> None:
    """When the binary is not on PATH, TerraformNotFoundError should be raised."""
    runner = TerraformRunner(
        working_dir="/tmp",
        terraform_bin="terraform_does_not_exist_xyzxyz",
    )
    with pytest.raises(TerraformNotFoundError):
        runner._ensure_terraform_available()


@patch("subprocess.run")
def test_result_dataclass_success_flag(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(0, "ok")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    result = runner._run(["init"])
    assert result.success is True
    assert result.return_code == 0


@patch("subprocess.run")
def test_result_dataclass_failure_flag(mock_run: MagicMock) -> None:
    mock_run.return_value = _make_result(1, "", "error")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    result = runner._run(["init"])
    assert result.success is False
    assert result.return_code == 1


@patch("subprocess.run")
def test_env_has_checkpoint_disable(mock_run: MagicMock) -> None:
    """subprocess should be called with CHECKPOINT_DISABLE=1."""
    mock_run.return_value = _make_result(0, "ok")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    runner._run(["init"])
    call_kwargs = mock_run.call_args[1]
    env = call_kwargs["env"]
    assert env["CHECKPOINT_DISABLE"] == "1"
    assert env["TF_IN_AUTOMATION"] == "1"


@patch("subprocess.run")
def test_env_injects_ibmcloud_stage_settings(mock_run: MagicMock, monkeypatch) -> None:
    """_build_env should inject IBM Cloud Stage credentials and endpoint overrides."""
    import app.terraform.runner as runner_module

    monkeypatch.setattr(runner_module.settings, "ibmcloud_api_key", "test-api-key-abc123")
    monkeypatch.setattr(runner_module.settings, "ibmcloud_region", "us-south")
    monkeypatch.setattr(runner_module.settings, "ibmcloud_iam_api_endpoint", "https://iam.test.cloud.ibm.com")
    monkeypatch.setattr(runner_module.settings, "ibmcloud_is_ng_api_endpoint", "https://us-south-stage01.iaasdev.cloud.ibm.com/v1")
    monkeypatch.setattr(runner_module.settings, "ibmcloud_gt_api_endpoint", "https://tags.global-search-tagging.test.cloud.ibm.com")

    mock_run.return_value = _make_result(0, "ok")
    runner = TerraformRunner(working_dir="/tmp", terraform_bin="terraform")
    runner._run(["init"])

    env = mock_run.call_args[1]["env"]
    assert env.get("IBMCLOUD_API_KEY") == "test-api-key-abc123"
    assert env.get("TF_VAR_ibmcloud_api_key") == "test-api-key-abc123"
    assert env.get("IBMCLOUD_REGION") == "us-south"
    # Stage endpoint overrides must be injected
    assert env.get("IBMCLOUD_IAM_API_ENDPOINT") == "https://iam.test.cloud.ibm.com"
    assert env.get("IBMCLOUD_IS_NG_API_ENDPOINT") == "https://us-south-stage01.iaasdev.cloud.ibm.com/v1"
    assert env.get("IBMCLOUD_GT_API_ENDPOINT") == "https://tags.global-search-tagging.test.cloud.ibm.com"
