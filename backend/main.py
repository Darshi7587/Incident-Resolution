"""FastAPI application entrypoint for Autonomous IT Incident Resolution."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.database.db import check_db_connection, init_db
from backend.routes.incidents import router as incidents_router
from backend.routes.runbooks import router as runbooks_router
from backend.schemas.common import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SQLite tables on application startup."""
    init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Phase 1 Prototype for Autonomous IT Incident Resolution using LangGraph, "
            "Ollama (with deterministic fallback), ChromaDB RAG, SQLite audit trails, "
            "and human-in-the-loop safety approvals."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["System"])
    def health_check() -> HealthResponse:
        """Verify FastAPI backend and SQLite database health."""
        db_ok = check_db_connection()
        return HealthResponse(
            status="healthy" if db_ok else "degraded",
            app_name=settings.app_name,
            environment=settings.app_env,
            database_connected=db_ok,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            thresholds={
                "cpu_warning": settings.cpu_warning_threshold,
                "cpu_critical": settings.cpu_critical_threshold,
                "memory_warning": settings.memory_warning_threshold,
                "memory_critical": settings.memory_critical_threshold,
                "disk_warning": settings.disk_warning_threshold,
                "disk_critical": settings.disk_critical_threshold,
            },
        )

    app.include_router(incidents_router)
    app.include_router(runbooks_router)
    return app


app = create_app()
