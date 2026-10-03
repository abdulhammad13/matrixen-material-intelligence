import json

import pytest

from cpse_harmonizer.domain.models import (
    MaterialPair,
    PairRelation,
    ReviewStatus,
    ReviewTask,
)
from cpse_harmonizer.extraction.embedding_service import EmbeddingService
from cpse_harmonizer.governance.audit import AuditLog
from cpse_harmonizer.matching.technical_compatibility import (
    CompatibilityClass,
    TechnicalCompatibilityChecker,
)
from cpse_harmonizer.persistence.database import Database
from cpse_harmonizer.persistence.repository import MaterialRepository
from cpse_harmonizer.retrieval.hybrid_search import HybridSearchEngine, rrf_fusion
from cpse_harmonizer.review.service import ReviewQueue, ReviewWorkflowError


def test_rrf_fuses_document_ids_instead_of_positions():
    fused = rrf_fusion([["material-a", "material-b"], ["material-b", "material-c"]])
    assert fused["material-b"] > fused["material-a"]
    assert "material-0" not in fused


def test_hybrid_retrieval_returns_source_candidate_ids():
    engine = HybridSearchEngine(
        ["centrifugal pump 5 hp", "gate valve 50 mm"],
        document_ids=["src-pump-1", "src-valve-1"],
        embedding_service=EmbeddingService(backend="lexical"),
    )
    results = engine.search("centrifugal pump", limit=1)
    assert results[0]["candidate_id"] == "src-pump-1"
    assert results[0]["rank"] == 1
    assert "fusion_score" in results[0]


def test_technical_checker_fails_closed_for_unknown_and_detects_conflict():
    checker = TechnicalCompatibilityChecker()
    conflict = checker.check("11 kV transformer", "33 kV transformer")
    unknown = checker.check("miscellaneous item", "miscellaneous item")
    assert conflict.classification == CompatibilityClass.HARD_CONFLICT
    assert unknown.classification == CompatibilityClass.UNKNOWN
    assert unknown.compatible is False


def test_review_queue_persists_maker_checker_separation(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'review.db').as_posix()}")
    try:
        queue = ReviewQueue(database)
        task = queue.add(
            ReviewTask(
                pair=MaterialPair(material_a="material-a", material_b="material-b"),
                created_by="maker",
            )
        )
        persisted_queue = ReviewQueue(database)
        assert persisted_queue.get(task.id).status == ReviewStatus.PENDING
        persisted_queue.assign(task.id, "reviewer")
        persisted_queue.decide(
            task.id,
            "reviewer",
            "COMMODITY_EXPERT",
            PairRelation.EXACT,
        )
        with pytest.raises(ReviewWorkflowError, match="self-approval"):
            persisted_queue.approve(
                task.id,
                "reviewer",
                "CHECKER",
                approved=True,
            )
        approved = persisted_queue.approve(
            task.id,
            "checker",
            "CHECKER",
            approved=True,
        )
        assert approved.status == ReviewStatus.APPROVED
    finally:
        database.engine.dispose()


def test_audit_chain_detects_modified_events(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)
    audit.append("material", "material-a", "normalized", "system", output={"value": "A"})
    audit.append("material", "material-b", "normalized", "system", output={"value": "B"})
    assert audit.verify()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["actor"] = "tampered"
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    assert not audit.verify()


def test_material_repository_rejects_unbounded_list_limit(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'repo.db').as_posix()}")
    try:
        repository = MaterialRepository(database)
        with pytest.raises(ValueError, match="limit"):
            repository.list(limit=0)
    finally:
        database.engine.dispose()
