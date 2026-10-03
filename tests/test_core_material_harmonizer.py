import math

from cpse_harmonizer.domain.models import MaterialAttribute, MaterialRecord
from cpse_harmonizer.governance.audit import AuditLog
from cpse_harmonizer.master_data.nmc_generator import NMCGenerator
from cpse_harmonizer.matching.hybrid_scorer import HybridScorer
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.uom_pint import convert_quantity, is_convertible
from cpse_harmonizer.persistence.database import Database
from cpse_harmonizer.persistence.repository import MaterialRepository


def test_matching_score_confidence_band():
    result = HybridScorer().score_match(0.95, 0.80, 0.90, 0.75)
    assert result["score"] >= 0.8
    assert result["confidence_band"] in {"Auto-accept", "Human Review", "Reject"}


def test_attribute_extraction_marks_voltage_and_grade():
    attrs = extract_attributes("11 kV transformer with IS 1239 grade A106")
    assert attrs.voltage_kv == 11.0
    assert attrs.standard is not None
    assert attrs.material_grade is not None


def test_units_convert_and_are_flagged():
    assert math.isclose(convert_quantity(1, "kg", "gram"), 1000.0, rel_tol=1e-6)
    assert is_convertible("kg", "gram") is True
    assert is_convertible("kg", "meter") is False


def test_nmc_is_cpse_independent_and_description_order_independent():
    generator = NMCGenerator()
    first = generator.generate("500 KVA transformer 11 KV", cpse="NTPC")
    second = generator.generate("11kV 500kva transformer", cpse="IOCL")
    assert first == second
    assert first.startswith("NMC-IND-")


def test_material_identity_does_not_change_with_normalizer_output():
    source = {
        "source_system": "ERP",
        "source_record_id": "material-17",
        "raw_description": "11 kV Transformer",
    }
    raw = MaterialRecord(**source)
    normalized = MaterialRecord(**source, normalized_description="11 KV TRANSFORMER")
    assert raw.id == normalized.id


def test_material_repository_persists_provenance_and_typed_attributes(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'nummf.db'}")
    try:
        repository = MaterialRepository(database)
        material = MaterialRecord(
            source_system="ERP",
            source_organization="CPCL",
            source_record_id="material-17",
            raw_description="11 kV transformer",
            normalized_description="11 KV TRANSFORMER",
            attributes=[
                MaterialAttribute(
                    attribute_name="voltage",
                    value=11.0,
                    normalized_value=11.0,
                    unit="kV",
                    source_span=(0, 4),
                )
            ],
        )
        assert repository.save_many([material]) == 1
        saved = repository.get(material.id)
        assert saved is not None
        assert saved.source_organization == "CPCL"
        assert saved.attributes[0].value == 11.0
        assert saved.attributes[0].source_span == (0, 4)
    finally:
        database.engine.dispose()


def test_audit_log_appends():
    audit = AuditLog()
    record = audit.append("material", "M-42", "match", "system", confidence="high")
    assert record.entity_id == "M-42"
    assert len(audit.read()) == 1
