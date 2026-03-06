from __future__ import annotations

import math

import httpx
from sentence_transformers import SentenceTransformer


class EmbeddingService:
    def __init__(self, model_name: str, provider: str = "sentence_transformers", ollama_base_url: str = "http://localhost:11434") -> None:
        self.model_name = model_name
        self.provider = provider.strip().lower()
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = None

        if self.provider == "sentence_transformers":
            try:
                self.model = SentenceTransformer(model_name)
            except Exception as exc:
                raise RuntimeError(f"Failed to load embedding model {model_name}: {exc}") from exc
            return

        if self.provider == "flagembedding":
            try:
                from FlagEmbedding import BGEM3FlagModel
            except Exception as exc:
                raise RuntimeError(f"FlagEmbedding import failed: {exc}") from exc
            try:
                self.model = BGEM3FlagModel(model_name, use_fp16=False)
            except Exception as exc:
                raise RuntimeError(f"Failed to load FlagEmbedding model {model_name}: {exc}") from exc
            return

        if self.provider == "ollama":
            return

        raise RuntimeError(
            f"Unsupported embedding provider '{provider}'. "
            "Expected one of: sentence_transformers, flagembedding, ollama",
        )

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum((value * value) for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _embed_with_ollama(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=120.0) as client:
            for text in texts:
                response = client.post(
                    f"{self.ollama_base_url}/api/embeddings",
                    json={"model": self.model_name, "prompt": text},
                )
                response.raise_for_status()
                payload = response.json()
                raw_vector = payload.get("embedding")
                if not isinstance(raw_vector, list):
                    raise RuntimeError("Ollama embeddings response missing 'embedding' list")
                vector = [float(value) for value in raw_vector]
                vectors.append(self._normalize_vector(vector))
        return vectors

    def _embed_with_flagembedding(self, texts: list[str]) -> list[list[float]]:
        if self.model is None:
            raise RuntimeError("FlagEmbedding model not initialized")
        output = self.model.encode(texts, batch_size=8, max_length=8192)
        if isinstance(output, dict):
            dense = output.get("dense_vecs")
        else:
            dense = output
        if dense is None:
            raise RuntimeError("FlagEmbedding output missing dense vectors")
        if hasattr(dense, "tolist"):
            dense = dense.tolist()
        return [self._normalize_vector([float(value) for value in vector]) for vector in dense]

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            if self.provider == "ollama":
                return self._embed_with_ollama(texts)
            if self.provider == "flagembedding":
                return self._embed_with_flagembedding(texts)
            if self.model is None:
                raise RuntimeError("SentenceTransformer model not initialized")
            vectors = self.model.encode(texts, normalize_embeddings=True)
            return vectors.tolist()
        except Exception as exc:
            raise RuntimeError(f"Failed to embed texts via provider '{self.provider}': {exc}") from exc
