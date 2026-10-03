"""Dash search and governance views backed by repository records and SQLite state."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from dash import Dash, Input, Output, dcc, html

from cpse_harmonizer.data_quality.checker import read_csv_records
from cpse_harmonizer.domain.models import MaterialRecord
from cpse_harmonizer.extraction.embedding_service import EmbeddingService
from cpse_harmonizer.matching.pair_scorer import PairScorer
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.normalizer import MaterialNormalizer
from cpse_harmonizer.persistence.database import Database, NMCRegistryRow
from cpse_harmonizer.retrieval.hybrid_search import HybridSearchEngine
from cpse_harmonizer.review.service import ReviewQueue

_CORPUS = Path("data/processed/extracted_items/material_description_corpus.csv")
_QUALITY = Path("data/manifests/quality_report.json")
_DB = Database()
_NORMALIZER = MaterialNormalizer()


def create_app() -> Dash:
    application = Dash(
        __name__,
        title="NUMMF | Material Intelligence",
        update_title="Loading material intelligence…",
        suppress_callback_exceptions=True,
    )
    application.layout = html.Div(
        className="page-shell",
        children=[
            html.Header(
                className="masthead",
                children=[
                    html.Div([
                        html.Div("NUMMF", className="wordmark"),
                        html.Div("National Unified Material Master Framework", className="product-name"),
                    ]),
                    html.Div("CPSE MATERIAL INTELLIGENCE · PHASE-0 / PHASE-1 PILOT", className="masthead-meta"),
                ],
            ),
            html.Main(
                children=[
                    html.H1("Material harmonization workspace"),
                    html.P(
                        "Evidence-led discovery and review. Recommendations are uncalibrated and never constitute national approval.",
                        className="intro",
                    ),
                    dcc.Tabs(
                        id="workspace-tabs",
                        value="overview",
                        className="workspace-tabs",
                        children=[
                            dcc.Tab(label="Overview", value="overview"),
                            dcc.Tab(label="Material search", value="search"),
                            dcc.Tab(label="Match review", value="match"),
                            dcc.Tab(label="NMC explorer", value="nmc"),
                            dcc.Tab(label="Governance", value="governance"),
                            dcc.Tab(label="Data quality", value="quality"),
                        ],
                    ),
                    html.Div(id="screen-content", className="screen-content"),
                ],
            ),
            html.Footer(
                "Source documents remain authoritative. Weak rules are not expert gold labels; proposals require independent human review.",
                className="footer",
            ),
        ],
    )
    register_callbacks(application)
    return application


def register_callbacks(application: Dash) -> None:
    @application.callback(Output("screen-content", "children"), Input("workspace-tabs", "value"))
    def render_screen(tab: str):
        if tab == "overview":
            stats = _corpus_stats()
            return html.Div([
                html.Div([
                    _stat("Observed descriptions", f"{stats['records']:,}", "Current extracted corpus"),
                    _stat("Organizations", str(stats["organizations"]), "Present in source rows"),
                    _stat("Approved NMCs", "Not measured", "No nationally approved registry evidence"),
                ], className="stat-grid"),
                html.Section(className="panel", children=[
                    html.H2("Current evidence boundary"),
                    html.P("Textual and deterministic rule signals can prioritize expert review. They do not establish functional equivalence or calibrated confidence."),
                    html.P("Spend analysis is unavailable until sourced transaction records are provided."),
                ]),
            ])
        if tab == "search":
            return html.Section(className="panel", children=[
                html.H2("Material search"),
                html.P("Searches source descriptions using BM25 lexical retrieval; dense retrieval is available only when a local Sentence-Transformer model is explicitly configured."),
                dcc.Input(id="search-query", type="text", placeholder="e.g. transformer 11 kV 500 kVA", className="text-input"),
                dcc.Input(id="search-family", type="text", placeholder="Optional family filter", className="text-input"),
                html.Button("Search source corpus", id="search-submit", className="primary-button"),
                html.Div(id="search-results", className="results"),
            ])
        if tab == "match":
            return html.Div(className="review-grid", children=[
                html.Section(className="panel", children=[
                    html.H2("Candidate list"),
                    dcc.Input(id="review-query", type="text", placeholder="Search similar materials", className="text-input"),
                    html.Button("Find candidates", id="review-search-submit", className="primary-button"),
                    dcc.Dropdown(id="review-candidate", options=[], placeholder="Select a source record"),
                    html.Div(id="review-candidate-provenance", className="results"),
                ]),
                html.Section(className="panel", children=[
                    html.H2("Side-by-side comparison"),
                    html.Label("Material A"),
                    dcc.Textarea(id="match-left", placeholder="Material A description", className="text-area"),
                    html.Label("Material B"),
                    dcc.Textarea(id="match-right", placeholder="Choose a candidate or enter text", className="text-area"),
                    html.Button("Compare evidence", id="match-submit", className="primary-button"),
                ]),
                html.Section(className="panel", children=[
                    html.H2("Rationale and compatibility"),
                    html.Pre(id="match-result", className="result-block"),
                ]),
            ])
        if tab == "nmc":
            return html.Section(className="panel", children=[
                html.H2("NMC registry explorer"),
                dcc.Input(id="nmc-query", type="text", placeholder="NMC-IND-…", className="text-input"),
                html.Button("Look up proposal", id="nmc-submit", className="primary-button"),
                html.Pre(id="nmc-result", className="result-block"),
                html.P("Only persisted proposals are shown. This screen cannot approve or publish an NMC."),
            ])
        if tab == "governance":
            tasks = _review_tasks()
            return html.Section(className="panel", children=[
                html.H2("Human review queue"),
                html.P(f"{len(tasks)} persisted review task(s). Decisions and maker-checker approvals are performed through the role-checked API."),
                html.Table([
                    html.Thead(html.Tr([html.Th("Task"), html.Th("Pair"), html.Th("Status"), html.Th("Assigned reviewer")])),
                    html.Tbody([
                        html.Tr([
                            html.Td(task["id"]),
                            html.Td(f"{task['material_a']} ↔ {task['material_b']}"),
                            html.Td(task["status"]),
                            html.Td(task["assigned_to"] or "Unassigned"),
                        ])
                        for task in tasks
                    ]),
                ], className="data-table"),
                html.A("Open API documentation", href="http://127.0.0.1:8000/docs", target="_blank"),
            ])
        if tab == "quality":
            if not _QUALITY.is_file():
                return html.Section(className="panel", children=[
                    html.H2("Data quality"),
                    html.P("No quality profile exists yet. Run `nummf profile-data --manifests` to create one."),
                ])
            report = json.loads(_QUALITY.read_text(encoding="utf-8"))
            return html.Section(className="panel", children=[
                html.H2("Corpus quality profile"),
                html.P(f"Source: {report.get('source_path', 'unknown')} · encoding: {report.get('encoding', 'unknown')}"),
                html.Div([
                    _stat("Rows seen", f"{report.get('records_seen', 0):,}", "Source rows"),
                    _stat("Rows clean / warning", f"{report.get('records_valid', 0):,}", "Not discarded"),
                    _stat("Quarantined", f"{report.get('records_quarantined', 0):,}", "Errors are retained separately"),
                ], className="stat-grid"),
                html.Pre(json.dumps({
                    "errors": report.get("error_counts", {}),
                    "warnings": report.get("warning_counts", {}),
                    "info": report.get("info_counts", {}),
                }, indent=2), className="result-block"),
            ])
        return html.Section(className="panel", children=[html.P("Select a workspace screen.")])

    @application.callback(
        Output("review-candidate", "options"),
        Input("review-search-submit", "n_clicks"),
        Input("review-query", "value"),
        prevent_initial_call=True,
    )
    def search_review_candidates(_clicks: int, query: str):
        if not query:
            return []
        engine, records = _search_index()
        hits = engine.search(query, limit=12)
        return [{
            "label": f"{record.organization}: {record.raw_description[:110]}",
            "value": record.id,
        } for record in (records[str(hit["candidate_id"])] for hit in hits)]

    @application.callback(
        Output("match-right", "value"),
        Output("review-candidate-provenance", "children"),
        Input("review-candidate", "value"),
        prevent_initial_call=True,
    )
    def select_review_candidate(candidate_id: str):
        if not candidate_id:
            return "", ""
        _, records = _search_index()
        record = records.get(candidate_id)
        if record is None:
            return "", "Selected candidate is no longer present in the source index."
        evidence = html.Div([
            html.Div(record.organization),
            html.Div(record.source_system),
            html.Div(record.source_section),
            html.Div(record.source_url or record.source_document or "Source URL not recorded."),
            html.Code(record.id),
        ])
        return record.raw_description, evidence

    @application.callback(
        Output("search-results", "children"),
        Input("search-submit", "n_clicks"),
        Input("search-query", "value"),
        Input("search-family", "value"),
        prevent_initial_call=True,
    )
    def search_records(_clicks: int, query: str, family: str | None):
        if not query:
            return html.P("Enter a material description to search.")
        engine, records = _search_index()
        hits = engine.search(query, limit=20, family=family or None)
        if not hits:
            return html.P("No candidate records found for this query.")
        return html.Table([
            html.Thead(html.Tr([html.Th("Rank"), html.Th("Description"), html.Th("Organization"), html.Th("Lexical score"), html.Th("Evidence ID")])),
            html.Tbody([
                html.Tr([
                    html.Td(hit["rank"]),
                    html.Td(records[str(hit["candidate_id"])].raw_description),
                    html.Td(records[str(hit["candidate_id"])].organization),
                    html.Td(f"{float(hit['lexical_score']):.3f}"),
                    html.Td(str(hit["candidate_id"])),
                ])
                for hit in hits
            ]),
        ], className="data-table")

    @application.callback(
        Output("match-result", "children"),
        Input("match-submit", "n_clicks"),
        Input("match-left", "value"),
        Input("match-right", "value"),
        prevent_initial_call=True,
    )
    def compare_pair(_clicks: int, left: str, right: str):
        if not left or not right:
            return "Provide both material descriptions."
        decision, features = PairScorer().score(left, right)
        return json.dumps({
            "score": decision.score,
            "score_semantics": decision.confidence_band,
            "calibrated_probability": decision.calibrated_probability,
            "compatibility": decision.compatibility,
            "requires_human_review": decision.requires_human_review,
            "rationale": decision.rationale,
            "features": {
                name: getattr(features, name)
                for name in features.__dataclass_fields__
            },
        }, indent=2)

    @application.callback(
        Output("nmc-result", "children"),
        Input("nmc-submit", "n_clicks"),
        Input("nmc-query", "value"),
        prevent_initial_call=True,
    )
    def lookup_nmc(_clicks: int, nmc: str):
        if not nmc:
            return "Enter an NMC to inspect."
        _DB.initialize()
        with _DB.sessions() as session:
            row = session.get(NMCRegistryRow, nmc.strip())
            if row is None:
                return "No persisted NMC proposal found."
            return json.dumps({
                "nmc": row.nmc,
                "family": row.family,
                "status": row.status,
                "approval_status": row.approval_status,
                "attribute_signature": row.attribute_signature,
                "canonical_material_id": row.canonical_material_id,
            }, indent=2)


@lru_cache(maxsize=1)
def _corpus_stats() -> dict[str, int]:
    if not _CORPUS.is_file():
        return {"records": 0, "organizations": 0}
    rows, _ = read_csv_records(_CORPUS)
    return {
        "records": len(rows),
        "organizations": len({row.get("organization", "") for row in rows if row.get("organization")}),
    }


@lru_cache(maxsize=1)
def _search_index() -> tuple[HybridSearchEngine, dict[str, MaterialRecord]]:
    if not _CORPUS.is_file():
        raise FileNotFoundError(f"Material corpus is unavailable: {_CORPUS}")
    rows, _ = read_csv_records(_CORPUS)
    records: list[MaterialRecord] = []
    families: list[str] = []
    for row in rows:
        description = (row.get("description") or "").strip()
        if not description:
            continue
        family = extract_attributes(description).family
        material = MaterialRecord(
            source_system=row.get("source_system") or "unknown",
            source_organization=row.get("organization") or "",
            source_record_id=row.get("tender_id") or row.get("tender_reference") or "",
            source_url=row.get("source_url") or "",
            source_document=row.get("document_url") or "",
            source_section=row.get("source_section") or "",
            material_code=row.get("corpus_id") or "",
            raw_description=description,
            normalized_description=_NORMALIZER.normalize(description).normalized_text,
            organization=row.get("organization") or "",
        )
        records.append(material)
        families.append(family)
    engine = HybridSearchEngine(
        records,
        document_ids=[record.id for record in records],
        families=families,
        embedding_service=EmbeddingService(),
    )
    return engine, {record.id: record for record in records}


def _review_tasks() -> list[dict[str, str]]:
    return [{
        "id": task.id,
        "material_a": task.pair.material_a,
        "material_b": task.pair.material_b,
        "status": task.status.value,
        "assigned_to": task.assigned_to,
    } for task in ReviewQueue(_DB).list(limit=100)]


def _stat(title: str, value: str, detail: str) -> html.Div:
    return html.Div([
        html.Div(title, className="stat-label"),
        html.Div(value, className="stat-value"),
        html.Div(detail, className="stat-detail"),
    ], className="stat-card")


app = create_app()
