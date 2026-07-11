"""BM25 sparse store for hybrid retrieval."""

from __future__ import annotations

import pickle
import re
from pathlib import Path

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

    def query(self, query: str, top_k: int) -> list[dict]:
        if self.bm25 is None or not self.chunk_ids:
            return []
        import numpy as np

        scores = self.bm25.get_scores(tokenize(query))
        scores_arr = np.asarray(scores)
        if top_k >= len(scores_arr):
            top_idx = np.argsort(-scores_arr)
        else:
            top_idx = np.argpartition(-scores_arr, top_k)[:top_k]
            top_idx = top_idx[np.argsort(-scores_arr[top_idx])]
        hits = []
        for idx in top_idx:
            i = int(idx)
            hits.append({
                "chunk_id": self.chunk_ids[i],
                "text": self.texts_raw[i],
                "metadata": self.metas[i],
                "score_sparse": float(scores_arr[i]),
            })
            if len(hits) >= top_k:
                break
        return hits

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
