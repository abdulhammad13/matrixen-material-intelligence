"""Normalization pipeline for material rows extracted from tender pages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.normalizer import MaterialNormalizer


class NormalizationService:
    """Normalize extracted material rows before matching and NMC generation."""

    def __init__(self, normalizer: MaterialNormalizer | None = None) -> None:
        self.normalizer = normalizer or MaterialNormalizer()

    def process(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        for item in items:
            description = str(
                item.get("short_description")
                or item.get("long_description")
                or item.get("item_description")
                or item.get("description")
                or item.get("specifications")
                or ""
            )
            result = self.normalizer.normalize(description)
            attrs = extract_attributes(result.normalized_text)
            normalized = dict(item)
            normalized["raw_text"] = result.raw_text
            normalized["normalized_text"] = result.normalized_text
            normalized["normalization_transformations"] = result.transformations
            normalized["normalized_attributes"] = attrs.as_dict()
            processed.append(normalized)
        return processed
