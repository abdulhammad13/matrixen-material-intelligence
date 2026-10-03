---
license: other
tags:
- material-master-data
- entity-resolution
- unspsc
- procurement
- tenders
- india
- cpse
- sih26099
pretty_name: SIH 26099 — CPSE Material Code Harmonisation Dataset
size_categories:
- 10K<n<100K
task_categories:
- token-classification
- text-classification
---

# NUMMF — National Unified Material Master Framework

**AI-Driven Standardization & Harmonization of Material Codes Across CPSEs**

This repository combines harvested CPSE procurement/reference data with a
workstation-ready Phase-0/Phase-1 harmonization vertical slice. It includes
provenance-bearing domain contracts, data-quality quarantine, deterministic
normalization and attribute rules, hybrid candidate retrieval, explainable
pair scoring, CPSE-independent NMC proposals, maker-checker review, and
SQLite-backed persistence. Outputs remain proposals until reviewed; there are
no expert gold labels or validated calibrated probabilities in the checkout.

The supplied `NUMMF_Comprehensive_Research_Blueprint.pdf` is not present in
this checkout. The available Solution Design and repository assets were used
as requirements; no claim is made that absent material was reviewed. Source
data reuse and redistribution terms have not been verified. See
`data/manifests/sources.csv` and each source's official terms before reuse.

## Phase-0 / Phase-1 quick start

Requires Python 3.12:

```powershell
python -m pip install -e ".[dev,dashboard,ingestion]"
nummf doctor
nummf profile-data --manifests
nummf serve-api
```

The API is served at `http://127.0.0.1:8000` by default; its OpenAPI page is
`/docs`. Start the review/search dashboard separately with
`nummf serve-dashboard` (default `http://127.0.0.1:8050`). The dashboard is a
local operator interface, not an authentication boundary.

### Reproducible data workflow

```powershell
nummf ingest path\to\source.csv --output data\interim\materials.jsonl
nummf normalize data\interim\materials.jsonl --output data\interim\normalized.jsonl
nummf extract-attributes data\interim\normalized.jsonl --output data\interim\attributes.jsonl
nummf build-index --output data\interim\material_index.json
nummf generate-weak-labels --output data\interim\weak_pair_labels.jsonl
```

`ingest`, `normalize`, and `extract-attributes` preserve JSONL artifacts and
upsert records into the configured SQLAlchemy database. The default is the
ignored local database `data/processed/nummf.db`; configure
`NUMMF_DATABASE_URL` for a PostgreSQL deployment. The PostgreSQL optional
dependencies are available with `pip install -e ".[postgres]"`; apply the
initial schema with `alembic upgrade head` after setting `NUMMF_DATABASE_URL`.
The migration was exercised on SQLite; PostgreSQL deployment is not validated
in this checkout. Live SAP connectors are not part of this vertical slice.
Redis caching is disabled unless `REDIS_URL` is set; install
`pip install -e ".[cache]"` and run an authorized Redis instance before
enabling it.

`nummf profile-data --manifests` writes a row-level quality report,
`clean.csv`, `quarantine.csv`, and `row_issues.csv` under
`data/interim/data_quality/`, plus `sources.csv`, `files.csv`, `lineage.csv`,
and `quality_report.json` under `data/manifests/`. The raw source tree is not
rewritten. Quarantined rows remain inspectable; warning-only rows stay in the
clean export with their reported issues.

### Matching and governance boundaries

- `NUMMF_EMBEDDING_BACKEND=lexical` is the deterministic offline default and
  does not claim semantic-vector capability. To use local CPU
  Sentence-Transformers, install `.[ml]` and explicitly configure
  `NUMMF_EMBEDDING_BACKEND=sentence-transformers` plus
  `NUMMF_EMBEDDING_MODEL`.
- Pair scores are uncalibrated ranking signals. No score is presented as a
  match probability, and the current matching path always requires human
  review.
- Weak labels are explicitly marked `weak_rule`; evaluation and calibration
  reject weak labels and require expert-gold data with grouped validation.
- NMC generation is CPSE-independent and creates proposals only. A nationally
  approved code requires the distinct human review/checker workflow.
- Sovereign/offline behavior is the default. DeepSeek enrichment requires
  explicit opt-in and an API key; deterministic extraction does not invent
  source material rows.
- Role headers used by the development API are not identity authentication.
  Deploy behind an authenticated, authorized gateway before exposing it to
  users or networks.

### Validation

```powershell
python -m compileall -q src scripts tests
python -m ruff check .
python -m mypy src/cpse_harmonizer/domain src/cpse_harmonizer/data_quality
python -m pytest -q
```

The Research Blueprint PDF, expert-reviewed labels, spend/transaction data,
verified source redistribution terms, and production SAP/PostgreSQL deployment
configuration are not present. Accordingly, this checkout does not report
business performance, approved national mappings, or model-calibration
metrics.

---

## Harvested corpus and references

The following tables describe the collected data snapshot and the earlier
harvesting work. Current file counts and quality findings are generated by
`nummf profile-data --manifests`; counts below are not treated as runtime
guarantees.

---

## 1. Headline numbers

| Dataset | Rows | File |
|---|---|---|
| **Material description corpus** (main table) | **21,513** | `data/processed/extracted_items/material_description_corpus.csv` |
| NTPC NIT metadata | 1,418 | `data/raw/ntpc/tenders/nit_details.csv` |
| NTPC document index | 1,626 | `data/raw/ntpc/tenders/documents_index.csv` |
| NTPC per-document text | 1,615 | `data/processed/extracted_items/ntpc_doc_text.csv` + `ntpc_text/` |
| NTPC tables pulled from PDFs | 78,216 | `data/processed/extracted_items/ntpc_doc_tables.csv` |
| NTPC structured material lines | 486 | `data/processed/extracted_items/ntpc_material_items.csv` |
| IOCL tender metadata | 179 | `data/raw/iocl/tenders/tender_details.csv` |
| IOCL bid-cover inventory | 3,715 | `data/raw/iocl/tenders/bid_covers.csv` |
| IOCL procurement-plan items | 1,224 | `data/processed/extracted_items/iocl_procurement_plan_items.csv` |
| OIL India live tenders | 180 (140 unique) | `data/raw/oil_india/tenders/live_tenders.csv` |
| OIL India archived tenders | 4,051 (4,016 unique) | `data/raw/oil_india/tenders/archive_tenders.csv` |
| OIL India historical tenders | **12,116 (11,987 unique)** | `data/raw/oil_india/tenders/old_tenders.csv` |
| OIL India tender detail pages | 4,165 (4,152 unique) | `data/raw/oil_india/tenders/tender_details.csv` |
| OIL India NIT download links | 4,152 | `data/raw/oil_india/tenders/nit_documents_index.csv` |
| OIL India corrigenda | 145 | `data/raw/oil_india/tenders/corrigenda.csv` |
| UNSPSC master taxonomy | **71,502** | `data/reference/unspsc/unspsc_master.csv` |
| UNSPSC industrial subset | 12,771 | `data/reference/unspsc/unspsc_industrial_subset.csv` |
| CPPP organisations + live counts | 235 | `data/raw/cppp/tenders/organisations_with_tender_counts.csv` |

---

## 2. What was reachable, and what was not

| Source | Status | What we got |
|---|---|---|
| **NTPC** `ntpctender.ntpc.co.in` | ✅ full | 1,418 NITs, 1,626 documents indexed, 1,615 PDFs text-extracted |
| **IOCL** `iocletenders.nic.in` | ✅ full | 179 tenders, full metadata, 3,715 bid-cover rows |
| **IOCL** `iocl.com` | ✅ full | 104-page Future Procurement Plan → 1,224 item rows + 2 item-list PDFs |
| **OIL India** `oil-india.com` | ✅ full | 180 live, 4,016 archived, 11,987 historical tenders, 145 corrigenda, EoI/pre-bid, 4,152 NIT links |
| **UNSPSC** | ✅ full | 71,502 commodities / 5,313 classes / 465 families / 57 segments |
| **CPPP** `eprocure.gov.in` | ⚠️ partial | Portal reachable, but every search POST is captcha + session-gated. Only the org list (235 orgs / 2,452 live tenders) and the 85-category taxonomy came through |
| **SAIL** `eproc.sail.co.in` | ❌ blocked | REST API (`/rest/openarea/*`) discovered, but every call returns a generic error page (WAF) |
| **ONGC** | ❌ unreachable | `ongcindia.com` / `ongc.co.in` hosts time out from this network |
| **BPCL** | ❌ blocked | HTTP 403 (CloudFront) |
| **Coal India** | ❌ blocked | HTTP 403 |
| **GeM** `gem.gov.in` | ❌ unreachable | Host times out — but GeM data reaches us indirectly (see below) |
| **EIL** `tenders.eil.co.in` | ❌ unreachable | Host times out |
| **data.gov.in** | ❌ gated | Public API needs a key; the catalogue site is client-side rendered |
| **OIL India SAP SRM** | ❌ login-only | `etender.srm.oilindia.in` serves a logon page |

**GeM is still well represented**, just not from the GeM portal: OIL India has a
whole `GeM Tenders` category (2,820 archived + 102 live records), 2,085
historical tenders are categorised `GEM`, and NTPC NITs carry GeM item codes and
GeMARPTS search strings.

---

## 3. Directory map

```
data/
├── raw/                                     untouched source output
│   ├── ntpc/tenders/     nit_details.csv, listing_rows.csv,
│   │                     documents_index.csv, raw_html_sample/ (60)
│   ├── ntpc/documents/   70 sample NIT/corrigendum PDFs (full index kept)
│   ├── iocl/tenders/     tender_details.csv, search_rows.csv, bid_covers.csv,
│   │                     3 source PDFs, raw_html_sample/ (50)
│   ├── oil_india/tenders/  live/archive/old/tender_details/nit_documents_index/
│   │                       corrigenda/eoi CSVs, raw_html_sample/ (60)
│   ├── oil_india/documents/  sample NIT PDF
│   └── cppp/tenders/     organisations_with_tender_counts.csv
├── reference/
│   ├── unspsc/           unspsc_master.csv (71,502),
│   │                     unspsc_industrial_subset.csv (12,771),
│   │                     oklahoma_unspsc.csv (original download)
│   ├── abbreviations/    material_abbreviations.csv (154),
│   │                     material_grades.csv (58), pressure_classes.csv (28)
│   ├── units/            unit_normalisation.csv (125)
│   ├── cppp_product_categories.csv (85 categories)
│   └── ntpc_locations.csv (116 units/projects)
└── processed/extracted_items/
    ├── material_description_corpus.csv      ← main working table
    ├── ntpc_doc_text.csv, ntpc_doc_tables.csv
    ├── ntpc_material_items.csv
    ├── iocl_procurement_plan_items.csv
    └── ntpc_text/                           1,615 per-document .txt
```

Total 119 MB, 1,894 files. `PRUNED.txt` lists the 7,133 bulky files (1.3 GB)
that were removed to stay inside the snapshot budget — every one is
re-downloadable from the URLs kept in the CSVs, and the harvest scripts
reproduce them.

---

## 4. The main table: `material_description_corpus.csv`

One row = one real, publicly published material/item description, tagged with
the organisation that published it and where it came from.

| column | meaning |
|---|---|
| `corpus_id` | stable row id (`M000001`…) |
| `organization` | NTPC / IOCL / Oil India |
| `source_system` | host the record came from |
| `source_section` | which listing, page or document |
| `tender_reference`, `tender_id` | publisher's own identifiers |
| `description` | the material/item description text |
| `description_kind` | `tender_title`, `nit_brief_description`, `historical_tender`, `tender_detail`, `procurement_plan_item`, `doc_spec_string`, … |
| `item_type_hint` | coarse type from a keyword pass (valve, pump, pipe, cable…) |
| `quantity`, `unit` | where the source gave them |
| `location`, `product_category` | publisher metadata |
| `document_url`, `source_url` | provenance — always kept |

Split by organisation: **Oil India 18,950 · NTPC 1,843 · IOCL 720**.
17,400 of the 21,513 descriptions are distinct strings; the rest repeat across
organisations or across a tender's title / work-description pair.

Cross-organisation near-duplicates are **kept on purpose** — they are exactly
the variation the harmonisation step has to resolve. Only exact duplicates
within one organisation *and* description kind are collapsed.

Coarse type distribution (top): pipe 1,214 · pump 927 · tank 580 · cable 330 ·
steel 325 · instrument 259 · spares 246 · chemical 236 · valve 224 ·
pipe fitting 200 · compressor 184 · safety valve 183 · transformer 151 ·
flange 141 · gate valve 131.

---

## 5. Notable content

**Real GeM catalogue strings** from NTPC NIT PDFs — already semi-structured
material codes:

```
CABLE,PWR,240MM2,1C,STRANDED,AL,11KV
CABLE, PWR, 150MM2, 1C, STRANDED, AL, 11KV
GASKET,17.5KV,1000A,AREVA
GASKET,3.6KV,2000A,AREVA
SEAMLESS,SS,A312-TP304L,80S,15MM , PIPE
PIPE:BLK, CORTEN,A423GR1,ERW,2MM,40MM
```

**IOCL procurement-plan items** with quantities, units and values:

```
Vessels/Drums/Tanks                          99 Nos.   ₹108.06 Cr
Pumps                                       275 Nos.   ₹138.08 Cr
Heat Ex/Air coolers/Fin Fan Coolers         130 Nos.   ₹142.66 Cr
Rotary Valves/Safety Valves/Control Valves/On-off Valves…
Synthetic base oil Poly alfa olefin 4 CST, PAO 40(ST 55578)
Benzene hydrogenation catalyst for ISOM unit
Sample Coolers (PI) & Sample Bombs (PE)
```

**OIL India historical tenders** — the densest source of true material text:

```
Line Pipe, 2" , ERW Galvanised, Screwed (Q3)
Conventional Gas Lift Mandrels
PMCC PANEL – 01 NOS.
OXYGEN GAS STORAGE CYLINDER, 7 CUM (Q3), ACETYLENE GAS STORAGE CYLINDER, 6-7 CUM (Q3)
GATE VALVE -STEEL
High pressure high temperature (HPHT), Four cells (175ml), filter press (Q3)
SUPPLY OF CHAIN TONGS AND PIPE WRENCH UNDER RATE CONTRACT
Supply of Stage cementing collars
```

**IOCL tender titles** — long, specification-rich free text, exactly what needs
normalising:

```
Procurement of Capital Spare, Complete Trip and Throttle valve (Make Siemens
Energy Industrial Turbomachinery India Private Limited) of WGC Turbine as per
Insurance spares guideline rotary 2025 26 at IOCL Paradip Refinery

SP/B269-000-WB-MR-3741/396 - VALVES-GATE, GLOBE, CHECK FOR P-25 PROJECT
```

---

## 6. Reference tables

| file | rows | purpose |
|---|---|---|
| `unspsc_master.csv` | 71,502 | full UNSPSC segment→family→class→commodity hierarchy — the target code system |
| `unspsc_industrial_subset.csv` | 12,771 | the 20 industrial segments relevant to CPSE materials |
| `material_abbreviations.csv` | 154 | `BALL VL`→`BALL VALVE`, `NRV`→`CHECK VALVE`, `RF`→`RAISED FACE`, … |
| `material_grades.csv` | 58 | ASTM / API / IS grade tokens → standard, grade, description |
| `pressure_classes.csv` | 28 | `300#` / `CL 300` / `CLASS-300` → `CLASS 300` (≈PN50) |
| `unit_normalisation.csv` | 125 | `EA`/`NOS`/`PCS`→`NOS`, inch↔mm size equivalences, mass/volume/pressure factors |
| `cppp_product_categories.csv` | 85 | CPPP's own product-category taxonomy |
| `ntpc_locations.csv` | 116 | NTPC stations / projects |

---

## 7. Scripts

| script | what it does |
|---|---|
| `scripts/harvest_ntpc.py` | NTPC listing sweep (types + 130 material keywords), NIT detail pages, corrigendum JSON API, document download |
| `scripts/harvest_iocl.py` | IOCL captcha-free keyword sweep; search **and** detail fetch share one session (required) |
| `scripts/harvest_oil_india.py` | OIL India `live` / `rest` / `old` / `details` subcommands, checkpointed |
| `scripts/extract_ntpc_docs.py` | memory-safe text + table extraction over the NTPC PDFs |
| `scripts/extract_ntpc_material_items.py` | GeM item strings, BOQ lines, spec strings from the NIT text |
| `scripts/extract_iocl_plan.py` | IOCL Future Procurement Plan → item rows |
| `scripts/extract_oil_nit_links.py` | recover NIT download links from saved detail pages |
| `scripts/build_reference_tables.py` | abbreviation / unit / grade / pressure-class tables |
| `scripts/build_material_corpus.py` | merge everything into `material_description_corpus.csv` |
| `scripts/prune_workspace.py` | trim reproducible bulk, log to `PRUNED.txt` |

Reproduce everything with:

```
python3 scripts/harvest_ntpc.py
python3 scripts/harvest_iocl.py            # IOCL_GENERIC=1 for the wider sweep
python3 scripts/harvest_oil_india.py live
python3 scripts/harvest_oil_india.py rest
python3 scripts/harvest_oil_india.py old
python3 scripts/harvest_oil_india.py details
python3 scripts/extract_ntpc_docs.py
python3 scripts/extract_ntpc_material_items.py
python3 scripts/extract_iocl_plan.py
python3 scripts/extract_oil_nit_links.py
python3 scripts/build_reference_tables.py
python3 scripts/build_material_corpus.py
```

---

## 8. Four things worth knowing about these portals

**1. IOCL's detail URLs are session-bound.** The listing hands out
`…&sp=<token>` links that only resolve for a session which has already fetched
the Home page. A fresh session gets a 1,410-byte stub with zero fields instead
of the 79,870-byte page. `harvest_iocl.py` therefore searches and fetches
inside one session.

**2. IOCL's search caps at 20 hits per keyword**, most-recent first, with no
pagination. Broad terms (`the`, `supply`, `procurement`) each return a
different 20, so the harvester sweeps 230 keywords and unions the results —
179 distinct tenders.

**3. OIL India's Drupal pager loops past the end of a result set.** The archive
listing advertises `data-total=450` but keeps returning rows forever: a naive
crawl produced 19,570 rows holding only 449 distinct tender numbers (97.6 %
duplicates). The harvester now stops when a page yields no unseen tender
number. It also has to tolerate *transient* blank pages — page 378 of
`/old-tender` comes back empty while pages 379–1,311 all carry data, so an
early version gave up 9,000 rows short.

**4. OIL India's NIT links have no file extension.** They are served by
`/download-tender-document?ten_detail=…` and answer `binary/octet-stream`, so
matching on `.pdf` finds nothing and the extension has to come from the payload
magic bytes. All 4,152 links are indexed in `nit_documents_index.csv`; only a
sample is downloaded because the advertised sizes run to several GB in total.
