"""Configurable CPU-capable embeddings with an explicitly lexical offline mode."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from functools import cached_property

import numpy as np

from cpse_harmonizer.normalization.attribute_extractor import extract_attributes


class EmbeddingService:
    """Embed descriptions with Sentence-Transformers or a non-semantic smoke fallback.

    ``lexical`` is deliberately not presented as a semantic model. Set
    ``NUMMF_EMBEDDING_BACKEND=sentence-transformers`` and configure the model
    explicitly for a production-capable local dense index.
    """

    def __init__(
        self,
        dimension: int = 512,
        model_name: str | None = None,
        backend: str | None = None,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.dimension = dimension
        self.backend = (backend or os.getenv("NUMMF_EMBEDDING_BACKEND", "lexical")).casefold()
        if self.backend not in {"lexical", "sentence-transformers"}:
            raise ValueError(
                "NUMMF embedding backend must be 'lexical' or 'sentence-transformers'."
            )
        self.model_name = (
            model_name
            or os.getenv("NUMMF_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
            or "intfloat/multilingual-e5-small"
        )
        self.device = device or os.getenv("NUMMF_EMBEDDING_DEVICE", "cpu")
        self.batch_size = max(1, batch_size)
        self._cache: dict[str, list[float]] = {}

    @property
    def model_version(self) -> str:
        if self.backend == "lexical":
            return f"lexical-hash-baseline-v1:{self.dimension}"
        return f"sentence-transformers:{self.model_name}"

    @cached_property
    def _model(self):
        if self.backend != "sentence-transformers":
            return None
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Sentence-Transformers is not installed; install the 'ml' extra or select lexical smoke mode."
            ) from exc
        return SentenceTransformer(self.model_name, device=self.device)

    @staticmethod
    def serialize_attributes(text: str) -> str:
        attributes = extract_attributes(text)
        serialized = [f"family={attributes.family}"]
        for attribute in sorted(attributes.attributes, key=lambda item: item.attribute_name):
            value = (
                attribute.normalized_value
                if attribute.normalized_value is not None
                else attribute.value
            )
            suffix = f" {attribute.unit}" if attribute.unit else ""
            serialized.append(f"{attribute.attribute_name}={value}{suffix}")
        return " ".join(serialized)

    def _input_text(self, text: str, *, is_query: bool) -> str:
        value = str(text or "").strip()
        if self.backend == "sentence-transformers":
            prefix = "query" if is_query else "passage"
            return f"{prefix}: {value} {self.serialize_attributes(value)}"
        return value

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text], is_query=True)[0]

    def embed_many(self, texts: Iterable[str], *, is_query: bool = False) -> list[list[float]]:
        inputs = [self._input_text(text, is_query=is_query) for text in texts]
        if not inputs:
            return []
        if self.backend == "lexical":
            return [self._lexical_vector(text) for text in inputs]

        missing = list(dict.fromkeys(text for text in inputs if text not in self._cache))
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start : start + self.batch_size]
            vectors = self._model.encode(
                batch,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            for text, vector in zip(batch, vectors, strict=True):
                self._cache[text] = np.asarray(vector, dtype=float).tolist()
        return [self._cache[text] for text in inputs]

    def similarity(self, left: str, right: str) -> float:
        left_vector = np.asarray(self.embed(left), dtype=float)
        right_vector = np.asarray(self.embed(right), dtype=float)
        denominator = float(np.linalg.norm(left_vector) * np.linalg.norm(right_vector))
        if denominator == 0:
            return 0.0
        return float(np.dot(left_vector, right_vector) / denominator)

    def _lexical_vector(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9]+", text.casefold())
        vector = np.zeros(self.dimension, dtype=float)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimension
            vector[index] += 1.0
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector.tolist()
