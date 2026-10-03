"""Layer 2 normalization: regex-based material attribute extraction.

This module extracts common industrial fields (voltage, rating, grade, standards,
UoM, winding, cooling, efficiency and related metadata) from a material
description string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MaterialAttributes:
    """Structured attributes extracted from a descriptive material string."""

    voltage_kv: float | None = None
    rating_kva: float | None = None
    material_grade: str | None = None
    standard: str | None = None
    uom: str | None = None
    winding: str | None = None
    cooling: str | None = None
    efficiency: float | None = None
    item_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "voltage_kv": self.voltage_kv,
            "rating_kva": self.rating_kva,
            "material_grade": self.material_grade,
            "standard": self.standard,
            "uom": self.uom,
            "winding": self.winding,
            "cooling": self.cooling,
            "efficiency": self.efficiency,
            "item_type": self.item_type,
        }
        data.update(self.raw)
        return data


class AttributeExtractor:
    """Regex-based extraction engine for material text descriptions."""

    _VOLTAGE_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:kv|kV|kilo[- ]?volt|kilovolt)")
    _RATING_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:kva|mva|kW|kw)", re.IGNORECASE)
    _STANDARD_RE = re.compile(r"(?:IS|IEC|BIS|ASTM|API|ANSI)\s*[-\s]*\d+[A-Za-z0-9/.-]*")
    _GRADE_RE = re.compile(r"(?:gr\.?\s*[- ]?\w+|grade\s*[- ]?\w+|[A-Z]+\d+|SS\s*\d+|MS\s*\d+)", re.IGNORECASE)
    _UOM_RE = re.compile(r"\b(?:mm|cm|m|kg|g|ton|tonne|ltr|l|kl|m3|sqm|mm2|m2|kv|v|a|amp|kva|mva)\b", re.IGNORECASE)
    _WINDING_RE = re.compile(r"\b(?:delta|star|wye|auto[- ]?transformer|double[- ]?winding|three[- ]?winding)\b", re.IGNORECASE)
    _COOLING_RE = re.compile(r"\b(?:oil|air|water|forced[- ]?air|natural[- ]?air|ONAN|ONAF|ODAF|OFAF)\b", re.IGNORECASE)

    def extract(self, text: str) -> MaterialAttributes:
        description = str(text or "")
        lower = description.lower()
        voltage = self._parse_float(self._VOLTAGE_RE.search(description))
        rating = self._parse_float(self._RATING_RE.search(description))
        standard = self._STANDARD_RE.search(description)
        grade = self._GRADE_RE.search(description)
        uom = self._UOM_RE.search(description)
        winding = self._WINDING_RE.search(description)
        cooling = self._COOLING_RE.search(description)

        return MaterialAttributes(
            voltage_kv=float(voltage) if voltage is not None else None,
            rating_kva=float(rating) if rating is not None else None,
            material_grade=(grade.group(0).strip() if grade else None),
            standard=(standard.group(0).strip() if standard else None),
            uom=(uom.group(0).strip() if uom else None),
            winding=(winding.group(0).strip() if winding else None),
            cooling=(cooling.group(0).strip() if cooling else None),
            efficiency=self._infer_efficiency(lower),
            item_type=self._infer_item_type(lower),
            raw={
                "raw_text": description,
                "normalized_text": lower,
            },
        )

    @staticmethod
    def _parse_float(match: re.Match[str] | None) -> float | None:
        if match is None:
            return None
        value = match.group("value")
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _infer_efficiency(text: str) -> float | None:
        match = re.search(r"(?:efficiency|eff\.|η)\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*%", text)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _infer_item_type(text: str) -> str | None:
        mapping = {
            "valve": ["valve"],
            "pump": ["pump"],
            "transformer": ["transformer", "xmer", "trf"],
            "cable": ["cable"],
            "pipe": ["pipe"],
            "flange": ["flange"],
            "gasket": ["gasket"],
            "tank": ["tank", "vessel", "drum"],
            "instrument": ["instrument", "transmitter", "gauge", "meter"],
        }
        for item_type, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                return item_type
        return None


def extract_attributes(text: str) -> MaterialAttributes:
    """Convenience helper returning the extracted attributes bundle."""
    return AttributeExtractor().extract(text)
