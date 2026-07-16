"""ChromaDB vector store with shared LocalAgent embedder."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class _SharedEmbeddingFunction:
    """Chroma embedding_function adapter over LocalAgent shared embedder."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] | None = None

    @staticmethod
    def name() -> str:
        return "localagent_shared"

    def get_config(self) -> dict[str, Any]:
        return {"provider": "localagent_shared"}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "_SharedEmbeddingFunction":  # noqa: ARG004
        return _SharedEmbeddingFunction()

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]

    def _resolve(self) -> dict[str, Any]:
        if self._settings is None:
            from localagent.memory.backends.mem0_backend import resolve_mem0_embedder_settings

            self._settings = resolve_mem0_embedder_settings()
        return self._settings

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 — chroma API
        from localagent.memory.embeddings import embed_texts

        return embed_texts(input, settings=self._resolve())

    def embed_query(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self(input)


class ChromaStore:
    def __init__(self, persist_dir: Path, collection_name: str = "localagent_kb") -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._collection = None
        self._available = False
        self._embedding_fn = _SharedEmbeddingFunction()
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            try:
                self._collection = self._client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=self._embedding_fn,
                )
            except Exception:
                # Existing collection may have been created with default embedder.
                self._collection = self._client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.warning(
                    "Chroma collection %s opened without shared embedder; "
                    "recreate knowledge index if dense recall looks wrong",
                    collection_name,
                )
            self._available = True
        except Exception:
            self._client = None

    @property
    def available(self) -> bool:
        return self._available

    def upsert(
        self,
        *,
        chunk_ids: list[str],
        texts: list[str],
        metadatas: list[dict],
    ) -> None:
        if not self._available or not chunk_ids or self._collection is None:
            return
        batch = 64
        for i in range(0, len(chunk_ids), batch):
            self._collection.upsert(
                ids=chunk_ids[i : i + batch],
                documents=texts[i : i + batch],
                metadatas=metadatas[i : i + batch],
            )

    def query(self, query: str, top_k: int) -> list[dict[str, Any]]:
        if not self._available or self._collection is None or self._collection.count() == 0:
            return []
        res = self._collection.query(
            query_texts=[query],
            n_results=min(top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
            sim = 1.0 - float(dist) if dist is not None else 0.0
            hits.append({
                "chunk_id": cid,
                "text": doc,
                "metadata": meta,
                "score_dense": sim,
            })
        return hits

    def count(self) -> int:
        if not self._available or self._collection is None:
            return 0
        return int(self._collection.count())

    def reset(self) -> None:
        if not self._available or self._client is None:
            return
        self._client.delete_collection(self.collection_name)
        try:
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=self._embedding_fn,
            )
        except Exception:
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

    def delete_by_source_file(self, source_file: str) -> None:
        if not self._available or self._collection is None:
            return
        try:
            self._collection.delete(where={"source_file": source_file})
        except Exception:
            pass

    def delete_by_origin(self, origin: str) -> None:
        if not self._available or self._collection is None:
            return
        try:
            self._collection.delete(where={"origin": origin})
        except Exception:
            pass
