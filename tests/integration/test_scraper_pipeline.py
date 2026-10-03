from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cpse_harmonizer.extraction.deepseek_extractor import DeepSeekMaterialExtractor
from cpse_harmonizer.ingestion.tender_portal_scraper import TenderPortalScraper


@pytest.mark.asyncio
async def test_scraper_and_extractor_pipeline(monkeypatch):
    fixture = Path("tests/fixtures/sample_nit_page.md").read_text(encoding="utf-8")
    scraper = TenderPortalScraper(portal_name="ntpc")

    async def fake_get(self, url, *args, **kwargs):
        return SimpleNamespace(text=fixture, raise_for_status=lambda: None)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    markdown = await scraper.fetch_tender_page("https://example.com/tender")
    assert "11 kV" in markdown

    extractor = DeepSeekMaterialExtractor()
    rows = await extractor.extract_material_lines(markdown, source_url="https://example.com/tender")
    assert rows
    assert rows[0].short_description
    assert rows[0].extraction_confidence >= 0.5
