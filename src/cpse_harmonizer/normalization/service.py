"""Normalization pipeline for material rows extracted from tender pages."""

from __future__ import annotations

from typing import Any, Iterable

from cpse_harmonizer.normalization.attribute_extractor import extract_attributes


class NormalizationService:
    """Normalize extracted material rows before matching and NMC generation."""

    @staticmethod
    def process(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        for item in items:
            description = str(item.get("short_description") or item.get("long_description") or item.get("specifications") or "")
            attrs = extract_attributes(description)
            normalized = dict(item)
            normalized["normalized_attributes"] = attrs.as_dict()
            processed.append(normalized)
        return processed
