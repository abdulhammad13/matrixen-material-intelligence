"""Evidence-grounded orchestration API for NUMMF Phase-0/Phase-1 workflows."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from cpse_harmonizer import __version__
from cpse_harmonizer.data_quality.checker import read_csv_records
from cpse_harmonizer.domain.models import (
    MatchDecision,
    MaterialAttribute,
    MaterialPair,
    MaterialRecord,
    PairRelation,
    ReviewStatus,
    ReviewTask,
    stable_id,
)
from cpse_harmonizer.extraction.embedding_service import EmbeddingService
from cpse_harmonizer.governance.audit import AuditLog
from cpse_harmonizer.master_data.nmc_generator import NMCGenerator
from cpse_harmonizer.matching.pair_scorer import PairScorer
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.normalizer import MaterialNormalizer
from cpse_harmonizer.persistence.database import (
    CanonicalMaterialRow,
    Database,
    NMCMappingRow,
    NMCRegistryRow,
)
from cpse_harmonizer.persistence.repository import MaterialRepository
from cpse_harmonizer.retrieval.hybrid_search import HybridSearchEngine
from cpse_harmonizer.review.service import ReviewQueue, ReviewWorkflowError

Role = Literal["ADMIN", "DATA_STEWARD", "COMMODITY_EXPERT", "CHECKER", "AUDITOR", "VIEWER"]

_database = Database()
_audit_log = AuditLog(os.getenv("NUMMF_AUDIT_PATH", "data/processed/audit_events.jsonl"))
_review_queue = ReviewQueue(_database)
_normalizer = MaterialNormalizer()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    _database.engine.dispose()


app = FastAPI(
    title="National Unified Material Master Framework",
    version=__version__,
    description="Provenance-aware material harmonization proposals; approvals remain human-controlled.",
    lifespan=_lifespan,
)


class NormalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20_000)


class NormalizeResponse(BaseModel):
    raw_text: str
    normalized_text: str
    transformations: list[str]


class AttributesResponse(BaseModel):
    raw_text: str
    family: str
    attributes: list[MaterialAttribute]
    conflicts: list[str]


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material: str = Field(min_length=1, max_length=20_000)
    candidate: str = Field(min_length=1, max_length=20_000)
    material_id: str | None = None
    candidate_id: str | None = None
    hsn_a: str | None = None
    hsn_b: str | None = None
    manufacturer_a: str | None = None
    manufacturer_b: str | None = None


class MatchBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[MatchRequest] = Field(min_length=1, max_length=100)


class PairFeaturesResponse(BaseModel):
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


class MatchResponse(BaseModel):
    decision: MatchDecision
    features: PairFeaturesResponse


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=10, ge=1, le=100)
    family: str | None = None


class NMCProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=20_000)
    family: str | None = None


class NMCProposalResponse(BaseModel):
    nmc: str
    family: str
    attribute_signature: str
    canonical_description: str
    status: str
    approval_status: str
    collisions: list[str]


class ReviewTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_a: str = Field(min_length=1)
    material_b: str = Field(min_length=1)
    created_by: str = "system"
    priority: float = Field(default=0.0, ge=0.0)
    rationale: list[str] = Field(default_factory=list)


class ReviewTaskResponse(BaseModel):
    id: str
    material_a: str
    material_b: str
    status: ReviewStatus
    assigned_to: str
    created_by: str
    priority: float
    rationale: list[str]


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_id: str = Field(min_length=1)
    relation: PairRelation
    reason_codes: list[str] = Field(default_factory=list)
    notes: str = ""


class ReviewApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checker_id: str = Field(min_length=1)
    approved: bool


class AuditEventsResponse(BaseModel):
    entity_type: str
    entity_id: str
    events: list[dict[str, object]]
    chain_valid: bool


class TaxonomyResult(BaseModel):
    taxonomy: str
    taxonomy_version: str
    taxonomy_code: str
    taxonomy_name: str
    parent_code: str
    source: str


def _role(value: str) -> str:
    role = value.upper()
    if role not in {"ADMIN", "DATA_STEWARD", "COMMODITY_EXPERT", "CHECKER", "AUDITOR", "VIEWER"}:
        raise HTTPException(status_code=403, detail="Unknown or unauthorized role.")
    return role


def _require(role: str, *allowed: str) -> None:
    if role not in allowed:
        raise HTTPException(
            status_code=403, detail=f"Role {role} is not permitted for this operation."
        )


def _task_response(task: ReviewTask) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        id=task.id,
        material_a=task.pair.material_a,
        material_b=task.pair.material_b,
        status=task.status,
        assigned_to=task.assigned_to,
        created_by=task.created_by,
        priority=task.priority,
        rationale=task.rationale,
    )


def _positive_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


@lru_cache(maxsize=1)
def _search_index() -> tuple[HybridSearchEngine, dict[str, MaterialRecord]]:
    corpus_path = Path(
        os.getenv(
            "NUMMF_MATERIAL_CORPUS",
            "data/processed/extracted_items/material_description_corpus.csv",
        )
    )
    if not corpus_path.is_file():
        raise FileNotFoundError(f"Material corpus is unavailable: {corpus_path}")
    rows, _ = read_csv_records(corpus_path)
    records: list[MaterialRecord] = []
    families: list[str] = []
    for row in rows:
        description = (row.get("description") or "").strip()
        if not description:
            continue
        attrs = extract_attributes(description)
        source_system = row.get("source_system") or "unknown"
        organization = row.get("organization") or ""
        record = MaterialRecord(
            source_system=source_system,
            source_organization=row.get("source_organization") or organization,
            source_record_id=(
                row.get("source_record_id")
                or row.get("tender_id")
                or row.get("tender_reference")
                or row.get("material_code")
                or row.get("corpus_id")
                or ""
            ),
            source_url=row.get("source_url") or "",
            source_document=row.get("source_document") or row.get("document_url") or "",
            source_page=_positive_int(row.get("source_page") or row.get("page")),
            source_section=row.get("source_section") or row.get("section") or "",
            material_code=row.get("corpus_id") or "",
            raw_description=description,
            normalized_description=_normalizer.normalize(description).normalized_text,
            organization=organization,
            attributes=attrs.attributes,
            metadata={"description_kind": row.get("description_kind") or ""},
        )
        records.append(record)
        families.append(attrs.family)
    persisted = MaterialRepository(_database).list()
    known_ids = {record.id for record in records}
    for record in persisted:
        if record.id in known_ids:
            continue
        normalized = (
            record.normalized_description
            or _normalizer.normalize(record.raw_description).normalized_text
        )
        attrs = extract_attributes(record.raw_description)
        enriched = record.model_copy(update={"normalized_description": normalized})
        records.append(enriched)
        families.append(attrs.family)
        known_ids.add(enriched.id)
    engine = HybridSearchEngine(
        records,
        document_ids=[record.id for record in records],
        families=families,
        embedding_service=EmbeddingService(backend=os.getenv("NUMMF_EMBEDDING_BACKEND", "lexical")),
    )
    return engine, {record.id: record for record in records}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": "configured"}


@app.get("/version")
def version() -> dict[str, str]:
    return {"name": "nummf", "version": __version__}


@app.post("/materials/normalize", response_model=NormalizeResponse)
def normalize_material(request: NormalizeRequest) -> NormalizeResponse:
    result = _normalizer.normalize(request.text)
    return NormalizeResponse(
        raw_text=result.raw_text,
        normalized_text=result.normalized_text,
        transformations=result.transformations,
    )


@app.post("/materials/attributes", response_model=AttributesResponse)
def material_attributes(request: NormalizeRequest) -> AttributesResponse:
    attributes = extract_attributes(request.text)
    conflicts = [
        name
        for name in {attribute.attribute_name for attribute in attributes.attributes}
        if len({str(value.normalized_value) for value in attributes.values(name)}) > 1
    ]
    return AttributesResponse(
        raw_text=request.text,
        family=attributes.family,
        attributes=attributes.attributes,
        conflicts=sorted(conflicts),
    )


@app.post("/materials/search")
def search_materials(request: SearchRequest) -> dict[str, object]:
    try:
        engine, records = _search_index()
        hits = engine.search(request.query, request.limit, family=request.family)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    candidates: list[dict[str, object]] = []
    for hit in hits:
        record = records[str(hit["candidate_id"])]
        candidates.append(
            {
                **hit,
                "material": record.model_dump(mode="json"),
            }
        )
    return {"query": request.query, "candidates": candidates, "retrieval_mode": "bm25_rrf_lexical"}


@app.post("/materials/match", response_model=MatchResponse)
def match_material(request: MatchRequest) -> MatchResponse:
    scorer = PairScorer()
    decision, features = scorer.score(
        request.material,
        request.candidate,
        material_a_id=request.material_id,
        material_b_id=request.candidate_id,
        hsn_a=request.hsn_a,
        hsn_b=request.hsn_b,
        manufacturer_a=request.manufacturer_a,
        manufacturer_b=request.manufacturer_b,
    )
    _audit_log.append(
        "material_pair",
        decision.pair.id,
        "match_scored",
        "system",
        input={"material": request.material, "candidate": request.candidate},
        output={"score": decision.score, "compatibility": decision.compatibility},
        model_version=decision.model_version,
    )
    return MatchResponse(
        decision=decision,
        features=PairFeaturesResponse(**asdict(features)),
    )


@app.post("/materials/match/batch")
def match_material_batch(request: MatchBatchRequest) -> dict[str, object]:
    return {"results": [match_material(pair) for pair in request.pairs]}


@app.post("/materials/nmc/propose", response_model=NMCProposalResponse)
def propose_nmc(
    request: NMCProposalRequest, x_role: str = Header(default="VIEWER")
) -> NMCProposalResponse:
    _require(_role(x_role), "ADMIN", "DATA_STEWARD", "COMMODITY_EXPERT")
    generator = NMCGenerator()
    try:
        proposal = generator.propose(request.description, family=request.family)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_id = stable_id("can", proposal.attribute_signature)
    _database.initialize()
    with _database.sessions.begin() as session:
        existing = session.get(NMCRegistryRow, proposal.nmc)
        if existing is None:
            canonical = session.get(CanonicalMaterialRow, record_id)
            if canonical is None:
                session.add(
                    CanonicalMaterialRow(
                        id=record_id,
                        family=proposal.family,
                        generated_description=proposal.canonical_description,
                        attribute_signature=proposal.attribute_signature,
                        status="proposed",
                    )
                )
            session.add(
                NMCRegistryRow(
                    nmc=proposal.nmc,
                    canonical_material_id=record_id,
                    family=proposal.family,
                    attribute_signature=proposal.attribute_signature,
                    status="proposed",
                    approval_status="PENDING",
                )
            )
    _audit_log.append(
        "nmc",
        proposal.nmc,
        "nmc_proposed",
        x_role,
        input={"description_hash": stable_id("input", request.description)},
        output={"attribute_signature": proposal.attribute_signature},
    )
    return NMCProposalResponse(**asdict(proposal))


@app.get("/materials/{material_id}")
def get_material(material_id: str) -> dict[str, object]:
    try:
        _, records = _search_index()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    record = records.get(material_id)
    if record is None:
        record = MaterialRepository(_database).get(material_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Material record not found.")
    return record.model_dump(mode="json")


@app.get("/nmc/{nmc}")
def get_nmc(nmc: str) -> dict[str, object]:
    _database.initialize()
    with _database.sessions() as session:
        record = session.get(NMCRegistryRow, nmc)
        if record is None:
            raise HTTPException(status_code=404, detail="NMC record not found.")
        return {
            "nmc": record.nmc,
            "family": record.family,
            "canonical_material_id": record.canonical_material_id,
            "attribute_signature": record.attribute_signature,
            "version": record.version,
            "status": record.status,
            "approval_status": record.approval_status,
        }


@app.get("/nmc/{nmc}/mappings")
def get_nmc_mappings(nmc: str) -> dict[str, object]:
    _database.initialize()
    with _database.sessions() as session:
        records = session.scalars(select(NMCMappingRow).where(NMCMappingRow.nmc == nmc)).all()
        return {
            "nmc": nmc,
            "mappings": [
                {
                    "cpse": row.cpse,
                    "legacy_material_code": row.legacy_material_code,
                    "plant": row.plant,
                    "source_system": row.source_system,
                    "valid_from": row.valid_from.isoformat(),
                    "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                    "mapping_status": row.mapping_status,
                    "approved_by": row.approved_by,
                    "review_id": row.review_id,
                }
                for row in records
            ],
        }


@app.post("/review/tasks", response_model=ReviewTaskResponse, status_code=201)
def create_review_task(
    request: ReviewTaskRequest, x_role: str = Header(default="VIEWER")
) -> ReviewTaskResponse:
    role = _role(x_role)
    _require(role, "ADMIN", "DATA_STEWARD", "COMMODITY_EXPERT")
    task = ReviewTask(
        pair=MaterialPair(material_a=request.material_a, material_b=request.material_b),
        created_by=request.created_by,
        priority=request.priority,
        rationale=request.rationale,
    )
    created = _review_queue.add(task)
    _audit_log.append(
        "review_task", created.id, "review_created", request.created_by, status=created.status.value
    )
    return _task_response(created)


@app.get("/review/tasks")
def list_review_tasks(
    status: ReviewStatus | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    x_role: str = Header(default="VIEWER"),
) -> dict[str, object]:
    _role(x_role)
    return {
        "tasks": [_task_response(task) for task in _review_queue.list(status=status, limit=limit)]
    }


@app.post("/review/tasks/{task_id}/assign", response_model=ReviewTaskResponse)
def assign_review_task(
    task_id: str,
    reviewer_id: str = Query(min_length=1),
    x_role: str = Header(default="VIEWER"),
) -> ReviewTaskResponse:
    _require(_role(x_role), "ADMIN", "DATA_STEWARD")
    try:
        return _task_response(_review_queue.assign(task_id, reviewer_id))
    except (KeyError, ReviewWorkflowError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/review/tasks/{task_id}/decision", response_model=ReviewTaskResponse)
def submit_review_decision(
    task_id: str,
    request: ReviewDecisionRequest,
    x_role: str = Header(default="VIEWER"),
) -> ReviewTaskResponse:
    role = _role(x_role)
    try:
        task = _review_queue.decide(
            task_id,
            request.reviewer_id,
            role,
            request.relation,
            request.reason_codes,
            request.notes,
        )
    except (KeyError, ReviewWorkflowError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_log.append(
        "review_task",
        task.id,
        "review_decision",
        request.reviewer_id,
        relation=request.relation.value,
    )
    return _task_response(task)


@app.post("/review/tasks/{task_id}/approve", response_model=ReviewTaskResponse)
def approve_review_task(
    task_id: str,
    request: ReviewApprovalRequest,
    x_role: str = Header(default="VIEWER"),
) -> ReviewTaskResponse:
    role = _role(x_role)
    try:
        task = _review_queue.approve(task_id, request.checker_id, role, approved=request.approved)
    except (KeyError, ReviewWorkflowError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_log.append(
        "review_task",
        task.id,
        "review_accepted" if request.approved else "review_rejected",
        request.checker_id,
        status=task.status.value,
    )
    return _task_response(task)


@app.get("/audit/{entity_type}/{entity_id}", response_model=AuditEventsResponse)
def get_audit_events(entity_type: str, entity_id: str) -> AuditEventsResponse:
    events = [
        event
        for event in _audit_log.read()
        if event.entity_type == entity_type and event.entity_id == entity_id
    ]
    return AuditEventsResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        events=[
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "actor": event.actor,
                "timestamp": event.timestamp,
                "previous_event_hash": event.previous_event_hash,
                "event_hash": event.event_hash,
                "details": event.details,
            }
            for event in events
        ],
        chain_valid=_audit_log.verify(),
    )


@app.get("/taxonomy/search", response_model=list[TaxonomyResult])
def search_taxonomy(
    query: str = Query(min_length=1, max_length=200), limit: int = Query(default=20, ge=1, le=100)
) -> list[TaxonomyResult]:
    path = Path("data/reference/unspsc/unspsc_industrial_subset.csv")
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Reference taxonomy unavailable: {path}")
    records, _ = read_csv_records(path)
    needle = query.casefold()
    results = []
    for row in records:
        code = row.get("unspsc_code") or ""
        name = row.get("commodity_description") or ""
        if needle in code.casefold() or needle in name.casefold():
            results.append(
                TaxonomyResult(
                    taxonomy="UNSPSC",
                    taxonomy_version="repository-industrial-subset",
                    taxonomy_code=code,
                    taxonomy_name=name,
                    parent_code=row.get("class") or "",
                    source="data/reference/unspsc/unspsc_industrial_subset.csv",
                )
            )
            if len(results) == limit:
                break
    return results


@app.get("/analytics/coverage")
def analytics_coverage() -> dict[str, object]:
    path = Path("data/processed/extracted_items/material_description_corpus.csv")
    if not path.is_file():
        return {"status": "insufficient_data", "records": 0}
    records, _ = read_csv_records(path)
    total = len(records)
    return {
        "status": "observed_source_corpus",
        "records": total,
        "with_material_code": sum(bool(row.get("corpus_id")) for row in records),
        "with_tender_id": sum(bool(row.get("tender_id")) for row in records),
        "with_source_url_or_document": sum(
            bool(row.get("source_url") or row.get("document_url")) for row in records
        ),
        "nmc_coverage": "not measured: no approved national mappings",
    }


@app.get("/analytics/duplicates")
def analytics_duplicates() -> dict[str, object]:
    path = Path("data/processed/extracted_items/material_description_corpus.csv")
    if not path.is_file():
        return {"status": "insufficient_data", "groups": []}
    records, _ = read_csv_records(path)
    groups: dict[str, list[dict[str, str]]] = {}
    for row in records:
        description = " ".join((row.get("description") or "").casefold().split())
        if description:
            groups.setdefault(description, []).append(row)
    duplicates = [
        {
            "normalized_description": text,
            "records": len(items),
            "organizations": sorted({row.get("organization", "") for row in items}),
        }
        for text, items in groups.items()
        if len(items) > 1
    ]
    return {"status": "exact_text_groups_only_not_equivalence_labels", "groups": duplicates}


@app.get("/analytics/spend")
def analytics_spend() -> dict[str, object]:
    return {
        "status": "insufficient transactional data",
        "source": None,
        "transactions": 0,
        "aggregates": [],
    }


@app.get("/model/status")
def model_status() -> dict[str, object]:
    return {
        "model_version": "rule-baseline-0.1",
        "embedding_backend": os.getenv("NUMMF_EMBEDDING_BACKEND", "lexical"),
        "calibrated": False,
        "gold_label_count": 0,
        "promotion_status": "not_evaluated",
    }


@app.post("/model/evaluate")
def evaluate_model(x_role: str = Header(default="VIEWER")) -> dict[str, object]:
    _require(_role(x_role), "ADMIN", "DATA_STEWARD")
    return {
        "status": "insufficient_gold_labels",
        "metrics": None,
        "required_evidence": "A reviewed, held-out pair-label dataset with leakage-aware grouping.",
    }


@app.post("/model/retrain")
def retrain_model(x_role: str = Header(default="VIEWER")) -> dict[str, object]:
    _require(_role(x_role), "ADMIN", "DATA_STEWARD")
    raise HTTPException(
        status_code=409,
        detail="Retraining is unavailable until reviewed gold labels and an evaluation split exist.",
    )
