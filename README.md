# Autonomous IT Incident Resolution

**Academic Capstone Project — Phase 1 Prototype**  
*Innovation Center, Center for Artificial Intelligence & Machine Learning*

An agentic AI system built exclusively with free and open-source technologies and locally simulated IT infrastructure to automate IT incident triage, correlation, runbook retrieval, controlled remediation, human-in-the-loop safety approval, recovery validation, and auditable reporting.

## Technology Stack

- **Backend:** Python, FastAPI, Pydantic, REST APIs
- **Agentic AI:** LangGraph, specialized Python agents, local Ollama LLM (with deterministic fallback)
- **RAG:** ChromaDB, `sentence-transformers`, local Markdown runbooks
- **Frontend:** Streamlit
- **Database:** SQLite
- **Infrastructure:** Docker, Docker Compose

## Quick Start (Phase 1 Foundation)

```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Start FastAPI backend
uvicorn backend.main:app --reload --port 8000
```

Verify health endpoint: `http://localhost:8000/health` and Swagger UI: `http://localhost:8000/docs`.
