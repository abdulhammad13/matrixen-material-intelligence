from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cpse_harmonizer.extraction.deepseek_extractor import DeepSeekMaterialExtractor, MaterialLine


@pytest.mark.asyncio
async def test_extract_material_lines_uses_schema_and_confidence(monkeypatch):
    extractor = DeepSeekMaterialExtractor(api_key="sk-test", model="deepseek-flash")

    async def fake_tool(self: DeepSeekMaterialExtractor, markdown: str, source_url: str = "") -> list[MaterialLine]:
        return [
            MaterialLine(
                short_description="11 kV Transformer",
                long_description="11 kV transformer 2 Nos",
                quantity=2.0,
                uom="Nos",
                hsn_code="8504",
                specifications="11 kV transformer",
                standards="IS 2026",
                source_url=source_url,
                extraction_confidence=0.93,
            )
        ]

    monkeypatch.setattr(DeepSeekMaterialExtractor, "_call_deepseek_tool", fake_tool)
    rows = await extractor.extract_material_lines("11 kV transformer 2 Nos HSN 8504", source_url="https://example.com/tender")

    assert len(rows) == 1
    assert rows[0].hsn_code == "8504"
    assert 0.0 <= rows[0].extraction_confidence <= 1.0


def test_generate_match_rationale_is_human_readable():
    rationale = DeepSeekMaterialExtractor.generate_match_rationale("11 kV transformer", "11 kV transformer")
    assert "material match" in rationale.lower()
    assert "transformer" in rationale.lower()
