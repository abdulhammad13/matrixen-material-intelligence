"""Layer 4 retrieval: BM25/Tf-idf + dense embedding + reciprocal rank fusion."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from cpse_harmonizer.extraction.embedding_service import EmbeddingService


def rrf_fusion(ranks: Sequence[Sequence[float]], k: int = 60) -> list[float]:
    """Fuse multiple ranking lists using reciprocal rank fusion."""
    if not ranks:
        return []
    n = max(len(group) for group in ranks)
    fused = np.zeros(n, dtype=float)
    for group in ranks:
        for idx, _ in enumerate(group):
            fused[idx] += 1.0 / (k + idx + 1)
    return fused.tolist()


class HybridSearchEngine:
    """Lightweight hybrid retrieval engine over a corpus of material strings."""

    def __init__(self, documents: Sequence[str]) -> None:
        self.documents = list(documents)
        self.vectorizer = TfidfVectorizer(stop_words="english")
        if self.documents:
            self.sparse_matrix = self.vectorizer.fit_transform(self.documents)
        else:
            self.sparse_matrix = None
        self.embedding_service = EmbeddingService()
        self.dense_matrix = np.asarray(self.embedding_service.embed_many(self.documents), dtype=float) if self.documents else np.empty((0, 0))

    def search(self, query: str, limit: int = 5) -> list[dict[str, float | str | int]]:
        if not self.documents:
            return []
        query_vector = self.vectorizer.transform([query])
        sparse_scores = cosine_similarity(query_vector, self.sparse_matrix)[0]
        dense_query = np.asarray(self.embedding_service.embed(query), dtype=float)
        dense_scores = cosine_similarity(dense_query.reshape(1, -1), self.dense_matrix)[0]
        ranked_indices = np.argsort(-(sparse_scores * 0.5 + dense_scores * 0.5))[:limit]
        results: list[dict[str, float | str | int]] = []
        for index in ranked_indices:
            total = float((sparse_scores[index] * 0.5) + (dense_scores[index] * 0.5))
            results.append({
                "index": int(index),
                "score": total,
                "text": self.documents[int(index)],
            })
        return results
