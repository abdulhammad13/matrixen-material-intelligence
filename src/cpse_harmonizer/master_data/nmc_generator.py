"""CPSE-independent NMC proposals from structured canonical attribute signatures."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from cpse_harmonizer.normalization.attribute_extractor import MaterialAttributes, extract_attributes

_FAMILY_CODES = {
    "transformer": "TRF",
    "cable": "CAB",
    "valve": "VAL",
    "pipe": "PIP",
    "pump": "PMP",
    "bearing": "BRG",
    "motor": "MOT",
    "electrical_panel": "PNL",
    "flange_fitting": "FIT",
    "instrumentation": "INS",
}
_IDENTITY_ATTRIBUTES = {
    "transformer": {"voltage", "rating", "frequency", "phase", "vector_group", "cooling_type", "winding_material"},
    "cable": {"voltage", "cores", "cross_section", "conductor_material", "insulation", "armour"},
    "valve": {"valve_type", "nominal_diameter", "pressure_class", "material_grade", "end_connection", "actuation"},
    "pipe": {"nominal_diameter", "wall_thickness", "schedule", "material_grade", "standard"},
    "pump": {"rating", "material_grade", "standard"},
    "bearing": {"model", "material_grade"},
    "motor": {"rating", "voltage", "frequency", "phase"},
    "electrical_panel": {"voltage", "rating", "standard"},
    "flange_fitting": {"nominal_diameter", "pressure_class", "material_grade", "end_connection", "standard"},
    "instrumentation": {"model", "standard", "voltage"},
}


@dataclass(slots=True)
class NMCProposal:
    nmc: str
    family: str
    attribute_signature: str
    canonical_description: str
    status: str = "PROPOSED_REQUIRES_REVIEW"
    approval_status: str = "PENDING"
    collisions: list[str] = field(default_factory=list)


class NMCGenerator:
    """Generate a stable identity proposal; this class cannot approve or publish it."""

    def __init__(self, registry: dict[str, str] | None = None) -> None:
        self.registry = registry if registry is not None else {}

    def propose(
        self,
        description: str,
        *,
        attributes: MaterialAttributes | None = None,
        family: str | None = None,
    ) -> NMCProposal:
        text = str(description or "").strip()
        if not text:
            raise ValueError("Material description is required for NMC proposal.")
        extracted = attributes or extract_attributes(text)
        selected_family = family or extracted.family
        if selected_family == "unknown":
            raise ValueError("A recognized material family is required; NMC remains unverified.")

        allowed = _IDENTITY_ATTRIBUTES.get(selected_family, set())
        canonical_attributes: dict[str, set[tuple[str, str]]] = {}
        for attribute in extracted.attributes:
            if attribute.attribute_name not in allowed:
                continue
            value = str(attribute.normalized_value if attribute.normalized_value is not None else attribute.value).strip().upper()
            unit = (attribute.unit or "").upper()
            canonical_attributes.setdefault(attribute.attribute_name, set()).add((value, unit))
        if not canonical_attributes:
            raise ValueError("Insufficient structured identity attributes; NMC proposal requires human enrichment.")

        serializable = {
            name: sorted([{"value": value, "unit": unit} for value, unit in pairs], key=lambda part: (part["value"], part["unit"]))
            for name, pairs in sorted(canonical_attributes.items())
        }
        signature = json.dumps(
            {"family": selected_family, "attributes": serializable},
            sort_keys=True,
            separators=(",", ":"),
        )
        signature_digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20].upper()
        family_code = _FAMILY_CODES.get(selected_family, re.sub(r"[^A-Z0-9]", "", selected_family.upper())[:3] or "GEN")
        nmc = f"NMC-IND-{family_code}-{signature_digest}"
        canonical = self._canonical_description(selected_family, canonical_attributes)

        collisions: list[str] = []
        previous = self.registry.get(nmc)
        if previous is not None and previous != signature:
            collisions.append(nmc)
        else:
            self.registry[nmc] = signature
        return NMCProposal(
            nmc=nmc,
            family=selected_family,
            attribute_signature=signature,
            canonical_description=canonical,
            collisions=collisions,
        )

    def generate(self, description: str, cpse: str | None = None, plant: str | None = None) -> str:
        """Compatibility wrapper; CPSE and plant are deliberately not identity inputs."""
        del cpse, plant
        return self.propose(description).nmc

    @staticmethod
    def _canonical_description(
        family: str,
        attributes: dict[str, set[tuple[str, str]]],
    ) -> str:
        ordering = {
            "transformer": ("voltage", "rating", "winding_material", "cooling_type", "frequency", "vector_group"),
            "cable": ("voltage", "cores", "cross_section", "conductor_material", "insulation", "armour"),
            "valve": ("valve_type", "nominal_diameter", "pressure_class", "material_grade", "end_connection", "actuation"),
        }.get(family, tuple(sorted(attributes)))
        pieces = [family.upper().replace("_", " ")]
        for name in ordering:
            values = attributes.get(name)
            if not values:
                continue
            value, unit = sorted(values)[0]
            rendered = f"{value} {unit}".strip()
            pieces.append(f"{name.replace('_', ' ').upper()} {rendered}")
        return " | ".join(pieces)

    def assign(self, description: str, cpse: str | None = None, plant: str | None = None) -> str:
        return self.generate(description, cpse=cpse, plant=plant)


def generate_nmc(description: str, cpse: str | None = None, plant: str | None = None) -> str:
    """Compatibility helper for proposing, not approving, a CPSE-independent NMC."""
    return NMCGenerator().generate(description, cpse=cpse, plant=plant)
