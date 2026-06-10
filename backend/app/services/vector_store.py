from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings


class VectorStore:
    def __init__(self, persist_directory: str, collection_name: str) -> None:
        self.base_collection_name = collection_name
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection_cache: dict[str, Any] = {}

    def _collection_name_for(self, workspace_id: str) -> str:
        return f"{self.base_collection_name}_{workspace_id}"

    def _collection_for(self, workspace_id: str) -> Any:
        if workspace_id in self._collection_cache:
            return self._collection_cache[workspace_id]
        collection = self.client.get_or_create_collection(
            name=self._collection_name_for(workspace_id),
        )
        self._collection_cache[workspace_id] = collection
        return collection

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        workspace_id: str,
    ) -> None:
        self._collection_for(workspace_id).upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(self, embedding: list[float], top_k: int, workspace_id: str) -> dict[str, Any]:
        return self._collection_for(workspace_id).query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["distances", "metadatas", "documents"],
        )

    def get_all(self, workspace_id: str) -> dict[str, Any]:
        return self._collection_for(workspace_id).get(include=["metadatas", "documents"])

    def delete_by_document_id(self, document_id: str, workspace_id: str) -> None:
        self._collection_for(workspace_id).delete(where={"document_id": document_id})

    def delete_all(self, workspace_id: str) -> None:
        payload = self.get_all(workspace_id)
        ids = payload.get("ids") or []
        if ids:
            self._collection_for(workspace_id).delete(ids=ids)

    def delete_workspace(self, workspace_id: str) -> None:
        self._collection_cache.pop(workspace_id, None)
        collection_name = self._collection_name_for(workspace_id)
        try:
            self.client.delete_collection(name=collection_name)
        except Exception:
            # Chroma raises for missing collections; deleting an absent workspace is idempotent.
            return

    def list_workspaces(self) -> list[str]:
        workspaces: list[str] = []
        prefix = f"{self.base_collection_name}_"
        for collection in self.client.list_collections():
            name = getattr(collection, "name", "")
            if not isinstance(name, str):
                continue
            if name.startswith(prefix):
                workspaces.append(name[len(prefix) :])
        return sorted(set(workspaces))
