"""Persistence helpers for source artifacts and material records."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select

from cpse_harmonizer.domain.models import MaterialAttribute, MaterialRecord
from cpse_harmonizer.persistence.database import (
    Database,
    MaterialAttributeRow,
    MaterialRow,
    SourceArtifactRow,
)


def _chunks(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


class MaterialRepository:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database or Database()
        self.database.initialize()

    def save_many(self, materials: Iterable[MaterialRecord]) -> int:
        values = {material.id: material for material in materials}
        if not values:
            return 0
        with self.database.sessions.begin() as session:
            identifiers = list(values)
            artifact_ids = sorted(
                {material.source_artifact.artifact_id for material in values.values()}
            )
            existing_artifacts = {
                row.id: row
                for chunk in _chunks(artifact_ids)
                for row in session.scalars(
                    select(SourceArtifactRow).where(SourceArtifactRow.id.in_(chunk))
                )
            }
            existing_materials = {
                row.id: row
                for chunk in _chunks(identifiers)
                for row in session.scalars(select(MaterialRow).where(MaterialRow.id.in_(chunk)))
            }
            artifact_rows: list[SourceArtifactRow] = []
            material_rows: list[MaterialRow] = []
            attribute_rows: list[MaterialAttributeRow] = []
            for material in values.values():
                artifact = material.source_artifact
                if artifact.artifact_id not in existing_artifacts:
                    artifact_rows.append(
                        SourceArtifactRow(
                            id=artifact.artifact_id,
                            source_system=artifact.source_system,
                            source_organization=artifact.source_organization,
                            source_record_id=artifact.source_record_id,
                            source_url=artifact.source_url,
                            source_document=artifact.source_document,
                            source_hash=artifact.source_hash,
                            retrieved_at=artifact.retrieved_at,
                            metadata_json={
                                "source_page": artifact.source_page,
                                "source_section": artifact.source_section,
                                "parser_version": artifact.parser_version,
                                "schema_version": artifact.schema_version,
                                "terms_url": artifact.terms_url,
                                "license_note": artifact.license_note,
                                **material.metadata,
                            },
                        )
                    )
                    existing_artifacts[artifact.artifact_id] = artifact_rows[-1]
                row = existing_materials.get(material.id)
                if row is None:
                    row = MaterialRow(
                        id=material.id,
                        source_artifact_id=artifact.artifact_id,
                        raw_description=material.raw_description,
                    )
                    material_rows.append(row)
                    existing_materials[material.id] = row
                row.source_artifact_id = artifact.artifact_id
                row.raw_description = material.raw_description
                row.normalized_description = material.normalized_description
                row.material_code = material.material_code
                row.organization = material.organization or material.source_organization
                row.plant = material.plant
                row.metadata_json = material.metadata
                attribute_rows.extend(
                    MaterialAttributeRow(
                        material_id=material.id,
                        attribute_name=attribute.attribute_name,
                        value=str(attribute.value),
                        normalized_value=str(
                            attribute.normalized_value
                            if attribute.normalized_value is not None
                            else attribute.value
                        ),
                        unit=attribute.unit or "",
                        dimension=attribute.dimension or "",
                        evidence={
                            "source_span": list(attribute.source_span)
                            if attribute.source_span
                            else None,
                            "method": attribute.method,
                            "confidence": attribute.confidence,
                            "source_artifact_id": attribute.source_artifact_id,
                            "typed_value": attribute.value,
                            "typed_normalized_value": (
                                attribute.normalized_value
                                if attribute.normalized_value is not None
                                else attribute.value
                            ),
                        },
                    )
                    for attribute in material.attributes
                )
            for chunk in _chunks(identifiers):
                session.execute(
                    delete(MaterialAttributeRow).where(MaterialAttributeRow.material_id.in_(chunk))
                )
            session.add_all(artifact_rows + material_rows + attribute_rows)
        return len(values)

    def get(self, material_id: str) -> MaterialRecord | None:
        with self.database.sessions() as session:
            row = session.get(MaterialRow, material_id)
            if row is None:
                return None
            artifact = session.get(SourceArtifactRow, row.source_artifact_id)
            if artifact is None:
                raise RuntimeError(
                    f"Material {material_id} references missing source artifact "
                    f"{row.source_artifact_id}."
                )
            attributes: list[MaterialAttributeRow] = list(
                session.scalars(
                    select(MaterialAttributeRow).where(
                        MaterialAttributeRow.material_id == material_id
                    )
                ).all()
            )
            return self._record(row, artifact, attributes)

    def list(self, limit: int = 100_000) -> list[MaterialRecord]:
        if limit < 1 or limit > 500_000:
            raise ValueError("Material list limit must be between 1 and 500000.")
        with self.database.sessions() as session:
            rows = session.execute(
                select(MaterialRow, SourceArtifactRow)
                .join(SourceArtifactRow, MaterialRow.source_artifact_id == SourceArtifactRow.id)
                .order_by(MaterialRow.id)
                .limit(limit)
            ).all()
            identifiers = [row.id for row, _ in rows]
            attributes = []
            for offset in range(0, len(identifiers), 500):
                attributes.extend(
                    session.scalars(
                        select(MaterialAttributeRow).where(
                            MaterialAttributeRow.material_id.in_(identifiers[offset : offset + 500])
                        )
                    ).all()
                )
        attributes_by_id: dict[str, list[MaterialAttributeRow]] = {}
        for attribute in attributes:
            attributes_by_id.setdefault(attribute.material_id, []).append(attribute)
        return [
            self._record(row, artifact, attributes_by_id.get(row.id, [])) for row, artifact in rows
        ]

    @staticmethod
    def _record(
        row: MaterialRow,
        artifact: SourceArtifactRow,
        attributes: Iterable[MaterialAttributeRow],
    ) -> MaterialRecord:
        artifact_metadata = artifact.metadata_json or {}
        return MaterialRecord(
            id=row.id,
            source_system=artifact.source_system,
            source_organization=artifact.source_organization,
            source_record_id=artifact.source_record_id,
            source_url=artifact.source_url,
            source_document=artifact.source_document,
            source_hash=artifact.source_hash,
            retrieved_at=artifact.retrieved_at,
            source_page=artifact_metadata.get("source_page"),
            source_section=artifact_metadata.get("source_section", ""),
            parser_version=artifact_metadata.get("parser_version", "nummf-parser-0.1"),
            schema_version=artifact_metadata.get("schema_version", "1"),
            material_code=row.material_code,
            organization=row.organization,
            plant=row.plant,
            raw_description=row.raw_description,
            normalized_description=row.normalized_description,
            attributes=[
                MaterialAttribute(
                    attribute_name=attribute.attribute_name,
                    value=attribute.evidence.get("typed_value", attribute.value),
                    normalized_value=attribute.evidence.get(
                        "typed_normalized_value", attribute.normalized_value
                    ),
                    unit=attribute.unit or None,
                    dimension=attribute.dimension or None,
                    source_span=tuple(attribute.evidence["source_span"])
                    if attribute.evidence.get("source_span")
                    else None,
                    method=attribute.evidence.get("method", "rule"),
                    confidence=attribute.evidence.get("confidence", 1.0),
                    source_artifact_id=attribute.evidence.get("source_artifact_id"),
                )
                for attribute in attributes
            ],
            metadata=dict(row.metadata_json or {}),
        )
