#!/usr/bin/env bash
# ============================================================
# IBM Cloud Terraform DriftGuard AI — Drift Check Script
#
# Runs a single drift detection check and prints the result.
# Uses the FastAPI HTTP API.
#
# Usage:
#   ./scripts/run_drift_check.sh [API_BASE_URL]
#
# Default API_BASE_URL: http://127.0.0.1:8080
# ============================================================

set -euo pipefail

API_BASE="${1:-http://127.0.0.1:8080}"

echo ""
echo "=========================================="
echo " IBM Cloud Terraform DriftGuard AI"
echo " Running drift detection check..."
echo "=========================================="
echo ""

# ── Health check ───────────────────────────────────────────
echo "→ Checking application health..."
HEALTH=$(curl -sf "${API_BASE}/health" || echo '{"status":"unreachable"}')
echo "   Health: ${HEALTH}"
echo ""

# ── Trigger drift check ─────────────────────────────────────
echo "→ Triggering drift check..."
RESULT=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    "${API_BASE}/api/drift/check" || echo '{"error":"request failed"}')

echo "   Result: ${RESULT}"
echo ""

# ── Check latest drift report ──────────────────────────────
echo "→ Fetching latest drift report..."
REPORT=$(curl -sf "${API_BASE}/api/drift" || echo '{"error":"request failed"}')
echo "   Report: ${REPORT}" | python3 -m json.tool 2>/dev/null || echo "   ${REPORT}"
echo ""

echo "=========================================="
echo " Drift check complete."
echo "=========================================="
