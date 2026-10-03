"""Explainable pair features and uncalibrated ranking scores."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from cpse_harmonizer.domain.models import MatchDecision, MaterialPair, stable_id
from cpse_harmonizer.extraction.embedding_service import EmbeddingService
from cpse_harmonizer.matching.technical_compatibility import (
    CompatibilityClass,
    TechnicalCompatibilityChecker,
)
from cpse_harmonizer.normalization.attribute_extractor import MaterialAttributes, extract_attributes
from cpse_harmonizer.normalization.uom_pint import is_convertible

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


@dataclass(frozen=True, slots=True)
class PairFeatures:
    lexical_similarity: float
    dense_similarity: float | None
    cross_encoder_score: float | None
    item_family_agreement: float
    attribute_agreement: float
    attribute_conflicts: float
    uom_compatibility: float
    standard_compatibility: float
    hsn_compatibility: float | None
    manufacturer_compatibility: float | None
    numeric_proximity: float
    technical_hard_conflicts: int


class PairScorer:
    """Produce ranking features; no output is called a probability or approved match."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        cross_encoder: Callable[[str, str], float] | None = None,
        compatibility_checker: TechnicalCompatibilityChecker | None = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.cross_encoder = cross_encoder
        self.compatibility_checker = compatibility_checker or TechnicalCompatibilityChecker()

    def score(
        self,
        material_a: str,
        material_b: str,
        *,
        material_a_id: str | None = None,
        material_b_id: str | None = None,
        hsn_a: str | None = None,
        hsn_b: str | None = None,
        manufacturer_a: str | None = None,
        manufacturer_b: str | None = None,
    ) -> tuple[MatchDecision, PairFeatures]:
        left, right = extract_attributes(material_a), extract_attributes(material_b)
        compatibility = self.compatibility_checker.check(
            material_a,
            material_b,
            left_attributes=left,
            right_attributes=right,
        )
        features = self._features(
            material_a,
            material_b,
            left,
            right,
            compatibility,
            hsn_a,
            hsn_b,
            manufacturer_a,
            manufacturer_b,
        )
        if compatibility.classification == CompatibilityClass.HARD_CONFLICT:
            score = 0.0
        else:
            components = [
                (features.lexical_similarity, 0.30),
                (features.item_family_agreement, 0.10),
                (features.attribute_agreement, 0.25),
                (features.numeric_proximity, 0.15),
                (features.standard_compatibility, 0.10),
            ]
            if features.dense_similarity is not None:
                components.append((max(0.0, features.dense_similarity), 0.10))
            if features.cross_encoder_score is not None:
                components.append((features.cross_encoder_score, 0.10))
            total_weight = sum(weight for _, weight in components)
            score = sum(value * weight for value, weight in components) / total_weight if total_weight else 0.0

        id_a = material_a_id or stable_id("query", " ".join(material_a.casefold().split()))
        id_b = material_b_id or stable_id("query", " ".join(material_b.casefold().split()))
        if id_a == id_b:
            id_b = stable_id("query", id_b, "right")
        rationale = [
            f"Technical compatibility: {compatibility.classification.value}.",
            f"Lexical overlap: {features.lexical_similarity:.3f}.",
        ]
        rationale.extend(compatibility.reasons)
        decision = MatchDecision(
            pair=MaterialPair(material_a=id_a, material_b=id_b),
            score=round(float(score), 6),
            calibrated_probability=None,
            confidence_band="UNVALIDATED_SCORE",
            compatibility=compatibility.classification.value,
            rationale=rationale,
            requires_human_review=True,
        )
        return decision, features

    def _features(
        self,
        text_a: str,
        text_b: str,
        a: MaterialAttributes,
        b: MaterialAttributes,
        compatibility,
        hsn_a: str | None,
        hsn_b: str | None,
        manufacturer_a: str | None,
        manufacturer_b: str | None,
    ) -> PairFeatures:
        tokens_a, tokens_b = set(_TOKEN.findall(text_a.casefold())), set(_TOKEN.findall(text_b.casefold()))
        lexical = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
        dense = self.embedding_service.similarity(text_a, text_b) if self.embedding_service else None
        cross = self.cross_encoder(text_a, text_b) if self.cross_encoder else None
        if cross is not None and not 0 <= cross <= 1:
            raise ValueError("Cross-encoder score must be in the [0, 1] range.")

        family_agreement = float(a.family != "unknown" and a.family == b.family)
        shared = set(item.attribute_name for item in a.attributes) & set(item.attribute_name for item in b.attributes)
        agreed = sum(
            1
            for name in shared
            if TechnicalCompatibilityChecker._values(a, name)
            == TechnicalCompatibilityChecker._values(b, name)
        )
        conflicts = sum(
            1
            for name in shared
            if TechnicalCompatibilityChecker._values(a, name).isdisjoint(
                TechnicalCompatibilityChecker._values(b, name)
            )
        )
        attribute_agreement = agreed / max(len(shared), 1)
        attribute_conflicts = conflicts / max(len(shared), 1)
        standards_a, standards_b = {value.casefold() for value in self._values(a, "standard")}, {value.casefold() for value in self._values(b, "standard")}
        standard = float(bool(standards_a & standards_b)) if standards_a and standards_b else 0.0
        uom_a, uom_b = self._unit_values(a), self._unit_values(b)
        uom = float(bool(uom_a and uom_b) and any(
            x == y or is_convertible(x, y) for x in uom_a for y in uom_b
        ))
        numeric_a, numeric_b = self._numeric_values(a), self._numeric_values(b)
        shared_numeric = set(numeric_a) & set(numeric_b)
        numeric_values = [
            max(
                1.0 / (1.0 + abs(left - right) / max(abs(left), abs(right), 1.0))
                for left in numeric_a[name]
                for right in numeric_b[name]
            )
            for name in shared_numeric
        ]
        numeric = sum(numeric_values) / len(numeric_values) if numeric_values else 0.0
        hsn = None if not hsn_a or not hsn_b else float(hsn_a.strip() == hsn_b.strip())
        manufacturer = None if not manufacturer_a or not manufacturer_b else float(
            manufacturer_a.casefold().strip() == manufacturer_b.casefold().strip()
        )
        return PairFeatures(
            lexical_similarity=lexical,
            dense_similarity=dense,
            cross_encoder_score=cross,
            item_family_agreement=family_agreement,
            attribute_agreement=attribute_agreement,
            attribute_conflicts=attribute_conflicts,
            uom_compatibility=uom,
            standard_compatibility=standard,
            hsn_compatibility=hsn,
            manufacturer_compatibility=manufacturer,
            numeric_proximity=numeric,
            technical_hard_conflicts=len(compatibility.conflicts),
        )

    @staticmethod
    def _values(attributes: MaterialAttributes, name: str) -> set[str]:
        return {
            str(item.normalized_value if item.normalized_value is not None else item.value)
            for item in attributes.values(name)
        }

    @classmethod
    def _unit_values(cls, attributes: MaterialAttributes) -> set[str]:
        return {item.unit for item in attributes.attributes if item.unit and item.attribute_name in {"nominal_diameter", "cross_section"}}

    @classmethod
    def _numeric_values(cls, attributes: MaterialAttributes) -> dict[str, list[float]]:
        fields = {"voltage", "rating", "nominal_diameter", "cross_section", "wall_thickness"}
        values: dict[str, list[float]] = {}
        for item in attributes.attributes:
            if item.attribute_name not in fields or item.normalized_value is None:
                continue
            values.setdefault(item.attribute_name, []).append(float(item.normalized_value))
        return values
