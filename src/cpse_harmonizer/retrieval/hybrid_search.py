"""Material-ID-aware BM25 and optional dense retrieval with reciprocal-rank fusion."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cpse_harmonizer.domain.models import MaterialRecord, stable_id
from cpse_harmonizer.extraction.embedding_service import EmbeddingService

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def rrf_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """Fuse ordered material IDs; ranking position is never treated as identity."""
    if k < 1:
        raise ValueError("RRF k must be a positive integer.")
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, candidate_id in enumerate(ranking, start=1):
            fused[candidate_id] = fused.get(candidate_id, 0.0) + 1.0 / (k + rank)
    return dict(fused)


@dataclass(slots=True)
class _Document:
    candidate_id: str
    text: str
    family: str | None


class HybridSearchEngine:
    """BM25 candidate retrieval plus Sentence-Transformer dense ranking if configured."""

    def __init__(
        self,
        documents: Sequence[str | MaterialRecord],
        *,
        document_ids: Sequence[str] | None = None,
        families: Sequence[str | None] | None = None,
        embedding_service: EmbeddingService | None = None,
        rrf_k: int = 60,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.rrf_k = rrf_k
        if document_ids is not None and len(document_ids) != len(documents):
            raise ValueError("document_ids must align one-to-one with documents.")
        if families is not None and len(families) != len(documents):
            raise ValueError("families must align one-to-one with documents.")
        self.documents: list[_Document] = []
        for index, document in enumerate(documents):
            if isinstance(document, MaterialRecord):
                text = document.normalized_description or document.raw_description
                candidate_id = document.id
                family_value = next(
                    (a.value for a in document.attributes if a.attribute_name == "family"), None
                )
                family = str(family_value) if family_value is not None else None
            else:
                text = str(document)
                candidate_id = ""
                family = None
            if document_ids is not None:
                candidate_id = document_ids[index]
            if families is not None:
                family = families[index]
            if not candidate_id:
                candidate_id = stable_id("doc", str(index), " ".join(text.casefold().split()))
            self.documents.append(_Document(candidate_id, text, family))
        self._tokens = [self._tokenize(doc.text) for doc in self.documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._average_length = sum(self._lengths) / max(len(self._lengths), 1)
        self._document_frequencies: Counter[str] = Counter()
        for tokens in self._tokens:
            self._document_frequencies.update(set(tokens))
        self._dense_vectors: np.ndarray | None = None
        if self.embedding_service.backend == "sentence-transformers" and self.documents:
            self._dense_vectors = np.asarray(
                self.embedding_service.embed_many(doc.text for doc in self.documents),
                dtype=float,
            )

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        family: str | None = None,
    ) -> list[dict[str, float | str | int | None]]:
        if limit < 1:
            raise ValueError("limit must be at least one.")
        query_terms = self._tokenize(query)
        if not query_terms or not self.documents:
            return []
        indices = [
            index
            for index, doc in enumerate(self.documents)
            if family is None or doc.family is None or doc.family.casefold() == family.casefold()
        ]
        if not indices:
            return []

        lexical_raw = {index: self._bm25(query_terms, index) for index in indices}
        max_lexical = max(lexical_raw.values(), default=0.0)
        lexical_scores = {
            index: (score / max_lexical if max_lexical > 0 else 0.0)
            for index, score in lexical_raw.items()
        }
        lexical_rank = sorted(
            indices, key=lambda i: (-lexical_raw[i], self.documents[i].candidate_id)
        )
        lexical_rank = [index for index in lexical_rank if lexical_raw[index] > 0]
        dense_scores: dict[int, float] = {}
        dense_rank: list[int] = []
        if self._dense_vectors is not None:
            query_vector = np.asarray(self.embedding_service.embed(query), dtype=float)
            for index in indices:
                dense_scores[index] = float(np.dot(query_vector, self._dense_vectors[index]))
            dense_rank = sorted(
                indices, key=lambda i: (-dense_scores[i], self.documents[i].candidate_id)
            )

        rankings = (
            [
                [self.documents[index].candidate_id for index in lexical_rank],
                [self.documents[index].candidate_id for index in dense_rank],
            ]
            if dense_rank
            else [[self.documents[index].candidate_id for index in lexical_rank]]
        )
        fusion = rrf_fusion(rankings, k=self.rrf_k)
        index_by_id = {self.documents[index].candidate_id: index for index in indices}
        ordered_ids = sorted(fusion, key=lambda candidate_id: (-fusion[candidate_id], candidate_id))
        results: list[dict[str, float | str | int | None]] = []
        for rank, candidate_id in enumerate(ordered_ids[:limit], start=1):
            index = index_by_id[candidate_id]
            results.append(
                {
                    "candidate_id": candidate_id,
                    "rank": rank,
                    "lexical_score": lexical_scores[index],
                    "dense_score": dense_scores.get(index),
                    "fusion_score": fusion[candidate_id],
                    "text": self.documents[index].text,
                }
            )
        return results

    def save(self, path: str | Path) -> None:
        """Persist exact source IDs/text and the retrieval configuration for reproducible rebuilds."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1",
            "embedding_model_version": self.embedding_service.model_version,
            "rrf_k": self.rrf_k,
            "documents": [
                {
                    "candidate_id": document.candidate_id,
                    "text": document.text,
                    "family": document.family,
                }
                for document in self.documents
            ],
        }
        payload["index_version"] = hashlib.sha256(
            json.dumps(
                payload["documents"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        embedding_service: EmbeddingService | None = None,
    ) -> HybridSearchEngine:
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1" or not isinstance(payload.get("documents"), list):
            raise ValueError(f"Unsupported or malformed retrieval index: {source}")
        documents = payload["documents"]
        actual_hash = hashlib.sha256(
            json.dumps(documents, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        if actual_hash != payload.get("index_version"):
            raise ValueError(f"Retrieval index checksum failed: {source}")
        embedder = embedding_service or EmbeddingService()
        if embedder.model_version != payload.get("embedding_model_version"):
            raise ValueError("Configured embedding model/version differs from the persisted index.")
        return cls(
            [item["text"] for item in documents],
            document_ids=[item["candidate_id"] for item in documents],
            families=[item.get("family") for item in documents],
            embedding_service=embedder,
            rrf_k=int(payload.get("rrf_k", 60)),
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_RE.findall(text.casefold())

    def _bm25(self, query_terms: list[str], index: int, k1: float = 1.5, b: float = 0.75) -> float:
        terms = Counter(self._tokens[index])
        length = self._lengths[index]
        score = 0.0
        count = len(self.documents)
        for term in query_terms:
            frequency = terms.get(term, 0)
            if frequency == 0:
                continue
            df = self._document_frequencies[term]
            inverse_frequency = math.log(1 + (count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / max(self._average_length, 1))
            score += inverse_frequency * frequency * (k1 + 1) / denominator
        return score
