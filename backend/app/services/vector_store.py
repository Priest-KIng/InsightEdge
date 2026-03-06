from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings


class VectorStore:
    def __init__(self, persist_directory: str, collection_name: str) -> None:
        client = chromadb.PersistentClient(
            path=persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = client.get_or_create_collection(name=collection_name)

    def upsert(self, ids: list[str], embeddings: list[list[float]], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        self.collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def query(self, embedding: list[float], top_k: int) -> dict[str, Any]:
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["distances", "metadatas", "documents", "ids"],
        )

    def get_all(self) -> dict[str, Any]:
        return self.collection.get(include=["metadatas", "documents", "ids"])

    def delete_by_document_id(self, document_id: str) -> None:
        self.collection.delete(where={"document_id": document_id})

    def delete_all(self) -> None:
        payload = self.get_all()
        ids = payload.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)
