output "vpc_id" {
  description = "ID of the demo VPC"
  value       = ibm_is_vpc.demo.id
}

output "vpc_name" {
  description = "Name of the demo VPC"
  value       = ibm_is_vpc.demo.name
}

output "subnet_id" {
  description = "ID of the demo subnet"
  value       = ibm_is_subnet.demo.id
}

output "security_group_id" {
  description = "ID of the application security group"
  value       = ibm_is_security_group.app.id
}

output "security_group_name" {
  description = "Name of the application security group"
  value       = ibm_is_security_group.app.name
}

output "https_rule_id" {
  description = "ID of the HTTPS inbound security group rule (used for drift demo)"
  value       = ibm_is_security_group_rule.app_https.rule_id
}

output "drift_demo_instructions" {
  description = "Instructions for simulating drift"
  value = <<-EOT
    ==========================================================
    DRIFT DEMO INSTRUCTIONS
    ==========================================================

    1. This Terraform configuration has been applied.

    2. The security group rule 'app_https' allows HTTPS inbound from:
       ${var.allowed_cidr}

    3. To SIMULATE DRIFT:
       - Go to IBM Cloud Console → VPC → Security Groups
       - Find security group: ${ibm_is_security_group.app.name}
       - Edit the rule for TCP 443
       - Change the Source CIDR from ${var.allowed_cidr} to 0.0.0.0/0
       - Save the change

    4. To DETECT DRIFT:
       python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
       curl -X POST http://127.0.0.1:8080/api/drift/check

       OR run directly:
       ./scripts/run_drift_check.sh

    5. Expected result:
       - DriftGuard detects: remote changed from ${var.allowed_cidr} to 0.0.0.0/0
       - Policy engine classifies as CRITICAL
       - Slack notification sent

    6. To RESOLVE DRIFT:
       terraform apply

    7. Run drift check again → RESOLVED notification
    ==========================================================
  EOT
}
