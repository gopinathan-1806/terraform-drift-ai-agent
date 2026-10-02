#!/usr/bin/env bash
# =============================================================================
# set_stage_env.sh — Export IBM Cloud Stage endpoint environment variables
#
# Usage:
#   source scripts/set_stage_env.sh
#
# This script sets the environment variables required by the IBM Terraform
# provider to route all API calls to IBM Cloud Stage endpoints.
# It must be SOURCED (not executed) so the exports persist in your shell.
#
# Your API key must already be in the environment or .env file:
#   export TF_VAR_ibmcloud_api_key=<your-stage-api-key>
# =============================================================================

set -a

# ── IBM Cloud Stage API endpoints ─────────────────────────────────────────────
IBMCLOUD_API_ENDPOINT="https://test.cloud.ibm.com"
IBMCLOUD_IAM_API_ENDPOINT="https://iam.test.cloud.ibm.com"

# VPC / IS (Next Gen) — Stage regional endpoint
IBMCLOUD_IS_NG_API_ENDPOINT="https://us-south-stage01.iaasdev.cloud.ibm.com/v1"

# Global Tagging & Search
IBMCLOUD_GT_API_ENDPOINT="https://tags.global-search-tagging.test.cloud.ibm.com"
IBMCLOUD_GS_API_ENDPOINT="https://api.global-search-tagging.test.cloud.ibm.com"

# Resource Controller & Management
IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"
IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"

set +a

echo "✅ IBM Cloud Stage environment variables set."
echo "   API endpoint : $IBMCLOUD_API_ENDPOINT"
echo "   IAM endpoint : $IBMCLOUD_IAM_API_ENDPOINT"
echo "   VPC endpoint : $IBMCLOUD_IS_NG_API_ENDPOINT"
echo ""
echo "   Now run: terraform plan"
