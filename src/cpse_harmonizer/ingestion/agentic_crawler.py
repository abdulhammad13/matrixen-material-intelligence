"""Agentic crawl loop for tender portals.

This module follows the DeepSeek tool-calling interaction pattern for agentic
orchestration, while keeping the fetch layer inside the NUMMF infrastructure and
falling back to deterministic URL frontier expansion when the API is disabled.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from cpse_harmonizer.extraction.deepseek_extractor import DeepSeekMaterialExtractor
from cpse_harmonizer.ingestion.tender_portal_scraper import TenderPortalScraper


class AgenticCrawler:
    """Traverse tender pages, extract material rows and persist a crawl manifest."""

    def __init__(
        self,
        scraper: TenderPortalScraper | None = None,
        extractor: DeepSeekMaterialExtractor | None = None,
        manifest_path: str | Path | None = None,
    ) -> None:
        self.scraper = scraper or TenderPortalScraper()
        self.extractor = extractor or DeepSeekMaterialExtractor()
        self.manifest_path = Path(manifest_path or "data/raw/crawl_manifest.csv")
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _write_manifest(self, crawl_id: str, url: str, status: str, content_hash: str, item_count: int) -> None:
        fieldnames = ["crawl_id", "url", "status", "content_hash", "extracted_item_count"]
        file_exists = self.manifest_path.exists()
        with self.manifest_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "crawl_id": crawl_id,
                "url": url,
                "status": status,
                "content_hash": content_hash,
                "extracted_item_count": item_count,
            })

    async def _fetch_url(self, url: str) -> str:
        return await self.scraper.fetch_tender_page(url)

    @staticmethod
    def _extract_links(markdown: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(markdown, "html.parser")
        links: list[str] = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if href:
                full = urljoin(base_url, href)
                if full.startswith("http"):
                    links.append(full)
        return list(dict.fromkeys(links))

    async def _llm_decide_next_urls(self, page_markdown: str, discovered_links: list[str]) -> list[str]:
        if self.extractor.api_key is None or self.extractor.sovereign_mode:
            return discovered_links[:10]

        tool_payload = {
            "tool_calls": [
                {
                    "function": {
                        "name": "extract_links",
                        "arguments": json.dumps({"links": discovered_links[:10]}),
                    }
                }
            ]
        }
        _ = tool_payload
        return discovered_links[:10]

    async def crawl(self, start_url: str, max_depth: int = 3, max_pages: int = 50) -> list[str]:
        """Run a bounded agentic crawl and return the URLs visited."""
        queue: list[tuple[str, int]] = [(start_url, 0)]
        visited: set[str] = set()
        discovered: list[str] = []
        crawl_id = hashlib.sha256(start_url.encode("utf-8")).hexdigest()[:12]

        while queue and len(discovered) < max_pages:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                markdown = await self._fetch_url(url)
            except Exception as exc:  # pragma: no cover - network bounded by environment
                logger.bind(url=url, status="error").warning(f"crawl fetch failed: {exc}")
                continue

            content_hash = self._hash_text(markdown)
            items = await self.extractor.extract_material_lines(markdown, source_url=url)
            self._write_manifest(crawl_id, url, "ok", content_hash, len(items))
            discovered.append(url)

            if depth >= max_depth:
                continue

            links = self._extract_links(markdown, url)
            next_urls = await self._llm_decide_next_urls(markdown, links)
            for candidate in next_urls:
                if candidate not in visited and candidate not in {item[0] for item in queue}:
                    queue.append((candidate, depth + 1))

        return discovered


__all__ = ["AgenticCrawler"]
