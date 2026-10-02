# ============================================================
# IBM Cloud Terraform DriftGuard AI — Demo Infrastructure
#
# Creates minimal IBM Cloud VPC resources suitable for a Stage/Dev account.
# Cost: The base VPC and security groups incur minimal to no charge.
#
# DEMO PURPOSE:
#   1. Apply this configuration with allowed_cidr = "10.0.0.0/16"
#   2. Manually change the security group rule in the IBM Cloud console
#      to allow traffic from "0.0.0.0/0"
#   3. Run terraform plan -refresh-only to detect the drift
#   4. The DriftGuard AI system will analyze and notify via Slack
# ============================================================

# Data source — look up the resource group
data "ibm_resource_group" "rg" {
  name = var.resource_group
}

# ── VPC ──────────────────────────────────────────────────────────────
resource "ibm_is_vpc" "demo" {
  name           = "${var.prefix}-vpc"
  resource_group = data.ibm_resource_group.rg.id

  tags = [
    "project:driftguard-demo",
    "environment:stage",
    "managed-by:terraform",
  ]
}

# ── Subnet ───────────────────────────────────────────────────────────
resource "ibm_is_subnet" "demo" {
  name                     = "${var.prefix}-subnet"
  vpc                      = ibm_is_vpc.demo.id
  zone                     = var.zone
  resource_group           = data.ibm_resource_group.rg.id
  total_ipv4_address_count = 256

  tags = [
    "project:driftguard-demo",
    "environment:stage",
    "managed-by:terraform",
  ]
}

# ── Security group ───────────────────────────────────────────────────
resource "ibm_is_security_group" "app" {
  name           = "${var.prefix}-app-sg"
  vpc            = ibm_is_vpc.demo.id
  resource_group = data.ibm_resource_group.rg.id

  tags = [
    "project:driftguard-demo",
    "environment:stage",
    "managed-by:terraform",
  ]
}

# ── Security group rules ─────────────────────────────────────────────

# HTTPS inbound — THIS IS THE RULE USED TO DEMONSTRATE DRIFT
#
# Terraform expects:
#   remote = var.allowed_cidr  (default: "10.0.0.0/16")
#
# To simulate drift, manually change this in the IBM Cloud console to:
#   remote = "0.0.0.0/0"
#
# Then run: terraform plan -refresh-only
# DriftGuard will detect and classify the change as CRITICAL.
resource "ibm_is_security_group_rule" "app_https" {
  group     = ibm_is_security_group.app.id
  direction = "inbound"
  remote    = var.allowed_cidr
  protocol  = "tcp"
  port_min  = 443
  port_max  = 443
}

# Allow all outbound traffic (standard permissive egress for demo purposes)
resource "ibm_is_security_group_rule" "app_egress_all" {
  group     = ibm_is_security_group.app.id
  direction = "outbound"
  remote    = "0.0.0.0/0"
  protocol  = "any"
}
