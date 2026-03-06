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
    default_workspace_id: str = "default"

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "phi3:mini"
    llm_timeout_seconds: int = 180
    system_prompt: str = (
        "You are a private local assistant. Use only the provided context to answer. "
        "If the context is insufficient, say you do not have enough information. "
        "If asked about tables/images/charts, inspect any extracted table or OCR sections before concluding. "
        "When tables are provided as pipe-delimited rows, treat the first row as headers and map later rows to those columns."
    )

    chunk_size: int = 1400
    chunk_overlap: int = 280
    top_k: int = 3
    max_similarity_distance: float = 0.65
    retrieval_candidate_k: int = 12
    enable_hyde: bool = False
    hyde_max_chars: int = 1500
    enable_multi_query: bool = False
    multi_query_count: int = 3
    enable_parent_document_retrieval: bool = False
    parent_document_max_chars: int = 4000
    hybrid_rrf_k: int = 60
    cross_encoder_model: str | None = None
    cross_encoder_top_n: int = 8
    context_compression_max_sentences: int = 4
    context_compression_max_chars: int = 900
    ingest_max_workers: int = 4

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
