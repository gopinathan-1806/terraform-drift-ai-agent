variable "region" {
  description = "IBM Cloud region"
  type        = string
  default     = "us-south"
}

variable "resource_group" {
  description = "IBM Cloud resource group name"
  type        = string
  default     = "Default"
}

variable "prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "driftguard-demo"
}

variable "allowed_cidr" {
  description = "Allowed source CIDR for HTTPS traffic (change to 0.0.0.0/0 to simulate drift)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "zone" {
  description = "IBM Cloud VPC zone"
  type        = string
  default     = "us-south-1"
}

# ── IBM Cloud Stage account ──────────────────────────────────────────
#
# Set via environment variable (never put in terraform.tfvars and never commit):
#   export TF_VAR_ibmcloud_api_key=<your-stage-api-key>
#
# stage_endpoints.json redirects IBMCLOUD_IAM_API_ENDPOINT to Stage IAM so
# the API key is exchanged against iam.test.cloud.ibm.com, not production.

variable "ibmcloud_api_key" {
  description = "IBM Cloud API key for Stage account. Set via TF_VAR_ibmcloud_api_key — never hard-code."
  type        = string
  sensitive   = true
}
