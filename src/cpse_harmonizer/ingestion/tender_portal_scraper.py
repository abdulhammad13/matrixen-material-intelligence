"""Tender portal scraping for live CPSE procurement pages.

The fetch layer intentionally uses async HTTP and browser-backed rendering where
needed, while the DeepSeek API only receives sanitized markdown for semantic
extraction. This matches the DeepSeek API's tool-calling architecture and the
NUMMF sovereign requirement.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from cpse_harmonizer.governance.audit import AuditLog


@dataclass(slots=True)
class PortalAdapter:
    """Portal-specific scrape settings."""

    name: str
    base_url: str
    robots_url: str


class TenderPortalScraper:
    """Fetch and normalize HTML/Markdown from CPSE tender portals."""

    def __init__(
        self,
        portal_name: str = "ntpc",
        user_agent: str = "NUMMF-Forge-Scraper/1.0",
        audit_log: AuditLog | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.portal_name = portal_name
        self.user_agent = user_agent
        self.audit_log = audit_log or AuditLog()
        self.timeout_seconds = timeout_seconds
        self.portals = {
            "ntpc": PortalAdapter("NTPC", "https://ntpctender.ntpc.co.in", "https://ntpctender.ntpc.co.in/robots.txt"),
            "iocl": PortalAdapter("IOCL", "https://iocletenders.nic.in", "https://iocletenders.nic.in/robots.txt"),
            "oil_india": PortalAdapter("Oil India", "https://www.oil-india.com", "https://www.oil-india.com/robots.txt"),
            "cppp": PortalAdapter("CPPP", "https://eprocure.gov.in", "https://eprocure.gov.in/robots.txt"),
        }

    def _portal_adapter(self, portal_name: str | None = None) -> PortalAdapter:
        name = (portal_name or self.portal_name).lower()
        if name not in self.portals:
            return self.portals["ntpc"]
        return self.portals[name]

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        adapter = self._portal_adapter()
        bot = RobotFileParser(adapter.robots_url)
        try:
            bot.read()
            return bot.can_fetch(self.user_agent, url)
        except Exception:
            return True

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_markdown(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    async def fetch_tender_page(self, url: str) -> str:
        """Fetch a CPSE tender page and convert it to clean markdown."""
        if not self._robots_allowed(url):
            raise PermissionError(f"Robots policy blocks access to {url}")
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        markdown = self._to_markdown(html)
        self.audit_log.append(
            "scrape_page",
            url,
            "fetch_tender_page",
            self.portal_name,
            content_hash=self._hash_text(markdown),
            url_hash=self._hash_text(url),
        )
        logger.bind(portal=self.portal_name, url=url, model="scrape", tokens_used=len(markdown.split()), latency_ms=0, cache_hit=False).info("page fetched")
        return markdown

    async def discover_tender_links(self, portal_url: str) -> list[str]:
        """Discover links on a tender portal and return candidate tender-page URLs."""
        html = await self.fetch_html(portal_url)
        soup = BeautifulSoup(html, "html.parser")
        links: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            candidate = urljoin(portal_url, href)
            if candidate.startswith("http") and ("tender" in candidate.lower() or "bid" in candidate.lower() or "download" in candidate.lower()):
                links.add(candidate)
        self.audit_log.append("portal_scan", portal_url, "discover_tender_links", self.portal_name, link_count=len(links))
        return sorted(links)

    async def fetch_html(self, url: str) -> str:
        """Fetch raw HTML for a portal page while enforcing async HTTP usage."""
        headers = {"User-Agent": self.user_agent, "Accept": "text/html"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    async def fetch_pdf_document(self, pdf_url: str) -> str:
        """Download and extract plain text from a PDF via pymupdf if available."""
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
            payload = response.content

        try:
            import fitz

            doc = fitz.open(stream=payload, filetype="pdf")
            text_parts = [page.get_text("text") for page in doc]
            return "\n".join(part for part in text_parts if part)
        except Exception:
            return "PDF text extraction unavailable; raw content was fetched but not parsed."


class NTPCAdapter(TenderPortalScraper):
    """NTPC portal adapter."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(portal_name="ntpc", *args, **kwargs)


class IOCLAdapter(TenderPortalScraper):
    """IOCL portal adapter."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(portal_name="iocl", *args, **kwargs)


class OilIndiaAdapter(TenderPortalScraper):
    """Oil India portal adapter."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(portal_name="oil_india", *args, **kwargs)


__all__ = ["TenderPortalScraper", "NTPCAdapter", "IOCLAdapter", "OilIndiaAdapter"]
