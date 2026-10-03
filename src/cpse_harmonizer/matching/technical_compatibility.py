"""Layer 5 matching: hard-constraint compatibility checks for material comparisons."""

from __future__ import annotations

from dataclasses import dataclass, field

from cpse_harmonizer.config import MAX_VOLTAGE_DIFF_FRACTION
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.uom_pint import is_convertible


@dataclass(slots=True)
class CompatibilityResult:
    compatible: bool
    score: float
    reasons: list[str] = field(default_factory=list)


class TechnicalCompatibilityChecker:
    """Apply hard constraints before a match is accepted as technically compatible."""

    def check(self, left: str, right: str) -> CompatibilityResult:
        reasons: list[str] = []
        left_attrs = extract_attributes(left)
        right_attrs = extract_attributes(right)

        if left_attrs.voltage_kv is not None and right_attrs.voltage_kv is not None:
            diff = abs(left_attrs.voltage_kv - right_attrs.voltage_kv)
            max_voltage = max(left_attrs.voltage_kv, right_attrs.voltage_kv)
            if max_voltage > 0 and diff / max_voltage > MAX_VOLTAGE_DIFF_FRACTION:
                reasons.append("Voltage tolerance exceeded")

        if left_attrs.standard and right_attrs.standard and left_attrs.standard != right_attrs.standard:
            reasons.append("Standard mismatch")

        if left_attrs.uom and right_attrs.uom and not is_convertible(left_attrs.uom, right_attrs.uom):
            reasons.append("UoM is not convertible")

        compatible = not reasons
        score = 1.0 if compatible else 0.0
        return CompatibilityResult(compatible=compatible, score=score, reasons=reasons)


def technical_compatibility(left: str, right: str) -> CompatibilityResult:
    return TechnicalCompatibilityChecker().check(left, right)
