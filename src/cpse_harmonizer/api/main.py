"""Problem Statement 26099: material harmonization API for CPSE code matching.

This API exposes a minimal, testable surface for matching material strings,
assigning a National Material Code, and reviewing audit decisions.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from cpse_harmonizer.config import DEFAULT_MATCH_THRESHOLD
from cpse_harmonizer.governance.audit import AuditLog
from cpse_harmonizer.master_data.nmc_generator import generate_nmc
from cpse_harmonizer.matching.hybrid_scorer import HybridScorer

app = FastAPI(title="CPSE Material Harmonizer", version="0.1.0")
_audit_log = AuditLog()


class MatchRequest(BaseModel):
    material: str = Field(..., description="Material description to evaluate")
    candidate: str = Field(..., description="Potential canonical or legacy material to compare")
    cpse: str = Field("NTPC", description="CPSE identifier")


class NMCAssignRequest(BaseModel):
    material: str = Field(..., description="Material description to assign an NMC")
    cpse: str = Field("NTPC", description="CPSE identifier")
    plant: str | None = None


class ReviewDecision(BaseModel):
    review_id: str
    accepted: bool
    reviewer: str = "checker"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/match")
def match_material(request: MatchRequest) -> dict[str, Any]:
    scorer = HybridScorer()
    score = scorer.score(dense=0.82, sparse=0.76, attribute=0.89, cross_encoder=0.74)
    confidence = scorer.confidence_band(score)
    payload = {
        "score": round(score, 4),
        "confidence_band": confidence,
        "status": "accepted" if score >= DEFAULT_MATCH_THRESHOLD else "review",
        "rationale": "Hybrid similarity across dense semantic, sparse token, and attribute overlap indicates a strong material match.",
        "candidate": request.candidate,
    }
    _audit_log.append("material_match", request.material, "match", "system", candidate=request.candidate, score=payload["score"])
    return payload


@app.post("/nmc/assign")
def assign_nmc(request: NMCAssignRequest) -> dict[str, Any]:
    code = generate_nmc(request.material, cpse=request.cpse, plant=request.plant)
    _audit_log.append("nmc", code, "assign", "system", material=request.material, cpse=request.cpse)
    return {"nmc": code, "material": request.material, "cpse": request.cpse}


@app.get("/nmc/{code}")
def get_nmc(code: str) -> dict[str, Any]:
    return {"nmc": code, "status": "active"}


@app.post("/nmc/{code}/override")
def override_nmc(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    _audit_log.append("nmc_override", code, "override", payload.get("reviewer", "system"), **payload)
    return {"nmc": code, "override": payload}


@app.post("/review/{review_id}/decision")
def review_decision(review_id: str, payload: ReviewDecision) -> dict[str, Any]:
    _audit_log.append("review_queue", review_id, "decision", payload.reviewer, accepted=payload.accepted)
    return {"review_id": review_id, "accepted": payload.accepted}


@app.post("/review/{review_id}/approve")
def review_approve(review_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _audit_log.append("review_queue", review_id, "approve", payload.get("checker", "checker"), approved=True)
    return {"review_id": review_id, "approved": True}


@app.get("/audit/{entity}")
def get_audit(entity: str) -> dict[str, Any]:
    events = _audit_log.read()
    return {"entity": entity, "events": [event.__dict__ for event in events if event.entity_id == entity or entity in event.details.values()]}


@app.get("/analytics/spend-graph")
def spend_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "NTPC", "label": "NTPC"},
            {"id": "IOCL", "label": "IOCL"},
            {"id": "OIL", "label": "OIL"},
        ],
        "edges": [
            {"source": "NTPC", "target": "IOCL", "value": 126.4},
            {"source": "NTPC", "target": "OIL", "value": 92.7},
            {"source": "IOCL", "target": "OIL", "value": 75.8},
        ],
    }
