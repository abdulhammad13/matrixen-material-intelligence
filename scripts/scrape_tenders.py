#!/usr/bin/env python3
"""CLI for scraping and extracting CPSE tender material rows."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import typer

from cpse_harmonizer.extraction.deepseek_extractor import DeepSeekMaterialExtractor
from cpse_harmonizer.governance.audit import AuditLog
from cpse_harmonizer.ingestion.tender_portal_scraper import TenderPortalScraper
from cpse_harmonizer.intelligence.procurement.spend_graph import SpendGraph
from cpse_harmonizer.normalization.service import NormalizationService

app = typer.Typer(help="NUMMF tender scraping and extraction CLI")


@app.command("scrape")
def scrape_tenders(
    portal: str = typer.Option("ntpc", "--portal", help="Tender portal name: ntpc, iocl, oil_india, cppp"),
    max_pages: int = typer.Option(20, "--max-pages"),
    output: str = typer.Option("data/raw/ntpc", "--output"),
) -> None:
    """Scrape a tender portal and save discovered links to a local file."""
    async def _run() -> None:
        base_url = {
            "ntpc": "https://ntpctender.ntpc.co.in",
            "iocl": "https://iocletenders.nic.in",
            "oil_india": "https://www.oil-india.com",
            "cppp": "https://eprocure.gov.in",
        }.get(portal.lower(), "https://ntpctender.ntpc.co.in")
        scraper = TenderPortalScraper(portal_name=portal)
        links = await scraper.discover_tender_links(base_url)
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)
        with (output_dir / "tender_links.txt").open("w", encoding="utf-8") as handle:
            for link in links[:max_pages]:
                handle.write(f"{link}\n")
        typer.echo(f"Saved {len(links[:max_pages])} links to {output_dir / 'tender_links.txt'}")

    asyncio.run(_run())


@app.command("extract")
def extract_tenders(
    input_dir: str = typer.Option("data/raw/ntpc", "--input"),
    output: str = typer.Option("data/processed/ntpc_items.csv", "--output"),
) -> None:
    """Extract material rows from markdown files and write them as CSV."""
    async def _run() -> None:
        base = Path(input_dir)
        extractor = DeepSeekMaterialExtractor()
        audit_log = AuditLog(Path("data/processed/extraction_audit.jsonl"))
        graph = SpendGraph()
        rows: list[dict[str, str | float | None]] = []
        for file_path in sorted(base.rglob("*")):
            if file_path.suffix.lower() not in {".md", ".txt", ".html"}:
                continue
            markdown = file_path.read_text(encoding="utf-8", errors="ignore")
            extracted = await extractor.extract_material_lines(markdown, source_url=str(file_path))
            for item in extracted:
                row = {
                    "short_description": item.short_description,
                    "long_description": item.long_description,
                    "quantity": item.quantity,
                    "uom": item.uom,
                    "hsn_code": item.hsn_code,
                    "specifications": item.specifications,
                    "standards": item.standards,
                    "source_url": item.source_url,
                    "extraction_confidence": item.extraction_confidence,
                }
                rows.append(row)
                graph.add_material_signal(row["short_description"], row["quantity"], row["uom"], str(file_path))
                audit_log.append("material_extraction", str(file_path), "deepseek_extract", "system", **row)

        normalized_rows = NormalizationService().process(rows)

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "short_description",
                    "long_description",
                    "quantity",
                    "uom",
                    "hsn_code",
                    "specifications",
                    "standards",
                    "source_url",
                    "evidence_text",
                    "source_page",
                    "source_section",
                    "extraction_confidence",
                ],
            )
            writer.writeheader()
            for row in normalized_rows:
                writer.writerow({
                    "short_description": row.get("short_description"),
                    "long_description": row.get("long_description"),
                    "quantity": row.get("quantity"),
                    "uom": row.get("uom"),
                    "hsn_code": row.get("hsn_code"),
                    "specifications": row.get("specifications"),
                    "standards": row.get("standards"),
                    "source_url": row.get("source_url"),
                    "evidence_text": row.get("evidence_text"),
                    "source_page": row.get("source_page"),
                    "source_section": row.get("source_section"),
                    "extraction_confidence": row.get("extraction_confidence"),
                })
        typer.echo(f"Wrote {len(normalized_rows)} rows to {output_path}")

    asyncio.run(_run())


@app.command("verify")
def verify_tenders(input_csv: str = typer.Argument(..., help="CSV file to verify")) -> None:
    """Cross-check schema-valid rows and basic HSN sanity."""
    path = Path(input_csv)
    if not path.exists():
        raise typer.Exit(code=1)

    valid = 0
    total = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        total = len(rows)
        for row in rows:
            hsn = (row.get("hsn_code") or "").strip()
            evidence = (row.get("evidence_text") or "").strip()
            if evidence and (not hsn or hsn.isdigit()):
                valid += 1
    typer.echo(f"Evidence-backed schema-valid rows: {valid}/{total}")


if __name__ == "__main__":
    app()
