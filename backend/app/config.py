from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    app_name: str = "InsightEdge"
    app_env: str = "dev"
    api_prefix: str = "/api"
    api_key: str | None = None

    data_dir: Path = BACKEND_DIR / "data"
    vector_db_dir: Path = data_dir / "chroma"
    ingest_base_dir: Path = data_dir / "ingest"
    state_db_path: Path = data_dir / "state.db"
    max_file_size_mb: int = 25

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    collection_name: str = "insightedge_docs"

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.1:8b-instruct-q4_K_M"
    llm_timeout_seconds: int = 180

    chunk_size: int = 1400
    chunk_overlap: int = 280
    top_k: int = 4
    max_similarity_distance: float = 0.65

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    cors_allow_credentials: bool = False

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.vector_db_dir.mkdir(parents=True, exist_ok=True)
settings.ingest_base_dir.mkdir(parents=True, exist_ok=True)
