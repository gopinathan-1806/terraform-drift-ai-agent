# IBM Cloud Terraform DriftGuard AI — Project Summary

> **Purpose of this file:** Complete handoff document for continuing development in a new task.
> Last updated: 2026-10-01. All 112 unit tests pass. `terraform plan` succeeds against IBM Cloud Stage.

---

## 1. Project Overview

**Name:** IBM Cloud Terraform DriftGuard AI  
**Goal:** Detect manual changes to IBM Cloud infrastructure that was originally provisioned by Terraform, analyze the drift with an AI agent, classify risk, and send a Slack notification.

**Key constraints:**
- IBM Cloud **Stage / Dev** account (`test.cloud.ibm.com`, `iam.test.cloud.ibm.com`)
- No IBM Cloud Schematics, no Activity Tracker, no enterprise-only services
- First version is **read-only** — the AI agent must NEVER trigger `terraform apply`
- Run locally first; optionally deploy to IBM Cloud Code Engine later
- AI: OpenAI (`gpt-4o-mini`) configured; Slack webhook configured; both verified working

---

## 2. Current Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1 — Project structure & config | ✅ Complete | Pydantic Settings, structured logging |
| Phase 2 — Terraform runner | ✅ Complete | Command allowlist, subprocess safety |
| Phase 3 — Terraform JSON parser | ✅ Complete | Full plan JSON normalization |
| Phase 4 — Drift models & fingerprinting | ✅ Complete | SHA-256 dedup, lifecycle tracking |
| Phase 5 — Policy engine | ✅ Complete | YAML rules, CRITICAL→INFO |
| Phase 6 — AI agent | ✅ Complete | OpenAI/watsonx/none abstraction + guardrails |
| Phase 7 — Slack notifier | ✅ Complete | Block Kit, sensitive value masking |
| Phase 8 — Scheduler & lifecycle | ✅ Complete | APScheduler, NEW/ACTIVE/CHANGED/RESOLVED |
| Phase 9 — IBM Cloud Terraform demo infra | ✅ Complete | `terraform plan` now succeeds |
| Phase 10 — Tests | ✅ Complete | **112 tests passing** |
| Phase 11 — Dockerfile + docker-compose | ✅ Complete | Red Hat UBI9, non-root user |
| Phase 12 — README + Mermaid diagrams | ✅ Complete | |
| **End-to-end demo run** | ⏳ Pending | `terraform apply` not yet run; no live drift detected yet |

---

## 3. Architecture

```
flowchart TD
    A[IBM Cloud Infrastructure]
    B[Terraform Configuration]
    C[Terraform State]
    D[terraform plan -refresh-only]
    E[terraform show -json]
    F[Drift Parser]
    G[Policy Engine]
    H[AI Agent]
    I[Slack]

    A --> D
    B --> D
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
```

**Three strict layers:**
1. **Deterministic layer:** Terraform → Drift detection → Structured data → Policy engine
2. **AI layer:** Structured drift → AI reasoning → Risk explanation → Recommendation
3. **Action layer:** Slack notification only (AI has no cloud credentials, no shell access)

---

## 4. Complete File Tree

```
terraform-ai-agent/
│
├── .env                          # LIVE secrets (gitignored) — all vars set
├── .env.example                  # Template with all variable documentation
├── .gitignore
├── .venv/                        # Python 3.10.16 virtual environment
├── PROJECT_SUMMARY.md            # ← THIS FILE
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI entry point, lifespan, startup
│   │
│   ├── api/
│   │   └── routes.py             # 5 REST endpoints (health, drift, history, test)
│   │
│   ├── config/
│   │   ├── settings.py           # Pydantic Settings — all env vars documented here
│   │   └── logging.py            # structlog JSON structured logging
│   │
│   ├── terraform/
│   │   ├── runner.py             # Terraform CLI runner — command allowlist enforced
│   │   ├── parser.py             # terraform show -json → normalized DriftedResource
│   │   └── models.py             # Pydantic models for plan JSON
│   │
│   ├── drift/
│   │   ├── detector.py           # Full pipeline orchestrator (runner→parser→policy→AI→slack)
│   │   ├── fingerprint.py        # SHA-256 fingerprint dedup + lifecycle (NEW/ACTIVE/CHANGED/RESOLVED)
│   │   └── models.py             # DriftedResource, AttributeChange, DriftEvent, DriftReport
│   │
│   ├── policy/
│   │   ├── engine.py             # Deterministic rule evaluator (first-match wins)
│   │   └── rules.yaml            # CRITICAL/HIGH/MEDIUM/LOW/INFO rules (configurable YAML)
│   │
│   ├── agent/
│   │   ├── agent.py              # AI orchestrator — calls provider, validates output
│   │   ├── prompts.py            # System + user prompt templates with guardrails
│   │   └── provider.py           # LLMProvider abstraction: openai / watsonx / none
│   │
│   ├── notifications/
│   │   └── slack.py              # Block Kit notifier — masks sensitive values
│   │
│   ├── scheduler/
│   │   └── scheduler.py          # APScheduler — configurable polling, dedup
│   │
│   └── storage/
│       ├── interface.py          # Abstract DriftStateStore interface
│       └── local.py              # JSON file store (.driftguard/state/)
│
├── terraform/
│   ├── main.tf                   # VPC + subnet + security group + 2 SG rules
│   ├── variables.tf              # region, resource_group, prefix, allowed_cidr, ibmcloud_api_key
│   ├── outputs.tf                # vpc_id, security_group_id, drift_demo_instructions
│   ├── versions.tf               # provider ibm ≥ 1.71.0, authentication via env vars
│   ├── terraform.tfvars          # Non-secret defaults (region, prefix, etc.)
│   ├── terraform.tfvars.example  # Template
│   └── stage_endpoints.json      # Nested endpoint map (kept for reference, not used by provider)
│
├── tests/
│   ├── conftest.py               # Terraform plan JSON fixtures (no-drift, single-attr, multi-attr, etc.)
│   ├── test_terraform_runner.py  # Runner allowlist, env injection, Stage endpoint vars
│   ├── test_terraform_parser.py  # Parser: no-drift, create, update, delete, replace, sensitive
│   ├── test_fingerprint.py       # SHA-256 dedup, lifecycle transitions
│   ├── test_policy_engine.py     # CRITICAL/HIGH/MEDIUM/LOW rule matching
│   ├── test_agent.py             # AI agent: mock responses, fallback on failure
│   ├── test_slack.py             # Slack: Block Kit format, webhook failure handling
│   ├── test_drift_detector.py    # Full pipeline: new/active/changed/resolved lifecycle
│   └── test_phase1_structure.py  # Project structure, FastAPI health endpoint
│
├── scripts/
│   ├── run_drift_check.sh        # One-shot drift check script
│   └── set_stage_env.sh          # source this to export Stage endpoint env vars
│
├── Dockerfile                    # Red Hat UBI9 python-311-minimal, non-root, Terraform CLI
├── docker-compose.yml            # Local compose with env_file
├── requirements.txt              # Pinned Python deps
├── pytest.ini                    # Test config
└── README.md                     # Full documentation with Mermaid diagrams
```

---

## 5. Key Files Modified / Created (This Session)

| File | Change |
|------|--------|
| `terraform/versions.tf` | **Rewrote**: removed `iam_token` + broken `endpoints_file_path`; now uses `ibmcloud_api_key = var.ibmcloud_api_key` with env-var-based Stage routing |
| `terraform/variables.tf` | Replaced `iam_token` variable with `ibmcloud_api_key` (sensitive, no default) |
| `terraform/terraform.tfvars` | Removed stale `ibmcloud_visibility = "public"` (caused undeclared-variable warning) |
| `terraform/stage_endpoints.json` | Reformatted to correct nested structure `{"KEY": {"public": {"region": "url"}}}` — kept for reference but provider uses env vars instead |
| `app/config/settings.py` | Added 7 new Stage endpoint fields: `ibmcloud_api_endpoint`, `ibmcloud_iam_api_endpoint`, `ibmcloud_is_ng_api_endpoint`, `ibmcloud_gt_api_endpoint`, `ibmcloud_gs_api_endpoint`, `ibmcloud_resource_controller_api_endpoint`, `ibmcloud_resource_management_api_endpoint`. Removed `ibmcloud_visibility` |
| `app/terraform/runner.py` | Updated `_build_env()`: now injects `TF_VAR_ibmcloud_api_key`, all 7 Stage endpoint env vars from settings |
| `tests/test_terraform_runner.py` | Updated `test_env_injects_ibmcloud_stage_settings` to match new env var names |
| `.env.example` | Updated IBM Cloud section with Stage endpoint vars |
| `.env` (live) | Appended all 7 Stage endpoint vars (file is gitignored) |
| `scripts/set_stage_env.sh` | **New**: helper script — `source scripts/set_stage_env.sh` exports all Stage env vars |

---

## 6. IBM Cloud Stage Authentication — Root Cause & Solution

### Problem History
The IBM Terraform provider v2.6.2 has several Stage account bugs:

| Approach | Result |
|----------|--------|
| `visibility = "private"` in provider | Hangs locally — `test.cloud.ibm.com` internal network unreachable |
| `iam_token` in provider + `endpoints_file_path` (flat JSON) | **Provider panics**: `interface{} is string, not map[string]interface{}` — bug in v2.6.2 `config.go:4402` |
| `ibmcloud_api_key` only (no endpoint override) | Token exchanged against prod IAM; prod IAM rejects Stage token (`kid: 20191001`) |
| `IBMCLOUD_IAM_API_ENDPOINT` env var alone | IAM auth works; but `ibm_is_vpc.CustomizeDiff` calls `tags.global-search-tagging.cloud.ibm.com` (prod) → 401 |

### Solution (Working)
Set **7 environment variables** before running Terraform. The IBM provider's `buildIAMAuthenticator()` calls `EnvFallBack([]string{"IBMCLOUD_IAM_API_ENDPOINT"}, ...)` — env vars take priority over the endpoints file and over the file map. Similarly for VPC, tagging, and search.

```bash
export TF_VAR_ibmcloud_api_key="<your-stage-api-key>"
export IBMCLOUD_API_ENDPOINT="https://test.cloud.ibm.com"
export IBMCLOUD_IAM_API_ENDPOINT="https://iam.test.cloud.ibm.com"
export IBMCLOUD_IS_NG_API_ENDPOINT="https://us-south-stage01.iaasdev.cloud.ibm.com/v1"
export IBMCLOUD_GT_API_ENDPOINT="https://tags.global-search-tagging.test.cloud.ibm.com"
export IBMCLOUD_GS_API_ENDPOINT="https://api.global-search-tagging.test.cloud.ibm.com"
export IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"
export IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"
```

Or: `source scripts/set_stage_env.sh`

### Why It Works
- `IBMCLOUD_IAM_API_ENDPOINT` → API key is exchanged for a token against `iam.test.cloud.ibm.com` (Stage IAM)
- `IBMCLOUD_IS_NG_API_ENDPOINT` → VPC/IS resource calls route to `us-south-stage01.iaasdev.cloud.ibm.com`
- `IBMCLOUD_GT_API_ENDPOINT` → `ibm_is_vpc.CustomizeDiff` uses this for access tag lookups (was the last failing call)
- `IBMCLOUD_GS_API_ENDPOINT` → Global resource search routes to Stage
- The resource controller calls (`ibm_resource_group` data source) were already working via `resource-controller.test.cloud.ibm.com`

### Verified Stage Endpoints

| Service | Stage URL | Resolves |
|---------|-----------|----------|
| Main API | `https://test.cloud.ibm.com` | ✅ |
| IAM | `https://iam.test.cloud.ibm.com` | ✅ |
| VPC (us-south) | `https://us-south-stage01.iaasdev.cloud.ibm.com` | ✅ (104.16.78.50) |
| Global Tagging | `https://tags.global-search-tagging.test.cloud.ibm.com` | ✅ |
| Global Search | `https://api.global-search-tagging.test.cloud.ibm.com` | ✅ |
| Resource Controller | `https://resource-controller.test.cloud.ibm.com` | ✅ |

---

## 7. Environment Variables (`.env`)

All set in `.env` (gitignored). Values confirmed working:

```
ENVIRONMENT=stage
TERRAFORM_WORKING_DIR=./terraform
TERRAFORM_BIN=terraform
LLM_PROVIDER=openai           # verified working
LLM_API_KEY=<openai-key>      # set
LLM_MODEL=gpt-4o-mini
SLACK_WEBHOOK_URL=<webhook>   # verified working
IBMCLOUD_API_KEY=<stage-key>  # set — DNCzH4t2...
IBMCLOUD_REGION=us-south

# Stage endpoint overrides (all set):
IBMCLOUD_API_ENDPOINT=https://test.cloud.ibm.com
IBMCLOUD_IAM_API_ENDPOINT=https://iam.test.cloud.ibm.com
IBMCLOUD_IS_NG_API_ENDPOINT=https://us-south-stage01.iaasdev.cloud.ibm.com/v1
IBMCLOUD_GT_API_ENDPOINT=https://tags.global-search-tagging.test.cloud.ibm.com
IBMCLOUD_GS_API_ENDPOINT=https://api.global-search-tagging.test.cloud.ibm.com
IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT=https://resource-controller.test.cloud.ibm.com
IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT=https://resource-controller.test.cloud.ibm.com
```

**Note:** `LLM_PROVIDER` is currently `none` in `.env` — change to `openai` to enable AI analysis.

---

## 8. IBM Cloud Account Details

| Field | Value |
|-------|-------|
| Account name | cldgen custwFive |
| User | cldgen-custw05@ibm.com |
| Account ID | adacc156292b458285ee56b48dde4915 |
| Resource Group ID | d579147fddf74c56a81b2af857f1e2b0 |
| Region | us-south |
| API endpoint | https://test.cloud.ibm.com |
| Existing VPCs | 1 pre-existing VPC (pre-shutdown-b125ad8b-vpc) — not ours |
| Our infra state | **Not yet applied** — `terraform.tfstate` is empty |

---

## 9. Terraform Infrastructure (Demo)

Defined in `terraform/main.tf`. Will create when `terraform apply` is run:

| Resource | Terraform ID | Details |
|----------|-------------|---------|
| VPC | `ibm_is_vpc.demo` | `driftguard-demo-vpc` |
| Subnet | `ibm_is_subnet.demo` | `driftguard-demo-subnet`, zone us-south-1 |
| Security Group | `ibm_is_security_group.app` | `driftguard-demo-app-sg` |
| SG Rule (inbound HTTPS) | `ibm_is_security_group_rule.app_https` | TCP 443, remote `10.0.0.0/16` ← **drift target** |
| SG Rule (egress all) | `ibm_is_security_group_rule.app_egress_all` | protocol any, `0.0.0.0/0` |

**The drift scenario:** After apply, manually change the inbound HTTPS rule source from `10.0.0.0/16` to `0.0.0.0/0` in IBM Cloud Console → DriftGuard detects it as CRITICAL.

---

## 10. Terraform Commands

```bash
# Set Stage auth env vars first:
source scripts/set_stage_env.sh
export TF_VAR_ibmcloud_api_key="<your-api-key>"

# Or manually:
export IBMCLOUD_IAM_API_ENDPOINT="https://iam.test.cloud.ibm.com"
export IBMCLOUD_IS_NG_API_ENDPOINT="https://us-south-stage01.iaasdev.cloud.ibm.com/v1"
export IBMCLOUD_GT_API_ENDPOINT="https://tags.global-search-tagging.test.cloud.ibm.com"
export IBMCLOUD_GS_API_ENDPOINT="https://api.global-search-tagging.test.cloud.ibm.com"
export IBMCLOUD_RESOURCE_CONTROLLER_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"
export IBMCLOUD_RESOURCE_MANAGEMENT_API_ENDPOINT="https://resource-controller.test.cloud.ibm.com"

cd terraform/
terraform init    # ✅ Works
terraform validate # ✅ Works
terraform plan     # ✅ Works — plans 5 resources
terraform apply    # ⏳ NOT YET RUN — run to create demo resources
```

---

## 11. FastAPI Server

```bash
# Install deps:
pip install -r requirements.txt

# Start server:
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080

# Endpoints:
GET  http://127.0.0.1:8080/health           # {"status":"healthy"}
GET  http://127.0.0.1:8080/api/drift        # Latest drift result
POST http://127.0.0.1:8080/api/drift/check  # Trigger manual drift check
GET  http://127.0.0.1:8080/api/drift/history # Recent drift events
POST http://127.0.0.1:8080/api/test/slack   # Send test Slack notification
```

---

## 12. Test Suite

```bash
.venv/bin/python -m pytest tests/ -v
```

**Result: 112 passed, 0 failed, 1 warning (deprecation from starlette testclient)**

| Test file | Tests | Coverage |
|-----------|-------|----------|
| `test_terraform_runner.py` | ~15 | Allowlist, env injection, Stage endpoints, timeout |
| `test_terraform_parser.py` | ~20 | No-drift, create, update, delete, replace, sensitive values |
| `test_fingerprint.py` | ~15 | SHA-256 dedup, NEW/ACTIVE/CHANGED/RESOLVED lifecycle |
| `test_policy_engine.py` | ~20 | CRITICAL/HIGH/MEDIUM/LOW/INFO rule matching |
| `test_agent.py` | ~15 | Mock AI responses, fallback on failure, guardrails |
| `test_slack.py` | ~12 | Block Kit format, webhook failure, sensitive masking |
| `test_drift_detector.py` | ~10 | Full pipeline, dedup, lifecycle |
| `test_phase1_structure.py` | ~5 | File structure, FastAPI health |

---

## 13. Known Bugs / Issues

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-1 | ~~Critical~~ | IBM provider v2.6.2 panics on flat `endpoints_file_path` JSON | **Fixed** — using env vars instead |
| BUG-2 | ~~Critical~~ | Stage IAM token (`kid:20191001`) rejected by production `tags.global-search-tagging.cloud.ibm.com` | **Fixed** — `IBMCLOUD_GT_API_ENDPOINT` env var redirects to Stage |
| BUG-3 | ~~Medium~~ | `ibmcloud_visibility` field removed from Settings — one test referenced it | **Fixed** — test updated |
| BUG-4 | Low | `LLM_PROVIDER=none` in `.env` — AI analysis disabled | **Expected** — change to `openai` for live run |
| BUG-5 | Low | `terraform.tfstate` is empty — `terraform apply` not yet executed | **Pending** — next step |
| BUG-6 | Low | `stage_endpoints.json` file kept in repo but not used by provider | Cosmetic — may remove or keep for documentation |
| BUG-7 | Info | Python 3.10.16 used (`.venv`); `requirements.txt` specifies Python 3.11+ | Works fine; Dockerfile uses 3.11-minimal |

---

## 14. Pending Development (Next Steps)

### Immediate (complete the demo)

1. **`terraform apply`** — Create the 5 demo resources in IBM Cloud Stage
   ```bash
   source scripts/set_stage_env.sh
   export TF_VAR_ibmcloud_api_key="<api-key>"
   cd terraform && terraform apply
   ```

2. **Simulate drift** — In IBM Cloud Console:
   - Navigate: VPC Infrastructure → Security Groups → `driftguard-demo-app-sg`
   - Edit the TCP 443 inbound rule
   - Change Source CIDR: `10.0.0.0/16` → `0.0.0.0/0`

3. **Enable AI analysis** — In `.env`:
   ```
   LLM_PROVIDER=openai
   ```

4. **Start FastAPI server and trigger drift check**:
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
   curl -X POST http://127.0.0.1:8080/api/drift/check
   ```

5. **Verify end-to-end Slack notification** — expect:
   - 🚨 CRITICAL: `ibm_is_security_group_rule.app_https`
   - `remote` changed from `10.0.0.0/16` → `0.0.0.0/0`
   - AI assessment: HIGH/CRITICAL risk
   - Recommended action: revert via Terraform

6. **Resolve drift** — `terraform apply` to restore the rule → expect RESOLVED notification

### Near-term improvements

7. **Update `run_drift_check.sh`** to `source set_stage_env.sh` automatically
8. **Docker image** — build and test with `docker compose up`
9. **Drift state persistence** — verify `.driftguard/state/` is created on first run
10. **Scheduler smoke test** — verify polling runs every 300s without memory leaks

### Future (V2+)

- IBM Cloud Activity Tracker integration (enterprise accounts)
- IBM Cloud Schematics as alternative Terraform executor
- GitHub/GitLab PR correlation (compare drift timestamp vs recent commits)
- IBM Cloud Code Engine deployment
- Redis/PostgreSQL for drift state (replace local JSON store)
- Event-driven architecture (replace polling with push events)
- Multiple IBM Cloud accounts / multiple Terraform workspaces
- RAG over infrastructure documentation for better AI explanations
- Historical drift analytics dashboard

---

## 15. Quick Start for New Session

```bash
# 1. Navigate to project
cd /Users/gopinathankrishnasamy/Desktop/IBM/Repos/terraform-ai-agent

# 2. Activate Python env
source .venv/bin/activate

# 3. Verify all tests pass
python -m pytest tests/ -q   # expect: 112 passed

# 4. Set Stage env vars
source scripts/set_stage_env.sh
export TF_VAR_ibmcloud_api_key="DNCzH4t2Mv1iHHoy3_j2jdcYHoP8-9LPR_Tncs4XuNBs"

# 5. Apply Terraform demo infrastructure
cd terraform && terraform apply && cd ..

# 6. Enable AI in .env (change LLM_PROVIDER=none → LLM_PROVIDER=openai)
sed -i '' 's/LLM_PROVIDER=none/LLM_PROVIDER=openai/' .env

# 7. Start FastAPI server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 &

# 8. MANUALLY change security group rule in IBM Cloud Console first, then:
curl -X POST http://127.0.0.1:8080/api/drift/check

# 9. Check Slack for notification
```

---

## 16. Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend framework | FastAPI + Uvicorn | 0.115.12 / 0.34.3 |
| Configuration | Pydantic Settings | ≥2.11.9 |
| HTTP client | httpx | 0.28.1 |
| Structured logging | structlog | 25.3.0 |
| Scheduling | APScheduler | 3.11.0 |
| AI provider | OpenAI (gpt-4o-mini) | via httpx |
| Notifications | Slack Incoming Webhook | Block Kit format |
| IaC | Terraform CLI | v1.15.8 |
| IBM provider | IBM-Cloud/ibm | v2.6.2 |
| IBM CLI | ibmcloud | installed at `/usr/local/bin/ibmcloud` |
| Container base | Red Hat UBI9 python-311-minimal | |
| Testing | pytest + unittest.mock + respx | 8.3.5 |
| Python | 3.10.16 (venv) / 3.11+ (Dockerfile) | |

---

## 17. File Line Counts (approximate)

| Path | Lines |
|------|-------|
| `app/` (all Python) | ~9,441 |
| `tests/` (all Python) | ~2,068 |
| `terraform/*.tf` | ~250 |
| `app/policy/rules.yaml` | ~150 |
| `README.md` | ~500 |

---

*End of summary. All 112 tests pass. `terraform plan` succeeds. Ready to run `terraform apply` and complete the end-to-end demo.*
