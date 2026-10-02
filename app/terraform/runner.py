"""
Terraform CLI runner.

Executes Terraform commands safely with:
- A strict command allowlist (apply/destroy/taint/etc. are BLOCKED)
- Subprocess timeout enforcement
- Maximum output size guard
- Structured logging throughout
- No secrets in log output

Allowed commands:
  init, validate, plan, show

Everything else raises TerraformCommandNotAllowedError.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config.logging import get_logger
from app.config.settings import get_settings

logger = get_logger("terraform.runner")
settings = get_settings()

# ---------------------------------------------------------------------------
# Command allowlist — ONLY these sub-commands are permitted.
# The application MUST NEVER execute apply, destroy, taint, state rm, import,
# or any other infrastructure-changing operation.
# ---------------------------------------------------------------------------
_ALLOWED_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "init",
        "validate",
        "plan",
        "show",
        "version",
    }
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TerraformError(RuntimeError):
    """Base class for Terraform runner errors."""


class TerraformCommandNotAllowedError(TerraformError):
    """Raised when a caller attempts to execute a blocked Terraform command."""


class TerraformInitError(TerraformError):
    """Raised when terraform init fails."""


class TerraformValidateError(TerraformError):
    """Raised when terraform validate fails."""


class TerraformPlanError(TerraformError):
    """Raised when terraform plan fails."""


class TerraformOutputTooLargeError(TerraformError):
    """Raised when Terraform output exceeds the configured maximum."""


class TerraformNotFoundError(TerraformError):
    """Raised when the terraform binary cannot be found."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class TerraformResult:
    """Result of a single Terraform command execution."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    success: bool = field(init=False)

    def __post_init__(self) -> None:
        self.success = self.return_code == 0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class TerraformRunner:
    """
    Executes Terraform CLI commands safely.

    Only read/refresh/plan/show/validate operations are permitted.
    terraform apply and any state-modifying command will be rejected
    with TerraformCommandNotAllowedError before subprocess is invoked.
    """

    def __init__(
        self,
        working_dir: str | None = None,
        terraform_bin: str | None = None,
        timeout_seconds: int | None = None,
        max_output_bytes: int | None = None,
    ) -> None:
        self._working_dir = Path(working_dir or settings.terraform_working_dir).resolve()
        self._terraform_bin = terraform_bin or settings.terraform_bin
        self._timeout = timeout_seconds or settings.terraform_timeout_seconds
        self._max_output_bytes = max_output_bytes or settings.terraform_max_output_bytes

    # ------------------------------------------------------------------ #
    # Public high-level API
    # ------------------------------------------------------------------ #

    def init(self) -> TerraformResult:
        """Run terraform init in the working directory."""
        logger.info("Running terraform init", working_dir=str(self._working_dir))
        result = self._run(["init", "-input=false", "-no-color"])
        if not result.success:
            raise TerraformInitError(
                f"terraform init failed (exit {result.return_code}): {result.stderr[:500]}"
            )
        logger.info("terraform init succeeded")
        return result

    def validate(self) -> TerraformResult:
        """Run terraform validate."""
        logger.info("Running terraform validate")
        result = self._run(["validate", "-no-color"])
        if not result.success:
            raise TerraformValidateError(
                f"terraform validate failed (exit {result.return_code}): {result.stderr[:500]}"
            )
        logger.info("terraform validate succeeded")
        return result

    def plan_refresh_only(self, plan_file: str) -> TerraformResult:
        """
        Run terraform plan -refresh-only and save the plan to plan_file.

        This is the key drift-detection command.  It refreshes remote state
        against actual infrastructure WITHOUT applying any changes.
        """
        logger.info("Running terraform plan -refresh-only", plan_file=plan_file)
        result = self._run(
            [
                "plan",
                "-refresh-only",
                "-input=false",
                "-no-color",
                f"-out={plan_file}",
            ]
        )
        if not result.success:
            raise TerraformPlanError(
                f"terraform plan -refresh-only failed (exit {result.return_code}): {result.stderr[:500]}"
            )
        logger.info("terraform plan -refresh-only succeeded")
        return result

    def show_json(self, plan_file: str) -> dict[str, Any]:
        """
        Run terraform show -json <plan_file> and return the parsed JSON.

        Returns the full plan JSON as a Python dict.
        """
        logger.info("Running terraform show -json", plan_file=plan_file)
        result = self._run(["show", "-json", plan_file])
        if not result.success:
            raise TerraformPlanError(
                f"terraform show -json failed (exit {result.return_code}): {result.stderr[:500]}"
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise TerraformPlanError(
                f"terraform show -json produced invalid JSON: {exc}"
            ) from exc

        logger.info("terraform show -json parsed successfully")
        return data

    def version(self) -> str:
        """Return the installed terraform version string."""
        result = self._run(["version", "-json"])
        if result.success:
            try:
                return json.loads(result.stdout).get("terraform_version", "unknown")
            except (json.JSONDecodeError, KeyError):
                pass
        return "unknown"

    # ------------------------------------------------------------------ #
    # High-level drift-detection workflow
    # ------------------------------------------------------------------ #

    def run_drift_detection(self) -> tuple[dict[str, Any], str]:
        """
        Execute the full read-only drift detection workflow:

        1. terraform init
        2. terraform validate
        3. terraform plan -refresh-only  (saved to temp file)
        4. terraform show -json          (parse plan file)

        Returns:
            (plan_json, terraform_version) tuple.

        Raises:
            TerraformInitError, TerraformValidateError, TerraformPlanError
        """
        self._ensure_terraform_available()

        # Use a temporary directory for the plan file so it is always cleaned up.
        with tempfile.TemporaryDirectory(prefix="driftguard_") as tmpdir:
            plan_file = os.path.join(tmpdir, "drift.tfplan")

            self.init()
            self.validate()
            self.plan_refresh_only(plan_file)
            plan_json = self.show_json(plan_file)

        tf_version = plan_json.get("terraform_version", "unknown")
        return plan_json, tf_version

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _run(self, args: list[str]) -> TerraformResult:
        """
        Execute a terraform sub-command.

        Enforces:
        - Command allowlist check
        - Subprocess timeout
        - Maximum output size
        """
        if not args:
            raise TerraformError("No arguments provided to terraform runner")

        subcommand = args[0].lower()
        self._assert_command_allowed(subcommand)

        full_cmd = [self._terraform_bin, *args]
        logger.debug("Executing terraform", cmd=full_cmd[1:])  # bin path omitted

        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603
                full_cmd,
                cwd=str(self._working_dir),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=self._build_env(),
            )
        except FileNotFoundError as exc:
            raise TerraformNotFoundError(
                f"terraform binary not found: {self._terraform_bin!r}. "
                "Install Terraform CLI and ensure it is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TerraformPlanError(
                f"terraform {subcommand} timed out after {self._timeout}s"
            ) from exc

        duration = time.monotonic() - start

        # Guard against extremely large output (e.g. huge state files)
        stdout_bytes = len(proc.stdout.encode("utf-8", errors="replace"))
        if stdout_bytes > self._max_output_bytes:
            raise TerraformOutputTooLargeError(
                f"terraform {subcommand} output ({stdout_bytes} bytes) exceeds "
                f"maximum allowed size ({self._max_output_bytes} bytes)"
            )

        result = TerraformResult(
            command=full_cmd,
            return_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=round(duration, 3),
        )

        log_extra: dict[str, Any] = {
            "subcommand": subcommand,
            "exit_code": result.return_code,
            "duration_seconds": result.duration_seconds,
        }
        if result.success:
            logger.debug("terraform command succeeded", **log_extra)
        else:
            # Only log stderr snippet — never log full output which may contain state
            logger.warning(
                "terraform command failed",
                stderr_snippet=result.stderr[:300],
                **log_extra,
            )

        return result

    @staticmethod
    def _assert_command_allowed(subcommand: str) -> None:
        """Raise TerraformCommandNotAllowedError if subcommand is not on the allowlist."""
        if subcommand not in _ALLOWED_SUBCOMMANDS:
            raise TerraformCommandNotAllowedError(
                f"terraform {subcommand!r} is not permitted. "
                f"Allowed commands: {sorted(_ALLOWED_SUBCOMMANDS)}. "
                "The application must never execute infrastructure-modifying operations."
            )

    def _ensure_terraform_available(self) -> None:
        """Raise TerraformNotFoundError if terraform binary is not on PATH."""
        import shutil

        if not shutil.which(self._terraform_bin):
            raise TerraformNotFoundError(
                f"terraform binary {self._terraform_bin!r} not found on PATH. "
                "Install Terraform CLI: https://developer.hashicorp.com/terraform/install"
            )

    def _build_env(self) -> dict[str, str]:
        """
        Build the subprocess environment for Terraform.

        Inherits the current process environment, then injects IBM Cloud
        credentials and Stage endpoint overrides from app config so that the
        Terraform IBM provider targets the correct endpoints.

        Stage endpoint variables (set via IBMCLOUD_* in .env):
          IBMCLOUD_API_ENDPOINT                    — https://test.cloud.ibm.com
          IBMCLOUD_IAM_API_ENDPOINT                — https://iam.test.cloud.ibm.com
          IBMCLOUD_IS_NG_API_ENDPOINT              — VPC endpoint with /v1 suffix
          IBMCLOUD_GT_API_ENDPOINT                 — Global Tagging endpoint
          IBMCLOUD_GS_API_ENDPOINT                 — Global Search endpoint
          IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT
          IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT

        Secrets (API key) are never logged.
        """
        env = os.environ.copy()

        # Disable Terraform checkpoint (telemetry) and color for clean JSON output.
        env["CHECKPOINT_DISABLE"] = "1"
        env["TF_IN_AUTOMATION"] = "1"

        # ── IBM Cloud credentials ──────────────────────────────────────
        # The IBM provider authenticates via ibmcloud_api_key in the provider
        # block (populated by TF_VAR_ibmcloud_api_key).  We also set
        # IBMCLOUD_API_KEY so the provider picks it up as a fallback.
        if settings.ibmcloud_api_key:
            env.setdefault("TF_VAR_ibmcloud_api_key", settings.ibmcloud_api_key)
            env.setdefault("IBMCLOUD_API_KEY", settings.ibmcloud_api_key)

        # ── IBM Cloud region ───────────────────────────────────────────
        if settings.ibmcloud_region:
            env.setdefault("IBMCLOUD_REGION", settings.ibmcloud_region)

        # ── Stage / Dev endpoint overrides ────────────────────────────
        # Each variable is only injected if configured in settings AND not
        # already present in the process environment (env vars win).
        _endpoint_map = [
            ("IBMCLOUD_API_ENDPOINT",                    settings.ibmcloud_api_endpoint),
            ("IBMCLOUD_IAM_API_ENDPOINT",                settings.ibmcloud_iam_api_endpoint),
            ("IBMCLOUD_IS_NG_API_ENDPOINT",              settings.ibmcloud_is_ng_api_endpoint),
            ("IBMCLOUD_GT_API_ENDPOINT",                 settings.ibmcloud_gt_api_endpoint),
            ("IBMCLOUD_GS_API_ENDPOINT",                 settings.ibmcloud_gs_api_endpoint),
            ("IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT", settings.ibmcloud_resource_controller_api_endpoint),
            ("IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT", settings.ibmcloud_resource_management_api_endpoint),
        ]
        for env_key, value in _endpoint_map:
            if value:
                env.setdefault(env_key, value)

        return env
