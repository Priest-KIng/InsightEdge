from __future__ import annotations

from sentence_transformers import SentenceTransformer


class EmbeddingService:
    def __init__(self, model_name: str) -> None:
        try:
            self.model = SentenceTransformer(model_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to load embedding model {model_name}: {exc}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.model.encode(texts, normalize_embeddings=True)
            return vectors.tolist()
        except Exception as exc:
            raise RuntimeError(f"Failed to embed texts: {exc}") from exc
