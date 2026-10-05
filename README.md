<div align="center">

# MATRIXEN
### Material Intelligence for CPSE Harmonization

**From fragmented material descriptions to a traceable, reviewable evidence trail.**

A Python-based prototype for discovering related material descriptions, normalizing technical attributes, scoring candidate equivalence, proposing CPSE-independent National Material Codes (NMCs), and routing consequential cases through human review.

<br/>

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Dash](https://img.shields.io/badge/UI-Dash-119DFF?logo=plotly&logoColor=white)](https://dash.plotly.com/)
[![SQLAlchemy](https://img.shields.io/badge/Data-SQLAlchemy-D71F00)](https://www.sqlalchemy.org/)
[![CI](https://github.com/abdulhammad13/matrixen-material-intelligence/actions/workflows/python-package.yml/badge.svg)](https://github.com/abdulhammad13/matrixen-material-intelligence/actions/workflows/python-package.yml)
[![License](https://img.shields.io/badge/License-See%20repository-lightgrey)](https://github.com/abdulhammad13/matrixen-material-intelligence)

### 🚀 Live workspace
**[Open Matrixen on Render →](https://matrixen-material-dashboard.onrender.com)**

### 🏆 SIH 2026
**Problem context:** SIH26099 — AI-driven standardization & harmonization of material codes across CPSEs

</div>

---

## Why Matrixen?

Large public-sector procurement ecosystems often describe similar materials in different ways: abbreviations, reordered attributes, inconsistent units, publisher-specific identifiers, and specification-heavy free text.

Matrixen is designed as an **evidence-first harmonization layer** rather than a black-box “similarity score”. The prototype keeps the original wording and provenance visible while adding deterministic normalization, structured attribute evidence, retrieval, explainable matching, NMC proposals, persistence, and human-review boundaries.

> **Core principle:** similarity can prioritize attention; it does not silently become approval.

---

## What the prototype does

| Capability | What Matrixen provides |
|---|---|
| **Material discovery** | Search source descriptions using the current retrieval engine |
| **Normalization** | Canonicalize wording, units, abbreviations, and attribute forms |
| **Attribute extraction** | Turn technical descriptions into structured, typed signals |
| **Hybrid retrieval** | Rank candidate source records for further inspection |
| **Pair matching** | Compare two descriptions using lexical, attribute, unit, numeric, HSN and other available signals |
| **Explainability** | Expose rationale/features instead of returning only a score |
| **NMC proposal** | Generate a stable CPSE-independent proposal from structured identity attributes |
| **Governance** | Persist review tasks and keep human decision points explicit |
| **Data quality** | Profile source rows, warnings, errors, provenance gaps and quarantined records |
| **Audit trail** | Record hash-linked events for important material/NMC operations |
| **API** | FastAPI endpoints for normalization, search, matching and NMC workflows |
| **Dashboard** | Dash workspace for search, comparison, NMC lookup, governance and quality inspection |

---

## System flow

```mermaid
flowchart LR
    A[CPSE procurement sources] --> B[Ingestion]
    B --> C[Data quality + provenance]
    C --> D[Normalization]
    D --> E[Attribute extraction]
    E --> F[Candidate retrieval]
    F --> G[Pair scoring]
    G --> H[Evidence + rationale]
    H --> I[Human review]
    I --> J[NMC proposal / mapping context]
    J --> K[Audit + persistence]
```

The architecture is deliberately separated into layers so deterministic evidence, retrieval, scoring, governance, and persistence can evolve independently.

---

## Architecture at a glance

```text
matrixen-material-intelligence/
│
├── src/cpse_harmonizer/
│   ├── api/                 FastAPI application + endpoints
│   ├── data_quality/        Row-level checks, reports, quarantine
│   ├── domain/              Core material / match / review contracts
│   ├── evaluation/          Metrics, grouping, calibration safeguards
│   ├── extraction/          Embedding service + optional DeepSeek enrichment
│   ├── governance/          Audit logging
│   ├── ingestion/           Portal/crawler ingestion components
│   ├── intelligence/        Higher-level intelligence services
│   ├── learning/            Weak supervision / learning utilities
│   ├── master_data/         Canonical material + NMC generation
│   ├── matching/            Pair scoring and compatibility features
│   ├── normalization/       Technical normalization + attribute extraction
│   ├── persistence/         SQLAlchemy models and repository layer
│   ├── retrieval/           Candidate search / ranking
│   └── review/              Human-review workflow
│
├── data/
│   ├── raw/                 Harvested source artifacts
│   ├── processed/           Working material corpus / extracted text
│   └── reference/           UNSPSC, units, grades, abbreviations, etc.
│
├── docs/
│   ├── architecture/
│   ├── data-dictionary/
│   ├── decisions/
│   └── solutions_design/
│
├── scripts/                 Harvesting, extraction, corpus + reference builders
├── migrations/               Database migration history
├── tests/                   Automated tests
└── pyproject.toml          Package, dependency and tooling configuration
```

---

## Data snapshot

The repository README's current corpus snapshot records a **21,513-row material description corpus** spanning:

- **Oil India:** 18,950 descriptions
- **NTPC:** 1,843 descriptions
- **IOCL:** 720 descriptions
- **UNSPSC master taxonomy:** 71,502 records
- **UNSPSC industrial subset:** 12,771 records

The harvested snapshot also includes tender metadata, extracted document text/tables, procurement-plan items, reference tables, and provenance fields.

### Why the near-duplicates matter

Cross-organization near-duplicates are retained intentionally: those variations are the actual harmonization problem the system is meant to inspect. The corpus is therefore not treated as a clean “one description = one material” master table.

---

## Provenance-first design

Matrixen keeps source context attached to records wherever it is available, including fields such as:

```text
source_system
source_organization
source_record_id
source_url
source_document
source_page
source_section
material_code
raw_description
normalized_description
```

This allows a reviewer to move from a model signal back toward the source evidence instead of interpreting a score in isolation.

---

## Matching is a decision-support signal

The current prototype intentionally does **not** claim calibrated match probabilities.

Available scoring features can include:

- lexical similarity
- dense similarity when configured
- cross-encoder score when configured
- material-family agreement
- attribute agreement/conflict
- UOM compatibility
- standard compatibility
- HSN compatibility when supplied
- manufacturer compatibility when supplied
- numeric proximity
- technical hard conflicts

A high score is therefore a **ranking / review signal**, not automatic national equivalence.

---

## NMC generation

Matrixen can propose a stable CPSE-independent identifier from recognized material-family attributes.

Example structure:

```text
NMC-IND-<FAMILY>-<ATTRIBUTE-SIGNATURE>
```

The generated object remains:

```text
PROPOSED_REQUIRES_REVIEW
approval_status = PENDING
```

The proposal generator is intentionally separate from the human checker/approval boundary.

---

## Quick start

### Requirements

- Python **3.12.x**
- Git
- A virtual environment is recommended

The repository pins Python 3.12 compatibility with:

```toml
requires-python = ">=3.12,<3.13"
```

### Install

```powershell
python -m pip install -e ".[dev,dashboard,ingestion]"
```

### Verify the environment

```powershell
nummf doctor
python -m compileall -q src scripts tests
python -m ruff check .
python -m pytest -q
```

### Generate the data-quality profile

```powershell
nummf profile-data --manifests
```

### Run the API

```powershell
nummf serve-api
```

Open:

```text
http://127.0.0.1:8000/docs
```

### Run the Dash workspace

In a second terminal:

```powershell
nummf serve-dashboard
```

Open:

```text
http://127.0.0.1:8050
```

---

## Reproducible material workflow

```powershell
nummf ingest path\to\source.csv --output data\interim\materials.jsonl
nummf normalize data\interim\materials.jsonl --output data\interim\normalized.jsonl
nummf extract-attributes data\interim\normalized.jsonl --output data\interim\attributes.jsonl
nummf build-index --output data\interim\material_index.json
nummf generate-weak-labels --output data\interim\weak_pair_labels.jsonl
```

The repository keeps raw inputs untouched and separates clean, quarantined, processed, and review-oriented artifacts.

---

## API surface

The FastAPI application currently exposes workflows including:

```text
GET  /health
GET  /version

POST /materials/normalize
POST /materials/attributes
POST /materials/search
POST /materials/match
POST /materials/match/batch
POST /materials/nmc/propose

GET  /materials/{material_id}
GET  /nmc/{nmc}
GET  /nmc/{nmc}/mappings
```

OpenAPI / Swagger UI is available at `/docs` when the API is running.

---

## Data-quality and governance model

Matrixen separates three concerns that are often collapsed in data-matching prototypes:

```text
DATA QUALITY
    ↓
Is the source evidence usable?

INTELLIGENCE
    ↓
What appears related, and why?

GOVERNANCE
    ↓
Who is accountable for the consequential decision?
```

The dashboard therefore does not expose a shortcut that turns an inferred match or an NMC proposal directly into a nationally approved record.

---

## Source and access reality

The harvested snapshot documents which source systems were reachable during collection and which were blocked, gated, timed out, or login-only from the collection environment.

Examples documented by the project include:

| Source | Snapshot status |
|---|---|
| NTPC tender portal | Reachable |
| IOCL tender portal | Reachable |
| OIL India | Reachable |
| UNSPSC | Reachable |
| CPPP | Partial / session-captcha constrained |
| SAIL | Blocked by WAF during collection |
| ONGC | Unreachable from collection environment |
| BPCL | HTTP 403 during collection |
| Coal India | HTTP 403 during collection |
| GeM | Portal unavailable from collection environment; indirect representation exists |
| data.gov.in | API/catalogue access constraints |
| OIL India SAP SRM | Login-only |

These are **collection-environment observations**, not claims about permanent availability of those systems.

---

## Deployment

### Render

The dashboard is deployable as a Python web service with Gunicorn.

Recommended runtime:

```text
Python: 3.12.11
```

Example build command:

```bash
pip install -r requirements.txt
```

Example start command:

```bash
gunicorn --chdir src cpse_harmonizer.dashboard.app:server --bind 0.0.0.0:$PORT --workers 1 --timeout 180
```

Set the Render environment variable:

```text
PYTHON_VERSION=3.12.11
```

The project uses a local SQLite development default. For a persistent production relational store, configure PostgreSQL with `NUMMF_DATABASE_URL` and apply the project migrations.

> Render's free service can spin down when idle; the first request after inactivity may therefore be slower.

---

## Optional capabilities

### Lexical / deterministic mode

```text
NUMMF_EMBEDDING_BACKEND=lexical
```

This is the deterministic offline-friendly pathway and should not be described as semantic-vector capability.

### Local Sentence Transformers

Install the ML extra and configure the embedding backend explicitly:

```powershell
python -m pip install -e ".[ml]"
```

```text
NUMMF_EMBEDDING_BACKEND=sentence-transformers
NUMMF_EMBEDDING_MODEL=intfloat/multilingual-e5-small
```

### DeepSeek enrichment

DeepSeek is optional and should only be enabled deliberately with the required API configuration. Deterministic extraction remains the baseline path.

---

## Validation philosophy

The repository prefers honest validation over inflated demo metrics.

The current checkout does **not** claim:

- expert-gold match accuracy
- calibrated match probabilities
- nationally approved mappings
- production SAP integration
- production-grade authentication / authorization
- verified data-redistribution rights for every harvested source

Weak-rule labels are explicitly distinguished from expert-gold labels, and evaluation/calibration code requires appropriate group separation.

---

## Documentation

Useful project material lives under:

```text
docs/architecture/
docs/data-dictionary/
docs/decisions/
docs/solutions_design/
```

The repository also contains its data manifest, pruning record, migrations, tests, extraction scripts, and reference-building scripts.

---

## Team

### Team Fresh Minds · Jamia Millia Islamia

**B.Tech '30 · JMI**

The Matrixen build combines AI/ML design, data engineering, validation, product design, presentation, and technical storytelling.

| Member | Focus |
|---|---|
| Abdul Hammad | AI / ML Architecture |
| MD Faisal Raza | R&D Pipeline Engineering |
| Zishan Afroz | Innovation & Validation |
| Zarish Parveen | Presentation & Deck Design |
| Mobashra Fatima | Presentation & Narrative |
| Nasiba Hoda | Product Pitch & Storytelling |

---

## Project boundaries

Matrixen is currently a **Phase-0 / Phase-1 prototype and decision-support workspace**. It is not a replacement for an enterprise MDM/ERP authority layer, and it should not be interpreted as an autonomous national approval system.

That boundary is intentional: source evidence, model signals, proposed canonical data, and accountable human decisions should remain distinguishable.

---

## License & data-use note

See the repository's current source manifests and project documentation before redistributing harvested source data. The current checkout does not assert a universal redistribution license for every external dataset or portal-derived artifact.

The software and data snapshot should therefore be evaluated separately for licensing and permitted reuse.

---

<div align="center">

### Explore the project

**[GitHub Repository](https://github.com/abdulhammad13/matrixen-material-intelligence)** · **[Live Dashboard](https://matrixen-material-dashboard.onrender.com)**

Built by **Team Fresh Minds · Jamia Millia Islamia**

</div>
