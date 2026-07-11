"""ChromaDB vector store with JSON keyword fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ChromaStore:
    def __init__(self, persist_dir: Path, collection_name: str = "localagent_kb") -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._collection = None
        self._available = False
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
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
        batch = 256
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
        return self._collection.count()

    def reset(self) -> None:
        if not self._available or self._client is None:
            return
        self._client.delete_collection(self.collection_name)
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
