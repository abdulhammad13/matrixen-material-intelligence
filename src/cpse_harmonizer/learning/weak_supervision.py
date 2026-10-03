"""Conservative weak-pair labels sourced only from observable material evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from cpse_harmonizer.domain.models import (
    MaterialPair,
    MaterialRecord,
    PairLabel,
    PairRelation,
)
from cpse_harmonizer.matching.technical_compatibility import (
    CompatibilityClass,
    TechnicalCompatibilityChecker,
)
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes

_IDENTITY_FIELDS = {
    "transformer": {"voltage", "rating", "frequency", "phase", "vector_group"},
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


class WeakLabelGenerator:
    """Generate review-required weak labels; never writes to expert-gold storage."""

    def __init__(self, max_negative_neighbors: int = 8, max_exact_pairs_per_group: int = 500) -> None:
        if max_negative_neighbors < 1 or max_exact_pairs_per_group < 1:
            raise ValueError("Weak-label candidate limits must be positive.")
        self.max_negative_neighbors = max_negative_neighbors
        self.max_exact_pairs_per_group = max_exact_pairs_per_group
        self.checker = TechnicalCompatibilityChecker()

    def generate(self, materials: Iterable[MaterialRecord]) -> list[PairLabel]:
        records = list(materials)
        labels: dict[str, PairLabel] = {}
        exact_groups: dict[str, list[MaterialRecord]] = defaultdict(list)
        families: dict[str, list[MaterialRecord]] = defaultdict(list)
        for record in records:
            normalized = " ".join(
                (record.normalized_description or record.raw_description).casefold().split()
            )
            if normalized:
                exact_groups[normalized].append(record)
            family = extract_attributes(record.normalized_description or record.raw_description).family
            if family != "unknown":
                families[family].append(record)

        for group in exact_groups.values():
            organizations = {
                (record.source_organization or record.organization).casefold()
                for record in group
            }
            if len(organizations) < 2:
                continue
            ordered_group = sorted(group, key=lambda item: item.id)
            emitted = 0
            for index, left in enumerate(ordered_group):
                for right in ordered_group[index + 1 :]:
                    if (left.source_organization or left.organization).casefold() == (
                        right.source_organization or right.organization
                    ).casefold():
                        continue
                    self._add(
                        labels,
                        PairLabel(
                            pair=MaterialPair(material_a=left.id, material_b=right.id),
                            relation=PairRelation.EXACT,
                            label_source="weak_rule",
                            label_confidence=0.9,
                            reason_codes=["EXACT_NORMALIZED_TEXT", "CROSS_ORGANIZATION"],
                            review_status="PENDING",
                        ),
                    )
                    emitted += 1
                    if emitted >= self.max_exact_pairs_per_group:
                        break
                if emitted >= self.max_exact_pairs_per_group:
                    break

        for family, family_records in families.items():
            fields = _IDENTITY_FIELDS.get(family, set())
            if len(family_records) < 2 or not fields:
                continue
            indexed_values: dict[str, dict[str, list[MaterialRecord]]] = defaultdict(lambda: defaultdict(list))
            extracted: dict[str, dict[str, set[str]]] = {}
            for record in family_records:
                attrs = extract_attributes(record.raw_description)
                values = {
                    name: {
                        f"{attribute.normalized_value}|{attribute.unit or ''}".casefold()
                        for attribute in attrs.values(name)
                    }
                    for name in fields
                }
                extracted[record.id] = values
                for name, found_values in values.items():
                    for value in found_values:
                        indexed_values[name][value].append(record)

            for left in family_records:
                values = extracted[left.id]
                candidate_records: dict[str, MaterialRecord] = {}
                for name in sorted(fields):
                    current_values = values[name]
                    if not current_values:
                        continue
                    for value, bucket in sorted(indexed_values[name].items()):
                        if value in current_values:
                            continue
                        for right in bucket[: self.max_negative_neighbors]:
                            if right.id != left.id:
                                candidate_records[right.id] = right
                        if len(candidate_records) >= self.max_negative_neighbors:
                            break
                    if len(candidate_records) >= self.max_negative_neighbors:
                        break
                for right in sorted(candidate_records.values(), key=lambda item: item.id):
                    result = self.checker.check(left.raw_description, right.raw_description)
                    if result.classification != CompatibilityClass.HARD_CONFLICT:
                        continue
                    self._add(
                        labels,
                        PairLabel(
                            pair=MaterialPair(material_a=left.id, material_b=right.id),
                            relation=PairRelation.NOT_EQUIVALENT,
                            label_source="weak_rule",
                            label_confidence=0.65,
                            reason_codes=["RULE_HARD_TECHNICAL_CONFLICT"] + [
                                reason.split(":", 1)[0].upper().replace(" ", "_")
                                for reason in result.conflicts
                            ],
                            review_status="PENDING",
                            notes="Weak negative; requires expert adjudication.",
                        ),
                    )
        return sorted(labels.values(), key=lambda label: label.pair.id)

    @staticmethod
    def _add(labels: dict[str, PairLabel], label: PairLabel) -> None:
        labels.setdefault(label.pair.id, label)
