"""BM25 sparse store for hybrid retrieval."""

from __future__ import annotations

import pickle
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens: list[str] = []
    for piece in _TOKEN_SPLIT_RE.split(text):
        if not piece:
            continue
        if _CJK_RE.search(piece) is None:
            tokens.append(piece)
            continue
        chars = [c for c in piece if _CJK_RE.match(c)]
        if not chars:
            continue
        tokens.extend(chars)
        tokens.extend([chars[i] + chars[i + 1] for i in range(len(chars) - 1)])
    return tokens


class BM25Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.bm25: BM25Okapi | None = None
        self.chunk_ids: list[str] = []
        self.texts_raw: list[str] = []
        self.metas: list[dict] = []
        if self.path.exists():
            self.load()

    def build(self, chunk_ids: list[str], texts: list[str], metas: list[dict]) -> None:
        tokenized = [tokenize(t) for t in texts]
        self.bm25 = BM25Okapi(tokenized)
        self.chunk_ids = chunk_ids
        self.texts_raw = texts
        self.metas = metas
        self.save()

    def merge_build(self, chunk_ids: list[str], texts: list[str], metas: list[dict]) -> None:
        all_ids = list(self.chunk_ids) + chunk_ids
        all_texts = list(self.texts_raw) + texts
        all_metas = list(self.metas) + metas
        self.build(all_ids, all_texts, all_metas)

    def save(self) -> None:
        with self.path.open("wb") as f:
            pickle.dump({
                "bm25": self.bm25,
                "chunk_ids": self.chunk_ids,
                "texts_raw": self.texts_raw,
                "metas": self.metas,
            }, f)

    def load(self) -> bool:
        try:
            with self.path.open("rb") as f:
                data = pickle.load(f)
        except Exception:
            return False
        self.bm25 = data.get("bm25")
        self.chunk_ids = data.get("chunk_ids", [])
        self.texts_raw = data.get("texts_raw", [])
        self.metas = data.get("metas", [])
        return True

    def _candidate_indices(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        origins: frozenset[str] | None = None,
    ) -> list[int]:
        from localagent.knowledge.time_filter import meta_in_range

        indices: list[int] = []
        for i, meta in enumerate(self.metas):
            if origins is not None:
                origin = str(meta.get("origin") or "").strip()
                if origin not in origins:
                    continue
            if since or until:
                if not meta_in_range(meta, since=since, until=until):
                    continue
            indices.append(i)
        return indices

    def query(
        self,
        query: str,
        top_k: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        origins: frozenset[str] | None = None,
    ) -> list[dict]:
        if self.bm25 is None or not self.chunk_ids:
            return []
        import numpy as np

        scores = np.asarray(self.bm25.get_scores(tokenize(query)), dtype=float)
        if since or until or origins is not None:
            allowed = self._candidate_indices(since=since, until=until, origins=origins)
            if not allowed:
                return []
            masked = np.full(len(scores), -np.inf)
            for i in allowed:
                masked[i] = scores[i]
            scores = masked

        finite = np.isfinite(scores)
        if not finite.any():
            return []
        # Rank only finite scores.
        order = np.argsort(-scores)
        hits = []
        for idx in order:
            i = int(idx)
            if not np.isfinite(scores[i]):
                continue
            hits.append({
                "chunk_id": self.chunk_ids[i],
                "text": self.texts_raw[i],
                "metadata": self.metas[i],
                "score_sparse": float(scores[i]),
            })
            if len(hits) >= top_k:
                break
        return hits

    def list_in_range(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        origins: frozenset[str] | None = None,
        prefer_summary: bool = True,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """List chunks in a date window (no semantic scoring), newest first."""
        from localagent.knowledge.time_filter import chunk_recorded_at

        indices = self._candidate_indices(since=since, until=until, origins=origins)
        rows: list[tuple[str, dict[str, Any]]] = []
        for i in indices:
            meta = self.metas[i]
            if prefer_summary and str(meta.get("chunk_kind") or "") not in ("", "summary"):
                continue
            rows.append(
                (
                    chunk_recorded_at(meta),
                    {
                        "chunk_id": self.chunk_ids[i],
                        "text": self.texts_raw[i],
                        "metadata": meta,
                        "score_sparse": 1.0,
                        "score_rrf": 1.0,
                    },
                )
            )
        if prefer_summary and len(rows) < limit:
            seen_ids = {r[1]["chunk_id"] for r in rows}
            seen_convs = {
                str((r[1]["metadata"] or {}).get("conversation_id") or "")
                for r in rows
            }
            for i in indices:
                meta = self.metas[i]
                cid = self.chunk_ids[i]
                if cid in seen_ids:
                    continue
                conv = str(meta.get("conversation_id") or "")
                if conv and conv in seen_convs:
                    continue
                if str(meta.get("chunk_kind") or "") == "summary":
                    continue
                rows.append(
                    (
                        chunk_recorded_at(meta),
                        {
                            "chunk_id": cid,
                            "text": self.texts_raw[i],
                            "metadata": meta,
                            "score_sparse": 0.5,
                            "score_rrf": 0.5,
                        },
                    )
                )
                if conv:
                    seen_convs.add(conv)
                if len(rows) >= limit:
                    break

        rows.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in rows[:limit]]

    def count(self) -> int:
        return len(self.chunk_ids)

    def reset(self) -> None:
        self.bm25 = None
        self.chunk_ids = []
        self.texts_raw = []
        self.metas = []
        if self.path.exists():
            self.path.unlink()

    def remove_by_source_file(self, source_file: str) -> None:
        keep_ids, keep_texts, keep_metas = [], [], []
        for cid, text, meta in zip(self.chunk_ids, self.texts_raw, self.metas):
            if meta.get("source_file") == source_file:
                continue
            keep_ids.append(cid)
            keep_texts.append(text)
            keep_metas.append(meta)
        if keep_ids:
            self.build(keep_ids, keep_texts, keep_metas)
        else:
            self.reset()

    def remove_by_origin(self, origin: str) -> None:
        keep_ids, keep_texts, keep_metas = [], [], []
        for cid, text, meta in zip(self.chunk_ids, self.texts_raw, self.metas):
            if str(meta.get("origin") or "") == origin:
                continue
            keep_ids.append(cid)
            keep_texts.append(text)
            keep_metas.append(meta)
        if keep_ids:
            self.build(keep_ids, keep_texts, keep_metas)
        else:
            self.reset()
