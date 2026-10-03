"""SQLAlchemy persistence with SQLite development default and PostgreSQL URL support."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class SourceArtifactRow(Base):
    __tablename__ = "source_artifacts"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(200), index=True)
    source_organization: Mapped[str] = mapped_column(String(200), default="")
    source_record_id: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_document: Mapped[str] = mapped_column(Text, default="")
    source_hash: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class MaterialRow(Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("source_artifacts.id"), index=True)
    raw_description: Mapped[str] = mapped_column(Text)
    normalized_description: Mapped[str] = mapped_column(Text, default="")
    material_code: Mapped[str] = mapped_column(String(200), default="", index=True)
    organization: Mapped[str] = mapped_column(String(200), default="", index=True)
    plant: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MaterialAttributeRow(Base):
    __tablename__ = "material_attributes"
    __table_args__ = (
        UniqueConstraint(
            "material_id", "attribute_name", "normalized_value", name="uq_material_attribute"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id"), index=True)
    attribute_name: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(50), default="")
    dimension: Mapped[str] = mapped_column(String(50), default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CanonicalMaterialRow(Base):
    __tablename__ = "canonical_materials"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    family: Mapped[str] = mapped_column(String(100), index=True)
    generated_description: Mapped[str] = mapped_column(Text)
    attribute_signature: Mapped[str] = mapped_column(Text, unique=True)
    template_version: Mapped[str] = mapped_column(String(50), default="canonical-v1")
    generation_method: Mapped[str] = mapped_column(String(50), default="structured-template")
    status: Mapped[str] = mapped_column(String(32), default="proposed")
    taxonomy: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class TaxonomyRow(Base):
    __tablename__ = "taxonomies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taxonomy: Mapped[str] = mapped_column(String(100), index=True)
    taxonomy_version: Mapped[str] = mapped_column(String(50), default="")
    taxonomy_code: Mapped[str] = mapped_column(String(100), index=True)
    taxonomy_name: Mapped[str] = mapped_column(Text)
    parent_code: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(Text, default="")
    hsn_sac_code: Mapped[str] = mapped_column(String(30), default="")


class NMCRegistryRow(Base):
    __tablename__ = "nmc_registry"

    nmc: Mapped[str] = mapped_column(String(100), primary_key=True)
    canonical_material_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_materials.id"), index=True
    )
    family: Mapped[str] = mapped_column(String(100), index=True)
    attribute_signature: Mapped[str] = mapped_column(Text, unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="proposed")
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    human_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str] = mapped_column(Text, default="")


class NMCMappingRow(Base):
    __tablename__ = "nmc_mappings"
    __table_args__ = (
        UniqueConstraint("nmc", "cpse", "legacy_material_code", "plant", name="uq_nmc_legacy_map"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nmc: Mapped[str] = mapped_column(ForeignKey("nmc_registry.nmc"), index=True)
    cpse: Mapped[str] = mapped_column(String(100), index=True)
    legacy_material_code: Mapped[str] = mapped_column(String(200), index=True)
    plant: Mapped[str] = mapped_column(String(200), default="")
    source_system: Mapped[str] = mapped_column(String(100))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(32), default="PROPOSED")
    mapping_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_version: Mapped[str] = mapped_column(String(100), default="")
    review_id: Mapped[str] = mapped_column(String(80), default="")


class MaterialPairRow(Base):
    __tablename__ = "material_pairs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    material_a: Mapped[str] = mapped_column(String(80), index=True)
    material_b: Mapped[str] = mapped_column(String(80), index=True)
    label_source: Mapped[str] = mapped_column(String(32), default="")
    relation: Mapped[str] = mapped_column(String(60), default="")
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)


class ReviewTaskRow(Base):
    __tablename__ = "review_tasks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    pair_id: Mapped[str] = mapped_column(ForeignKey("material_pairs.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    assigned_to: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(200), default="system")
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ReviewDecisionRow(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(200))
    reviewer_role: Mapped[str] = mapped_column(String(40))
    relation: Mapped[str] = mapped_column(String(60))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    checker_id: Mapped[str] = mapped_column(String(200), default="")
    checker_role: Mapped[str] = mapped_column(String(40), default="")
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(200), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    model_version: Mapped[str] = mapped_column(String(100), default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    output_hash: Mapped[str] = mapped_column(String(64), default="")
    previous_event_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelVersionRow(Base):
    __tablename__ = "model_versions"

    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    model_type: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvaluationRunRow(Base):
    __tablename__ = "evaluation_runs"

    run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(100))
    split_strategy: Mapped[str] = mapped_column(String(200))
    label_source: Mapped[str] = mapped_column(String(40))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Database:
    """Create an explicit persistent local or PostgreSQL SQLAlchemy database."""

    def __init__(self, url: str | None = None) -> None:
        self.url: str = (
            url or os.getenv("NUMMF_DATABASE_URL") or "sqlite:///data/processed/nummf.db"
        )
        connect_args: dict[str, Any] = {}
        if self.url.startswith("sqlite:///"):
            file_path = self.url.removeprefix("sqlite:///")
            if file_path != ":memory:":
                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            connect_args["check_same_thread"] = False
        self.engine = create_engine(self.url, connect_args=connect_args, future=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
