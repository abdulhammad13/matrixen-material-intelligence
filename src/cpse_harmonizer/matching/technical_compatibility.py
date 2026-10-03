"""Family-aware compatibility checks that distinguish unknown from compatible."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from cpse_harmonizer.normalization.attribute_extractor import MaterialAttributes, extract_attributes


class CompatibilityClass(StrEnum):
    MATCH = "MATCH"
    SOFT_MISMATCH = "SOFT_MISMATCH"
    HARD_CONFLICT = "HARD_CONFLICT"
    UNKNOWN = "UNKNOWN"


_IDENTITY_FIELDS = {
    "transformer": {"voltage", "rating", "frequency", "phase", "vector_group", "cooling_type", "winding_material"},
    "cable": {"voltage", "cores", "cross_section", "conductor_material", "insulation"},
    "valve": {"valve_type", "nominal_diameter", "pressure_class", "material_grade", "end_connection"},
    "pipe": {"nominal_diameter", "wall_thickness", "schedule", "material_grade"},
    "pump": {"rating", "material_grade"},
    "bearing": {"model", "material_grade"},
    "motor": {"rating", "voltage", "frequency", "phase"},
    "electrical_panel": {"voltage", "rating"},
    "flange_fitting": {"nominal_diameter", "pressure_class", "material_grade", "end_connection"},
    "instrumentation": {"model", "standard"},
}


@dataclass(slots=True)
class CompatibilityResult:
    compatible: bool
    score: float
    reasons: list[str] = field(default_factory=list)
    classification: CompatibilityClass = CompatibilityClass.UNKNOWN
    conflicts: list[str] = field(default_factory=list)
    unknown_attributes: list[str] = field(default_factory=list)


class TechnicalCompatibilityChecker:
    """Compare like-family identity attributes and fail closed on missing evidence."""

    def check(
        self,
        left: str,
        right: str,
        *,
        left_attributes: MaterialAttributes | None = None,
        right_attributes: MaterialAttributes | None = None,
    ) -> CompatibilityResult:
        a = left_attributes or extract_attributes(left)
        b = right_attributes or extract_attributes(right)
        if a.family != "unknown" and b.family != "unknown" and a.family != b.family:
            reason = f"Material family conflict: {a.family} versus {b.family}."
            return CompatibilityResult(False, 0.0, [reason], CompatibilityClass.HARD_CONFLICT, [reason])
        if a.family == "unknown" or b.family == "unknown":
            return CompatibilityResult(
                False,
                0.0,
                ["Material family is not established from both descriptions."],
                CompatibilityClass.UNKNOWN,
                unknown_attributes=["family"],
            )

        fields = _IDENTITY_FIELDS.get(a.family, set())
        hard_conflicts: list[str] = []
        soft_mismatches: list[str] = []
        unknown: list[str] = []
        for name in sorted(fields):
            left_values = self._values(a, name)
            right_values = self._values(b, name)
            if not left_values or not right_values:
                unknown.append(name)
                continue
            if left_values.isdisjoint(right_values):
                reason = f"{name.replace('_', ' ')} differs: {', '.join(sorted(left_values))} vs {', '.join(sorted(right_values))}."
                if name in {"standard", "model"}:
                    soft_mismatches.append(reason)
                else:
                    hard_conflicts.append(reason)

        if hard_conflicts:
            return CompatibilityResult(
                False,
                0.0,
                hard_conflicts + soft_mismatches,
                CompatibilityClass.HARD_CONFLICT,
                hard_conflicts,
                unknown,
            )
        if soft_mismatches:
            return CompatibilityResult(
                False,
                0.5,
                soft_mismatches,
                CompatibilityClass.SOFT_MISMATCH,
                [],
                unknown,
            )
        if unknown:
            return CompatibilityResult(
                False,
                0.0,
                ["Insufficient evidence to establish technical compatibility."],
                CompatibilityClass.UNKNOWN,
                [],
                unknown,
            )
        return CompatibilityResult(
            True,
            1.0,
            ["All extracted identity-defining attributes agree."],
            CompatibilityClass.MATCH,
        )

    @staticmethod
    def _values(attributes: MaterialAttributes, name: str) -> set[str]:
        return {
            f"{attribute.normalized_value}|{attribute.unit or ''}".casefold()
            for attribute in attributes.values(name)
        }


def technical_compatibility(left: str, right: str) -> CompatibilityResult:
    return TechnicalCompatibilityChecker().check(left, right)
