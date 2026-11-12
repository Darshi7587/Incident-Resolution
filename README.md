# Autonomous IT Incident Resolution

**Academic Capstone Project — Phase 1 Prototype**  
*Innovation Center, Center for Artificial Intelligence & Machine Learning*

An agentic AI prototype built exclusively with **free, open-source, locally executable technologies** and **isolated simulated IT infrastructure**. The system automates enterprise IT incident triage, metric/log correlation, root cause hypothesis generation, RAG runbook retrieval, controlled remediation planning, human-in-the-loop safety approvals, recovery validation, rollback/escalation, and auditable reporting.

> **Academic Simulation Notice:** All infrastructure metrics, system logs, services (`application-server`, `storage-service`, `payment-api`, `db-server`), and remediation executions operate strictly inside an isolated local simulator (`SimulatedInfrastructure`). No real enterprise servers, production databases, or host user files are modified.

---

## 1. Architecture Overview

```text
Incident Simulator (3 Scenarios + Baseline)
        │
        ▼
Agent 1: Orchestrator Agent (LangGraph StateGraph)
        │
        ├──► Agent 2: Monitoring Agent (Configurable Thresholds)
        ├──► Agent 3: Log Analysis Agent (Regex Parsing & Signatures)
        ├──► Agent 4: Root Cause Analysis Agent (Ollama LLM + Deterministic Fallback)
        ├──► Agent 5: RAG Knowledge Agent (ChromaDB + sentence-transformers)
        ├──► Agent 6: Remediation Planning Agent + Risk Engine (Allowlist + Policy)
        │        │
        │        ├── LOW RISK (auto-approved by policy) ──────────┐
        │        └── MEDIUM / HIGH RISK (persistent PENDING gate) │
        │                 │                                       │
        │        [Human Approve / Reject in Dashboard]            │
        │            ├── REJECT ─► Block Execution & Escalate     │
        │            └── APPROVE ───────────────────────────────┐ │
        │                                                       ▼ ▼
        │                                       Controlled Remediation Executor
        │                                                       │
        │                                                       ▼
        └──► Agent 7: Validation Agent (Before/After Check + Rollback on Failure)
                                                                │
                                                                ▼
                                   SQLite Audit Trail + Incident Report + Streamlit UI
```

---

## 2. Technology Stack (100% Free & Local)

| Layer | Technology |
|---|---|
| **Backend API** | Python 3.12/3.13, FastAPI, Uvicorn, Pydantic |
| **Multi-Agent Orchestration** | LangGraph (`StateGraph`), specialized Python agents |
| **Local LLM** | Ollama (`llama3.1:latest` / `gemma3:1b`) with transparent deterministic fallback |
| **RAG & Embeddings** | ChromaDB (`PersistentClient`), `sentence-transformers` (`all-MiniLM-L6-v2`), local Markdown runbooks |
| **Database & Audit Trail** | SQLite via SQLAlchemy ORM (9 tables) |
| **Frontend Dashboard** | Streamlit + Plotly (dark-themed operations console) |
| **Containerization** | Docker & Docker Compose |
| **Testing** | Pytest + `httpx` |

---

## 3. Seven Specialized Agents

1. **Orchestrator Agent** ([`backend/agents/orchestrator.py`](backend/agents/orchestrator.py))  
   Initializes shared `IncidentState`, runs the LangGraph `StateGraph` ([`backend/workflows/incident_workflow.py`](backend/workflows/incident_workflow.py)), handles pause/resume across human approvals, and logs execution events.
2. **Monitoring Agent** ([`backend/agents/monitoring_agent.py`](backend/agents/monitoring_agent.py))  
   Evaluates CPU, memory, disk, service statuses, and DB connectivity against configurable thresholds (`CPU_WARNING_THRESHOLD=70`, `CPU_CRITICAL_THRESHOLD=90`, etc.).
3. **Log Analysis Agent** ([`backend/agents/log_agent.py`](backend/agents/log_agent.py))  
   Parses raw log lines into structured timestamps, levels (`INFO`/`WARNING`/`ERROR`/`CRITICAL`), services, and error signatures (`CPU_THRESHOLD_EXCEEDED`, `DISK_SPACE_CRITICAL`, `SERVICE_FAILURE`, `DB_CONNECTION_REFUSED`).
4. **Root Cause Analysis Agent** ([`backend/agents/root_cause_agent.py`](backend/agents/root_cause_agent.py))  
   Correlates monitoring and log findings to produce probable root cause hypotheses with confidence scores. Uses local Ollama when available (`OLLAMA_LLM`) and transparently switches to `DETERMINISTIC_FALLBACK` if Ollama is offline or times out.
5. **RAG Knowledge Agent** ([`backend/agents/rag_agent.py`](backend/agents/rag_agent.py))  
   Chunks and embeds local Markdown runbooks (`cpu_high.md`, `disk_full.md`, `service_failure.md`) into ChromaDB and performs cosine semantic retrieval.
6. **Remediation Planning Agent & Risk Engine** ([`backend/agents/remediation_agent.py`](backend/agents/remediation_agent.py), [`backend/services/risk_engine.py`](backend/services/risk_engine.py))  
   Selects an action strictly from the allowlist (`cleanup_simulated_temp_files`, `restart_simulated_service`, `restore_simulated_service`). Never executes arbitrary LLM-generated shell commands. Enforces `LOW` (auto-approvable), `MEDIUM` (policy-checked), and `HIGH` (always human-approved) tiers.
7. **Validation Agent** ([`backend/agents/validation_agent.py`](backend/agents/validation_agent.py))  
   Captures post-remediation metrics, checks service health, compares before-and-after values, and marks `RESOLVED` **only** when recovery is verified. Automatically triggers `RemediationExecutor.rollback_simulated_action()` and escalates if recovery fails.

---

## 4. Local Installation & Startup (Without Docker)

### Prerequisites
- Python 3.11+ (tested on Python 3.13.5)
- Git
- Optional: [Ollama](https://ollama.com/) installed locally

### Installation Commands

```powershell
# 1. Clone the repository
git clone https://github.com/Darshi7587/Incident-Resolution.git
cd Incident-Resolution

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Copy environment configuration
Copy-Item .env.example .env
```

### Ollama Model Setup (Optional Local LLM)

```powershell
# Pull a local model (choose one matching your RAM/CPU)
ollama pull llama3.1:latest
# or lightweight 1B model:
ollama pull gemma3:1b

# Start Ollama service if not already running
ollama serve
```

> If Ollama is not running or times out on CPU-only hardware, `RootCauseAnalysisAgent` automatically falls back to `DETERMINISTIC_FALLBACK` and explicitly labels the reasoning source in both the database and dashboard.

### Start Backend and Dashboard

Open **Terminal 1** (FastAPI Backend):

```powershell
.\venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload --port 8000
```

- Swagger UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

Open **Terminal 2** (Streamlit Dashboard):

```powershell
.\venv\Scripts\Activate.ps1
streamlit run frontend/dashboard.py --server.port 8501
```

- Dashboard URL: `http://localhost:8501`

---

## 5. Docker & Docker Compose Setup

```bash
# Build and start backend + frontend (connects to Ollama on host if running)
docker compose up --build

# Or include containerized Ollama service:
docker compose --profile with-ollama up --build
```

- FastAPI Backend: `http://localhost:8000/docs`
- Streamlit Dashboard: `http://localhost:8501`

---

## 6. REST API Reference

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Backend, SQLite, Ollama config, and thresholds status |
| `POST` | `/incidents/simulate` | Simulate a scenario (`high_cpu`, `disk_full`, `service_failure`, `normal`) |
| `GET` | `/incidents` | List all recorded incidents |
| `GET` | `/incidents/{incident_id}` | Get incident details, logs, and workflow state |
| `POST` | `/incidents/{incident_id}/process` | Execute LangGraph multi-agent workflow |
| `GET` | `/incidents/{incident_id}/timeline` | Get chronological SQLite agent execution timeline |
| `GET` | `/incidents/{incident_id}/report` | Generate auditable report (`?format=json` or `?format=text`) |
| `GET` | `/approvals/pending` | List pending human approval requests |
| `POST` | `/approvals/{approval_id}/approve` | Approve action & resume workflow |
| `POST` | `/approvals/{approval_id}/reject` | Reject action, block execution, & escalate |
| `GET` | `/system/metrics` | Get current simulated infrastructure metrics |
| `POST` | `/system/reset` | Reset simulated infrastructure to healthy baseline |
| `GET` | `/runbooks` | List local Markdown runbooks |
| `POST` | `/runbooks/ingest` | Ingest/re-ingest runbooks into ChromaDB |
| `GET` | `/runbooks/search` | Semantic search over ChromaDB runbook chunks |
| `POST` | `/evaluation/run` | Run simulated 7-case evaluation suite |
| `GET` | `/evaluation/latest` | Fetch latest evaluation metrics |

---

## 7. Phase 1 Evaluation & Demonstration Guide

1. **Scenario 1 — High CPU Utilization (`high_cpu`):**
   - In the sidebar, choose **1. High CPU Utilization (application-server)** and click **Generate & Process Incident**.
   - Observe CPU spike to `95%`, `cpu_high.md` retrieved via ChromaDB, `restart_simulated_service` proposed (`MEDIUM` risk), and workflow paused at `AWAITING_APPROVAL`.
   - Go to **G. Human-in-the-Loop Approval Center** and click **Approve**.
   - Observe CPU drop to `26%`, `application-server` return to `HEALTHY`, status become `RESOLVED`, and inspect the Before/After chart and downloadable report in tab **H**.
2. **Scenario 2 — Disk Space Exhaustion (`disk_full`):**
   - Select **2. Disk Space Exhaustion (storage-service)** and click **Generate & Process Incident**.
   - Observe disk at `96%` (`2 GB` free), `disk_full.md` retrieved, `cleanup_simulated_temp_files` classified `LOW` risk (auto-approved), simulated temp cache cleaned, disk drop to `54%`, and status become `RESOLVED`.
3. **Scenario 3 — Application Service Failure (`service_failure`) + Human Approval / Rejection:**
   - Select **3. Application Service Failure (payment-api)** and click **Generate & Process Incident**.
   - Observe `payment-api` `FAILED`, `db_connected=False`, `service_failure.md` retrieved, and `restore_simulated_service` classified `HIGH` risk.
   - **To demonstrate Rejection:** Click **Reject** in the Approval Center -> `payment-api` remains `FAILED`, the action is marked `REJECTED_NOT_EXECUTED`, and the incident is `ESCALATED`.
   - **To demonstrate Approval:** Trigger Scenario 3 again and click **Approve** -> `db-server` and `payment-api` return to `HEALTHY` and status becomes `RESOLVED`.
4. **Failed Remediation & Controlled Rollback:**
   - Check **Simulate Remediation Failure (Test Rollback)** in the sidebar, select Scenario 1, and click **Generate & Process Incident**.
   - Click **Approve** in the Approval Center.
   - Validation Agent detects CPU remained unhealthy (`93%`), triggers controlled rollback back to `95%` pre-remediation state, marks `rollback_status="ROLLED_BACK"`, and transitions incident to `ESCALATED` (never falsely marked `RESOLVED`).
5. **Simulated Evaluation Suite:**
   - Scroll to **I. Evaluation Metrics** and click **Run Simulated Evaluation Suite** to compute all 7 metrics live from `data/evaluation/evaluation_dataset.json`.

---

## 8. Running Automated Tests

```powershell
.\venv\Scripts\pytest.exe tests -v
```

---

## 9. Phase 1 Limitations & Scope

- **Simulated Infrastructure Only:** Metrics, logs, and remediation tools operate on local simulated state (`SimulatedInfrastructure`) rather than live Kubernetes, AWS, or production Linux hosts.
- **Single-Node SQLite & ChromaDB:** Phase 1 uses local SQLite and local persistent ChromaDB; enterprise multi-tenant scaling and RBAC SSO are deferred to future phases.
- **CPU-Only LLM Latency:** Larger local Ollama models (`llama3.1:latest`) require sufficient RAM/GPU for low-latency responses; on slower CPUs, the configurable timeout gracefully engages the deterministic fallback.
