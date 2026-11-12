"""Application configuration using Pydantic Settings and environment variables."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Centralized configuration for the Autonomous IT Incident Resolution prototype."""

    app_name: str = "Autonomous IT Incident Resolution"
    app_env: str = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    backend_url: str = "http://localhost:8000"

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'runtime' / 'incidents.db').as_posix()}"

    # Ollama Local LLM Configuration
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:latest"
    ollama_timeout_seconds: int = 30

    # RAG / ChromaDB Configuration
    chroma_persist_dir: str = str(BASE_DIR / "data" / "chroma_db")
    embedding_model: str = "all-MiniLM-L6-v2"
    runbooks_dir: str = str(BASE_DIR / "backend" / "runbooks")

    # Configurable Monitoring Thresholds
    cpu_warning_threshold: float = 70.0
    cpu_critical_threshold: float = 90.0
    memory_warning_threshold: float = 75.0
    memory_critical_threshold: float = 90.0
    disk_warning_threshold: float = 80.0
    disk_critical_threshold: float = 90.0

    # Safety / Approval Policy
    auto_approve_low_risk: bool = True
    require_approval_medium_risk: bool = True
    require_approval_high_risk: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
