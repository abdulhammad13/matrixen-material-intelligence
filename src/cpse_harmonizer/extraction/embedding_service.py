"""Layer 3 extraction: deterministic embedding service for material text.

A production implementation would use a hosted or local sentence-transformer, but
this utility keeps a tiny offline fallback for testing and local scoring.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

import numpy as np


class EmbeddingService:
    """Return a compact deterministic embedding vector for a material description."""

    def __init__(self, dimension: int = 32, model_version: str = "synthetic-v1") -> None:
        self.dimension = dimension
        self.model_version = model_version

    def embed(self, text: str) -> list[float]:
        raw = str(text or "")
        tokens = re.findall(r"[A-Za-z0-9]+", raw.lower())
        vector = np.zeros(self.dimension, dtype=float)
        if not tokens:
            return vector.tolist()
        for token in tokens:
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            vector[index] += 1.0
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return vector.tolist()

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def similarity(self, left: str, right: str) -> float:
        left_vector = np.asarray(self.embed(left), dtype=float)
        right_vector = np.asarray(self.embed(right), dtype=float)
        denom = float(np.linalg.norm(left_vector) * np.linalg.norm(right_vector))
        if denom == 0:
            return 0.0
        return float(np.dot(left_vector, right_vector) / denom)
