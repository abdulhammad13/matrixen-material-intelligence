# AI-Driven Standardization and Harmonization of Material Codes Across CPSEs

**Problem Statement ID:** 26099

This repository is the project scaffold for a multi-CPSE material harmonization
platform. Its modules are arranged to follow the requested delivery sequence:

1. Multi-CPSE data ingestion
2. Schema intelligence
3. Data quality
4. NLP extraction
5. Unit and attribute normalization
6. Hybrid search
7. Semantic matching
8. Technical compatibility
9. Relationship classification
10. Clustering
11. Canonical material master
12. Common material ID
13. Human review
14. Active learning
15. Procurement intelligence
16. Audit and governance
17. FastAPI
18. Dashboard command centre
19. ERP/SAP integration

## Repository layout

```text
cpse-material-harmonization/
├── config/                         # Environment-specific, non-secret settings
├── data/
│   ├── raw/                        # Source extracts; access-controlled, never committed
│   ├── interim/                    # Temporary pipeline outputs
│   ├── processed/                  # Validated and normalized outputs
│   └── reference/                  # Approved taxonomies, units, and reference data
├── docs/
│   ├── architecture/               # Architecture diagrams and design notes
│   ├── data-dictionary/            # Field definitions and source mappings
│   └── decisions/                  # Architecture decision records
├── scripts/                        # Local setup, ingestion, and maintenance commands
├── src/cpse_harmonizer/
│   ├── ingestion/multi_cpse/
│   ├── schema_intelligence/
│   ├── data_quality/
│   ├── extraction/nlp/
│   ├── normalization/{units,attributes}/
│   ├── retrieval/hybrid_search/
│   ├── matching/{semantic,technical_compatibility,relationships}/
│   ├── clustering/
│   ├── master_data/{canonical_material,common_material_id}/
│   ├── review/human_review/
│   ├── learning/active_learning/
│   ├── intelligence/procurement/
│   ├── governance/audit/
│   ├── api/                        # FastAPI application and route modules
│   ├── dashboard/                  # Dashboard command-centre UI
│   └── integrations/erp_sap/
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

## Getting started

Requires Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
```

The directories are intentionally scaffolding: implementation should proceed
stage by stage, with contracts and tests added before connecting later pipeline
stages. Keep credentials and CPSE source data out of version control. Use
`config/` for safe configuration templates and environment variables or a
secrets manager for credentials.

## Design boundaries

- Keep source-specific adapters inside `ingestion/multi_cpse/`; downstream
  stages should consume a shared internal record contract.
- Keep deterministic unit/attribute normalization separate from probabilistic
  semantic matching and technical compatibility scoring.
- Persist canonical-material decisions and Common Material IDs with provenance
  and audit history.
- Treat human review as a first-class workflow; feed approved outcomes into
  active learning with appropriate validation and governance.
- Expose application use cases through the API rather than coupling the
  dashboard or ERP/SAP adapters directly to pipeline internals.
- Do not commit raw, interim, or processed business data.
