"""Provenance-preserving domain contracts for material harmonization."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _identity_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def stable_id(namespace: str, *parts: str) -> str:
    payload = json.dumps([namespace, *parts], ensure_ascii=False, separators=(",", ":"))
    return f"{namespace}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceArtifact(DomainModel):
    artifact_id: str = ""
    source_system: str
    source_organization: str = ""
    source_record_id: str = ""
    source_url: str = ""
    source_document: str = ""
    source_page: int | None = Field(default=None, ge=1)
    source_section: str = ""
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_hash: str = ""
    parser_version: str = "nummf-parser-0.1"
    schema_version: str = "1"
    license_note: str = ""
    terms_url: str = ""
    status: str = "available"

    @model_validator(mode="after")
    def assign_artifact_id(self) -> SourceArtifact:
        if not self.artifact_id:
            self.artifact_id = stable_id(
                "src",
                self.source_system,
                self.source_organization,
                self.source_record_id or self.source_url or self.source_document,
                self.source_hash,
            )
        return self


class MaterialAttribute(DomainModel):
    attribute_name: str = Field(min_length=1)
    value: str | int | float | bool
    normalized_value: str | int | float | bool | None = None
    unit: str | None = None
    dimension: str | None = None
    source_span: tuple[int, int] | None = None
    method: str = "rule"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_artifact_id: str | None = None


class MaterialRecord(DomainModel):
    id: str = ""
    source_system: str
    source_organization: str = ""
    source_record_id: str = ""
    source_url: str = ""
    source_document: str = ""
    source_page: int | None = Field(default=None, ge=1)
    source_section: str = ""
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_hash: str = ""
    parser_version: str = "nummf-parser-0.1"
    schema_version: str = "1"
    material_code: str = ""
    plant: str = ""
    raw_description: str
    normalized_description: str = ""
    quantity: float | None = None
    unit: str = ""
    organization: str = ""
    attributes: list[MaterialAttribute] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def assign_stable_identity(self) -> MaterialRecord:
        # The stable ID is tied to a fixed, minimal NFKC/case/whitespace
        # normalization of the source text, not to a replaceable pipeline version.
        normalized = _identity_text(self.raw_description)
        if not self.source_hash:
            self.source_hash = hashlib.sha256(self.raw_description.encode("utf-8")).hexdigest()
        if not self.id:
            self.id = stable_id(
                "mat",
                self.source_system,
                self.source_organization or self.organization,
                self.source_record_id or self.source_url or self.source_document,
                str(self.source_page or ""),
                self.source_section,
                normalized,
            )
        return self

    @property
    def source_artifact(self) -> SourceArtifact:
        return SourceArtifact(
            source_system=self.source_system,
            source_organization=self.source_organization or self.organization,
            source_record_id=self.source_record_id,
            source_url=self.source_url,
            source_document=self.source_document,
            source_page=self.source_page,
            source_section=self.source_section,
            retrieved_at=self.retrieved_at,
            source_hash=self.source_hash,
            parser_version=self.parser_version,
            schema_version=self.schema_version,
        )


class CanonicalMaterial(DomainModel):
    id: str = ""
    family: str
    generated_description: str
    attributes: list[MaterialAttribute] = Field(default_factory=list)
    attribute_source: str = "rule"
    template_version: str = "canonical-v1"
    generation_method: str = "structured-template"
    taxonomy: list[str] = Field(default_factory=list)
    taxonomy_version: str = ""
    status: str = "proposed"
    source_material_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def assign_id(self) -> CanonicalMaterial:
        if not self.id:
            signature = json.dumps(
                sorted(
                    (a.attribute_name, str(a.normalized_value or a.value), a.unit or "")
                    for a in self.attributes
                ),
                separators=(",", ":"),
            )
            self.id = stable_id("can", self.family.casefold(), signature)
        return self


class MaterialPair(DomainModel):
    id: str = ""
    material_a: str
    material_b: str

    @model_validator(mode="after")
    def assign_pair_id(self) -> MaterialPair:
        if self.material_a == self.material_b:
            raise ValueError("A material pair must contain two distinct material IDs")
        ordered = sorted((self.material_a, self.material_b))
        if not self.id:
            self.id = stable_id("pair", *ordered)
        return self


class PairRelation(StrEnum):
    EXACT = "EXACT"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    FUNCTIONALLY_EQUIVALENT = "FUNCTIONALLY_EQUIVALENT"
    POTENTIAL_SUBSTITUTE = "POTENTIAL_SUBSTITUTE"
    RELATED_BUT_NOT_EQUIVALENT = "RELATED_BUT_NOT_EQUIVALENT"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"


class PairLabel(DomainModel):
    pair: MaterialPair
    relation: PairRelation
    label_source: str = "expert_gold"
    label_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    review_status: str = "PENDING"
    reviewer_role: str = ""
    reviewer_id: str = ""
    review_timestamp: datetime | None = None
    notes: str = ""


class MatchCandidate(DomainModel):
    candidate_id: str
    rank: int = Field(ge=1)
    lexical_score: float = Field(ge=0.0)
    dense_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    fusion_score: float = Field(ge=0.0)
    material: MaterialRecord | None = None


class MatchDecision(DomainModel):
    pair: MaterialPair
    score: float = Field(ge=0.0, le=1.0)
    calibrated_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_band: str = "UNVALIDATED_SCORE"
    compatibility: str = "UNKNOWN"
    rationale: list[str] = Field(default_factory=list)
    model_version: str = "rule-baseline-0.1"
    requires_human_review: bool = True


class NMCRecord(DomainModel):
    nmc: str
    canonical_material_id: str
    family: str
    attribute_signature: str
    version: int = Field(default=1, ge=1)
    status: str = "proposed"
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None
    approval_status: str = "PENDING"
    human_override: bool = False
    override_reason: str = ""


class NMCMapping(DomainModel):
    nmc: str
    cpse: str
    legacy_material_code: str
    plant: str = ""
    source_system: str
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None
    mapping_status: str = "PROPOSED"
    mapping_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    approved_by: str = ""
    approved_at: datetime | None = None
    model_version: str = ""
    review_id: str = ""


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    REVIEWED = "REVIEWED"
    CHECKER_PENDING = "CHECKER_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewTask(DomainModel):
    id: str = ""
    pair: MaterialPair
    status: ReviewStatus = ReviewStatus.PENDING
    assigned_to: str = ""
    created_by: str = "system"
    priority: float = Field(default=0.0, ge=0.0)
    rationale: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def assign_id(self) -> ReviewTask:
        if not self.id:
            self.id = stable_id("review", self.pair.id)
        return self


class ReviewDecision(DomainModel):
    review_id: str
    reviewer_id: str
    reviewer_role: str
    relation: PairRelation
    reason_codes: list[str] = Field(default_factory=list)
    notes: str = ""
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    checker_id: str = ""
    checker_role: str = ""
    approved: bool | None = None


class AuditEvent(DomainModel):
    event_id: str = ""
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_version: str = ""
    input_hash: str = ""
    output_hash: str = ""
    previous_event_hash: str = ""
    event_hash: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class TaxonomyNode(DomainModel):
    taxonomy: str
    taxonomy_version: str
    taxonomy_code: str
    taxonomy_name: str
    parent_code: str = ""
    source: str = ""
    hsn_sac_code: str = ""


class ModelMetadata(DomainModel):
    model_version: str
    model_type: str
    embedding_model: str = ""
    embedding_revision: str = ""
    index_version: str = ""
    calibration_version: str = ""
    thresholds: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvaluationResult(DomainModel):
    run_id: str
    dataset_version: str
    split_strategy: str
    metrics: dict[str, float] = Field(default_factory=dict)
    calibration_metrics: dict[str, float] = Field(default_factory=dict)
    label_source: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "AuditEvent",
    "CanonicalMaterial",
    "DomainModel",
    "EvaluationResult",
    "MatchCandidate",
    "MatchDecision",
    "MaterialAttribute",
    "MaterialPair",
    "MaterialRecord",
    "ModelMetadata",
    "NMCMapping",
    "NMCRecord",
    "PairLabel",
    "PairRelation",
    "ReviewDecision",
    "ReviewStatus",
    "ReviewTask",
    "SourceArtifact",
    "TaxonomyNode",
    "stable_id",
]
