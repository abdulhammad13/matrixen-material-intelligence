import math

from cpse_harmonizer.governance.audit import AuditLog
from cpse_harmonizer.master_data.nmc_generator import generate_nmc
from cpse_harmonizer.matching.hybrid_scorer import HybridScorer
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.uom_pint import convert_quantity, is_convertible


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


def test_nmc_generation_is_stable():
    first = generate_nmc("11 kV transformer", cpse="NTPC")
    second = generate_nmc("11 kV transformer", cpse="NTPC")
    assert first == second
    assert first.startswith("NMC-NTPC-")


def test_audit_log_appends():
    audit = AuditLog()
    record = audit.append("material", "M-42", "match", "system", confidence="high")
    assert record.entity_id == "M-42"
    assert len(audit.read()) == 1
