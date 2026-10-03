"""Deterministic, evidence-spanned extraction for industrial specifications."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cpse_harmonizer.domain.models import MaterialAttribute

_FAMILY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("transformer", re.compile(r"\b(?:transformer|xmer|trf)\b", re.I)),
    ("cable", re.compile(r"\b(?:cable|xlpe|pilc)\b", re.I)),
    ("valve", re.compile(r"\b(?:valve|vlv|v\.?l\.?)\b", re.I)),
    ("pipe", re.compile(r"\b(?:pipe|tube|tubing)\b", re.I)),
    ("pump", re.compile(r"\b(?:pump|pmp)\b", re.I)),
    ("bearing", re.compile(r"\b(?:bearing|brg)\b", re.I)),
    ("motor", re.compile(r"\b(?:motor|motorized)\b", re.I)),
    ("electrical_panel", re.compile(r"\b(?:switchgear|switchboard|panel|mcc|pcc)\b", re.I)),
    ("flange_fitting", re.compile(r"\b(?:flange|fitting|elbow|reducer|tee)\b", re.I)),
    (
        "instrumentation",
        re.compile(r"\b(?:transmitter|gauge|sensor|instrument|meter|thermocouple|rtd)\b", re.I),
    ),
)

_PATTERNS: tuple[tuple[str, re.Pattern[str], str | None, str | None], ...] = (
    (
        "voltage",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>k\s*v|kv|kilovolts?|v|volts?)\b", re.I),
        "voltage",
        None,
    ),
    (
        "rating",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kva|mva|kw|mw|hp)\b", re.I),
        "power",
        None,
    ),
    (
        "frequency",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>hz)\b", re.I),
        "frequency",
        None,
    ),
    (
        "current_rating",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ka|a|amp|amps|ampere)\b", re.I),
        "current",
        None,
    ),
    ("phase", re.compile(r"\b(?P<value>single|three|1|3)\s*[- ]?phase\b", re.I), None, None),
    ("cores", re.compile(r"\b(?P<value>\d+)\s*(?:core|cores|c)\b", re.I), None, None),
    (
        "cross_section",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm2|mm²|sq\.?\s*mm)\b", re.I),
        "area",
        None,
    ),
    (
        "nominal_diameter",
        re.compile(
            r"\b(?:dn\s*)?(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|inch|inches|in\b|\"|nb|nps)\b",
            re.I,
        ),
        "length",
        None,
    ),
    (
        "wall_thickness",
        re.compile(
            r"\b(?:thk|thickness|wall)\s*[:=]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm)\b", re.I
        ),
        "length",
        None,
    ),
    ("schedule", re.compile(r"\b(?:schedule|sch\.?)\s*(?P<value>\d{1,3}[s]?)\b", re.I), None, None),
    (
        "pressure_class",
        re.compile(
            r"\b(?P<value>class\s*\d{2,4}|pn\s*\d{1,3}|150#|300#|600#|900#|1500#|2500#)\b", re.I
        ),
        None,
        None,
    ),
    (
        "valve_type",
        re.compile(
            r"\b(?P<value>ball|gate|globe|butterfly|check|control|safety|relief|needle|plug|diaphragm)\s+valve\b",
            re.I,
        ),
        None,
        None,
    ),
    (
        "standard",
        re.compile(
            r"\b(?P<value>(?:IS|IEC|BIS|ASTM|API|ANSI|ASME|DIN|BS|EN|ISO)\s*[-:]?\s*\d+[A-Z0-9/.-]*)\b",
            re.I,
        ),
        None,
        None,
    ),
    (
        "vector_group",
        re.compile(
            r"\b(?P<value>(?:D|Y|Z|I|d|y|z|i){1,3}\s*(?:yn|n)?\s*[-]?\s*(?:d|y|z|i){1,3}\s*\d{1,2})\b",
            re.I,
        ),
        None,
        None,
    ),
    ("cooling_type", re.compile(r"\b(?P<value>ONAN|ONAF|OFAF|ODAF|AN|AF|WF)\b", re.I), None, None),
    (
        "winding_material",
        re.compile(r"\b(?P<value>copper|aluminium|aluminum)\s+(?:winding|wound)\b", re.I),
        None,
        None,
    ),
    (
        "conductor_material",
        re.compile(r"\b(?P<value>copper|aluminium|aluminum|al)\b", re.I),
        None,
        None,
    ),
    (
        "insulation",
        re.compile(r"\b(?P<value>XLPE|PVC|EPR|PILC|paper insulated)\b", re.I),
        None,
        None,
    ),
    ("armour", re.compile(r"\b(?P<value>armou?red|unarmou?red|SWA|AWA)\b", re.I), None, None),
    (
        "end_connection",
        re.compile(
            r"\b(?P<value>flanged|flange|butt[- ]?weld|socket[- ]?weld|threaded|NPT|BSP|wafer|lug)\b",
            re.I,
        ),
        None,
        None,
    ),
    (
        "actuation",
        re.compile(
            r"\b(?P<value>manual|pneumatic|electric|hydraulic|motor[- ]operated)\s*(?:actuator|operated)?\b",
            re.I,
        ),
        None,
        None,
    ),
    (
        "manufacturer_part",
        re.compile(
            r"\b(?:part\s*(?:no|number)|mfr\.?\s*part)\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9./_-]{2,})",
            re.I,
        ),
        None,
        None,
    ),
    (
        "model",
        re.compile(r"\b(?:model|type)\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9./_-]{1,})", re.I),
        None,
        None,
    ),
    (
        "manufacturer",
        re.compile(
            r"\b(?:make|manufacturer|mfr)\s*[:#-]\s*(?P<value>[A-Z][A-Z0-9& .'-]{1,40}?)(?=,|;|$)",
            re.I,
        ),
        None,
        None,
    ),
    ("hsn_sac", re.compile(r"\b(?:HSN|SAC)\s*[:#-]?\s*(?P<value>\d{4,8})\b", re.I), None, None),
    (
        "flow_rate",
        re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m3/?h|m³/?h|lpm|gpm)\b", re.I),
        "volume_flow",
        None,
    ),
    (
        "head",
        re.compile(
            r"\b(?:head)\s*[:=]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m|metres?|meters?)\b", re.I
        ),
        "length",
        None,
    ),
    (
        "material_grade",
        re.compile(
            r"\b(?P<value>(?:A\s*\d{2,4}(?:\s+GR\.?\s*[A-Z0-9]+)?|A\d{2,4}\s+TP\d{3}|SS\s*3\d{2}[A-Z]?|WCB|WC6|WC9|CF8M?|F\d{2,3}|GR\.?\s*[A-Z0-9]+|GRADE\s+[A-Z0-9]+))\b",
            re.I,
        ),
        None,
        None,
    ),
)


@dataclass(slots=True)
class MaterialAttributes:
    """Compatibility view plus a general, evidence-carrying attribute list."""

    voltage_kv: float | None = None
    rating_kva: float | None = None
    material_grade: str | None = None
    standard: str | None = None
    uom: str | None = None
    winding: str | None = None
    cooling: str | None = None
    efficiency: float | None = None
    item_type: str | None = None
    attributes: list[MaterialAttribute] = field(default_factory=list)
    family: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)

    def values(self, name: str) -> list[MaterialAttribute]:
        return [attribute for attribute in self.attributes if attribute.attribute_name == name]

    def as_dict(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "family": self.family,
            "voltage_kv": self.voltage_kv,
            "rating_kva": self.rating_kva,
            "material_grade": self.material_grade,
            "standard": self.standard,
            "uom": self.uom,
            "winding": self.winding,
            "cooling": self.cooling,
            "efficiency": self.efficiency,
            "item_type": self.item_type,
            "attributes": [attribute.model_dump(mode="json") for attribute in self.attributes],
        }
        values.update(self.raw)
        return values


class AttributeExtractor:
    """Extract patterns without inferring technical facts absent from the text."""

    def extract(self, text: str) -> MaterialAttributes:
        description = str(text or "")
        family = next(
            (name for name, pattern in _FAMILY_PATTERNS if pattern.search(description)), "unknown"
        )
        found: list[MaterialAttribute] = []
        seen: set[tuple[str, str, int, int]] = set()
        for name, pattern, dimension, _ in _PATTERNS:
            for match in pattern.finditer(description):
                value = match.groupdict().get("value", "").strip()
                unit = match.groupdict().get("unit")
                normalized = self._normalize_value(name, value, unit)
                key = (name, str(normalized), match.start(), match.end())
                if key in seen or not value:
                    continue
                seen.add(key)
                found.append(
                    MaterialAttribute(
                        attribute_name=name,
                        value=value,
                        normalized_value=normalized,
                        unit=self._canonical_unit(unit, name),
                        dimension=dimension,
                        source_span=(match.start(), match.end()),
                        method="regex",
                        confidence=0.9,
                    )
                )

        efficiency_match = re.search(
            r"(?:efficiency|eff\.|η)\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*%", description, re.I
        )
        if efficiency_match:
            found.append(
                self._make_attribute(
                    "efficiency",
                    efficiency_match.group(1),
                    float(efficiency_match.group(1)),
                    "%",
                    efficiency_match.span(),
                )
            )
        uom_match = re.search(
            r"\b(?:nos?\.?|sets?|kg|kgs|mt|tonne|mtr|meter|metre|km|litre|ltr|ea|each)\b",
            description,
            re.I,
        )
        uom = self._canonical_unit(uom_match.group(0)) if uom_match else None
        item_type = family if family != "unknown" else None

        voltage = self._first_numeric(found, "voltage")
        rating_attribute = next((item for item in found if item.attribute_name == "rating"), None)
        rating_kva = self._rating_to_kva(rating_attribute) if rating_attribute else None
        material_value = next(
            (a.value for a in found if a.attribute_name == "material_grade"), None
        )
        standard_value = next((a.value for a in found if a.attribute_name == "standard"), None)
        cooling_value = next((a.value for a in found if a.attribute_name == "cooling_type"), None)
        winding_value = next(
            (a.value for a in found if a.attribute_name == "winding_material"), None
        )
        material = str(material_value) if material_value is not None else None
        standard = str(standard_value) if standard_value is not None else None
        cooling = str(cooling_value) if cooling_value is not None else None
        winding = str(winding_value) if winding_value is not None else None

        return MaterialAttributes(
            voltage_kv=voltage,
            rating_kva=rating_kva,
            material_grade=material,
            standard=standard,
            uom=uom,
            winding=winding,
            cooling=cooling,
            efficiency=float(efficiency_match.group(1)) if efficiency_match else None,
            item_type=item_type,
            attributes=found,
            family=family,
            raw={"raw_text": description},
        )

    @staticmethod
    def _first_numeric(attributes: list[MaterialAttribute], name: str) -> float | None:
        for attribute in attributes:
            if attribute.attribute_name == name:
                try:
                    value = attribute.normalized_value
                    return float(value) if value is not None else None
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _rating_to_kva(rating: MaterialAttribute) -> float | None:
        try:
            normalized_value = rating.normalized_value
            if normalized_value is None:
                return None
            value = float(normalized_value)
            if rating.unit == "MVA":
                return value * 1000
            if rating.unit == "MW":
                return value * 1000
            if rating.unit in {"KVA", "KW"}:
                return value
            return None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _canonical_unit(unit: str | None, name: str = "") -> str | None:
        if not unit:
            return None
        token = re.sub(r"\s+", "", unit).upper()
        if name == "voltage":
            return "KV"
        if name == "rating":
            return "KVA" if token in {"KVA", "MVA"} else "KW" if token in {"KW", "MW"} else token
        return {
            "K V": "KV",
            "KV": "KV",
            "KVA": "KVA",
            "MVA": "MVA",
            "KW": "KW",
            "MW": "MW",
            "MM²": "MM2",
            "SQ.MM": "MM2",
            "MM": "MM",
            "MTR": "M",
            "METRE": "M",
            "METER": "M",
            "INCHES": "IN",
            "IN": "IN",
        }.get(token, token)

    @staticmethod
    def _normalize_value(name: str, value: str, unit: str | None) -> str | float:
        if name in {
            "voltage",
            "rating",
            "frequency",
            "cross_section",
            "nominal_diameter",
            "wall_thickness",
        }:
            try:
                numeric = float(value)
                token = re.sub(r"\s+", "", (unit or "").casefold())
                if name == "voltage" and token in {"v", "volt", "volts"}:
                    return numeric / 1000
                if name == "rating" and token in {"mva", "mw"}:
                    return numeric * 1000
                return numeric
            except ValueError:
                return value.upper()
        normalized = re.sub(r"\s+", " ", value).upper()
        if name == "pressure_class":
            normalized = re.sub(r"^CLASS\s*", "CLASS ", normalized)
            normalized = re.sub(r"^PN\s*", "PN ", normalized)
        return normalized

    @staticmethod
    def _make_attribute(
        name: str,
        value: str,
        normalized: str | float,
        unit: str | None,
        span: tuple[int, int],
    ) -> MaterialAttribute:
        return MaterialAttribute(
            attribute_name=name,
            value=value,
            normalized_value=normalized,
            unit=unit,
            source_span=span,
            method="regex",
            confidence=0.9,
        )


def extract_attributes(text: str) -> MaterialAttributes:
    """Convenience helper returning family and general engineering attributes."""
    return AttributeExtractor().extract(text)
