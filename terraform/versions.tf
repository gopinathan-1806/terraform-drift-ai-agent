terraform {
  required_version = ">= 1.5.0"

  required_providers {
    ibm = {
      source  = "IBM-Cloud/ibm"
      version = ">= 1.71.0"
    }
  }
}

# IBM Cloud provider configuration.
#
# Stage account authentication is handled entirely through environment variables.
# These env vars redirect each IBM Cloud service to the Stage endpoints so that
# the Stage IAM token (kid: 20191001) is validated by Stage IAM, not production.
#
# Required before running terraform plan/apply:
#
#   export TF_VAR_ibmcloud_api_key=<your-stage-api-key>
#   export IBMCLOUD_API_ENDPOINT="https://test.cloud.ibm.com"
#   export IBMCLOUD_IAM_API_ENDPOINT="https://iam.test.cloud.ibm.com"
#   export IBMCLOUD_IS_NG_API_ENDPOINT="https://us-south-stage01.iaasdev.cloud.ibm.com/v1"
#   export IBMCLOUD_GT_API_ENDPOINT="https://tags.global-search-tagging.test.cloud.ibm.com"
#   export IBMCLOUD_GS_API_ENDPOINT="https://api.global-search-tagging.test.cloud.ibm.com"
#   export IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"
#   export IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"
#
# Or use the helper script:
#   source scripts/set_stage_env.sh && terraform plan
#
provider "ibm" {
  ibmcloud_api_key = var.ibmcloud_api_key
  region           = var.region
  ibmcloud_timeout = 60
}
