"""Reproducible NUMMF developer and data-preparation commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cpse_harmonizer.data_quality.checker import (
    DataQualityChecker,
    read_csv_records,
    write_quality_outputs,
)
from cpse_harmonizer.data_quality.manifests import generate_manifests
from cpse_harmonizer.domain.models import MaterialRecord
from cpse_harmonizer.evaluation.calibration import PairCalibrator
from cpse_harmonizer.evaluation.metrics import pair_classification_metrics
from cpse_harmonizer.evaluation.splitting import grouped_holdout_indices
from cpse_harmonizer.extraction.embedding_service import EmbeddingService
from cpse_harmonizer.learning.weak_supervision import WeakLabelGenerator
from cpse_harmonizer.master_data.nmc_generator import NMCGenerator
from cpse_harmonizer.normalization.attribute_extractor import extract_attributes
from cpse_harmonizer.normalization.normalizer import MaterialNormalizer
from cpse_harmonizer.persistence.database import Database
from cpse_harmonizer.persistence.repository import MaterialRepository
from cpse_harmonizer.retrieval.hybrid_search import HybridSearchEngine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nummf", description="NUMMF Phase-0/Phase-1 tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check runtime, repository assets, and configuration.")
    profile = subparsers.add_parser(
        "profile-data", help="Profile a CSV and write quality/manifests."
    )
    profile.add_argument(
        "input", nargs="?", default="data/processed/extracted_items/material_description_corpus.csv"
    )
    profile.add_argument("--output-dir", default="data/interim/data_quality")
    profile.add_argument(
        "--manifests", action="store_true", help="Generate repository-wide data manifests."
    )

    ingest = subparsers.add_parser(
        "ingest", help="Read a source CSV into provenance-tagged JSONL without modifying raw input."
    )
    ingest.add_argument("input")
    ingest.add_argument("--output", default="data/interim/material_records.jsonl")

    normalize = subparsers.add_parser(
        "normalize", help="Normalize provenance-tagged material JSONL."
    )
    normalize.add_argument("input")
    normalize.add_argument("--output", default="data/interim/normalized_materials.jsonl")

    attributes = subparsers.add_parser(
        "extract-attributes", help="Extract typed, evidence-spanned attributes from JSONL."
    )
    attributes.add_argument("input")
    attributes.add_argument("--output", default="data/interim/material_attributes.jsonl")

    index = subparsers.add_parser(
        "build-index", help="Build a persisted local hybrid candidate index from a CSV."
    )
    index.add_argument(
        "input", nargs="?", default="data/processed/extracted_items/material_description_corpus.csv"
    )
    index.add_argument("--output", default="data/interim/material_index.json")

    weak = subparsers.add_parser(
        "generate-weak-labels", help="Write weak-rule pairs to a separate JSONL file."
    )
    weak.add_argument(
        "input", nargs="?", default="data/processed/extracted_items/material_description_corpus.csv"
    )
    weak.add_argument("--output", default="data/interim/weak_pair_labels.jsonl")

    negatives = subparsers.add_parser(
        "mine-hard-negatives", help="Export only rule-evidenced weak negative pairs."
    )
    negatives.add_argument("input", nargs="?", default="data/interim/weak_pair_labels.jsonl")
    negatives.add_argument("--output", default="data/interim/hard_negatives.jsonl")

    train = subparsers.add_parser(
        "train", help="Train only after reviewed gold labels and a split are available."
    )
    train.add_argument("--labels", default="data/gold/pair_labels")

    evaluate = subparsers.add_parser(
        "evaluate", help="Evaluate explicit held-out expert labels with group isolation."
    )
    evaluate.add_argument("input", nargs="?", default="data/gold/pair_labels/evaluation.jsonl")
    evaluate.add_argument("--group-field", default="group_id")
    evaluate.add_argument("--threshold", type=float, default=0.5)

    calibrate = subparsers.add_parser(
        "calibrate", help="Fit a calibrator to an explicit, group-separated gold validation JSONL."
    )
    calibrate.add_argument("input", nargs="?", default="data/gold/pair_labels/calibration.jsonl")
    calibrate.add_argument("--method", choices=("platt", "isotonic"), default="platt")
    calibrate.add_argument("--output", default="models/calibration.json")

    nmc = subparsers.add_parser(
        "propose-nmc", help="Propose (never approve) an NMC from structured text attributes."
    )
    nmc.add_argument("description")

    export = subparsers.add_parser("review-export", help="Export persisted review tasks as JSONL.")
    export.add_argument("--output", default="data/interim/review_tasks.jsonl")

    api = subparsers.add_parser("serve-api", help="Run the FastAPI application.")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)

    dashboard = subparsers.add_parser(
        "serve-dashboard", help="Run the Dash review/search interface."
    )
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8050)

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command == "profile-data":
        report, clean, quarantine = DataQualityChecker().profile_csv(args.input)
        write_quality_outputs(report, clean, quarantine, args.output_dir)
        result: dict[str, Any] = report.as_dict()
        if args.manifests:
            result["manifests"] = generate_manifests(corpus_path=args.input)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "ingest":
        rows, _ = read_csv_records(args.input)
        records = _records_from_rows(rows, args.input)
        persisted = MaterialRepository(Database()).save_many(records)
        _write_jsonl(args.output, (record.model_dump(mode="json") for record in records))
        print(f"records_written={len(records)} records_persisted={persisted} output={args.output}")
        return 0
    if args.command == "normalize":
        normalizer = MaterialNormalizer()
        output = []
        for record in _read_jsonl(args.input):
            material = MaterialRecord.model_validate(record)
            normalized = normalizer.normalize(material.raw_description)
            attrs = extract_attributes(normalized.normalized_text)
            output.append(
                material.model_copy(
                    update={
                        "normalized_description": normalized.normalized_text,
                        "attributes": attrs.attributes,
                        "metadata": {
                            **material.metadata,
                            "normalization_transformations": normalized.transformations,
                        },
                    }
                ).model_dump(mode="json")
            )
        _write_jsonl(args.output, output)
        persisted = MaterialRepository(Database()).save_many(
            [MaterialRecord.model_validate(item) for item in output]
        )
        print(f"records_written={len(output)} records_persisted={persisted} output={args.output}")
        return 0
    if args.command == "extract-attributes":
        output = []
        for row in _read_jsonl(args.input):
            description = row.get("normalized_description") or row.get("raw_description") or ""
            row["attributes"] = [
                attribute.model_dump(mode="json")
                for attribute in extract_attributes(description).attributes
            ]
            output.append(row)
        _write_jsonl(args.output, output)
        persisted = MaterialRepository(Database()).save_many(
            [MaterialRecord.model_validate(item) for item in output]
        )
        print(f"records_written={len(output)} records_persisted={persisted} output={args.output}")
        return 0
    if args.command == "build-index":
        rows, _ = read_csv_records(args.input)
        records = _records_from_rows(rows, args.input)
        normalizer = MaterialNormalizer()
        records = [
            record.model_copy(
                update={
                    "normalized_description": normalizer.normalize(
                        record.raw_description
                    ).normalized_text,
                }
            )
            for record in records
        ]
        families = [extract_attributes(record.normalized_description).family for record in records]
        engine = HybridSearchEngine(
            records,
            document_ids=[record.id for record in records],
            families=families,
            embedding_service=EmbeddingService(),
        )
        engine.save(args.output)
        print(
            "documents_indexed="
            f"{len(records)} model={engine.embedding_service.model_version} output={args.output}"
        )
        return 0
    if args.command == "generate-weak-labels":
        rows, _ = read_csv_records(args.input)
        records = _records_from_rows(rows, args.input)
        labels = WeakLabelGenerator().generate(records)
        _write_jsonl(args.output, (label.model_dump(mode="json") for label in labels))
        print(f"weak_labels_written={len(labels)} label_source=weak_rule output={args.output}")
        return 0
    if args.command == "mine-hard-negatives":
        labels = [
            row
            for row in _read_jsonl(args.input)
            if row.get("relation") == "NOT_EQUIVALENT" and row.get("label_source") == "weak_rule"
        ]
        _write_jsonl(args.output, labels)
        print(f"hard_negatives_written={len(labels)} label_source=weak_rule output={args.output}")
        return 0
    if args.command == "train":
        path = Path(args.labels)
        if not path.exists():
            raise SystemExit(
                f"Training blocked: reviewed expert gold-label data is missing at {path}. Weak labels are not gold."
            )
        raise SystemExit(
            "Training is disabled until a leakage-aware evaluation dataset and model objective "
            "are configured."
        )
    if args.command == "evaluate":
        return _evaluate(args.input, args.group_field, args.threshold)
    if args.command == "calibrate":
        return _calibrate(args.input, args.method, args.output)
    if args.command == "propose-nmc":
        proposal = NMCGenerator().propose(args.description)
        print(
            json.dumps(
                {
                    "nmc": proposal.nmc,
                    "family": proposal.family,
                    "attribute_signature": proposal.attribute_signature,
                    "canonical_description": proposal.canonical_description,
                    "status": proposal.status,
                    "approval_status": proposal.approval_status,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "review-export":
        from cpse_harmonizer.review.service import ReviewQueue

        tasks = ReviewQueue(Database()).list(limit=1000)
        _write_jsonl(args.output, (task.model_dump(mode="json") for task in tasks))
        print(f"review_tasks_exported={len(tasks)} output={args.output}")
        return 0
    if args.command == "serve-api":
        import uvicorn

        uvicorn.run("cpse_harmonizer.api.main:app", host=args.host, port=args.port)
        return 0
    if args.command == "serve-dashboard":
        from cpse_harmonizer.dashboard.app import app

        app.run(host=args.host, port=args.port)
        return 0
    parser.error("Unknown command.")
    return 2


def _doctor() -> int:
    result = {
        "python": sys.version.split()[0],
        "supported_python": sys.version_info >= (3, 12) and sys.version_info < (3, 13),
        "material_corpus_present": Path(
            "data/processed/extracted_items/material_description_corpus.csv"
        ).is_file(),
        "unspsc_industrial_subset_present": Path(
            "data/reference/unspsc/unspsc_industrial_subset.csv"
        ).is_file(),
        "database_url": "configured"
        if __import__("os").getenv("NUMMF_DATABASE_URL")
        else "sqlite development default",
        "deepseek_enabled": bool(__import__("os").getenv("DEEPSEEK_API_KEY"))
        and __import__("os").getenv("SOVEREIGN_MODE", "true").casefold() != "true",
    }
    print(json.dumps(result, indent=2))
    return 0 if result["supported_python"] else 1


def _records_from_rows(rows: Iterable[dict[str, str]], source_path: str) -> list[MaterialRecord]:
    path = Path(source_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    records = []
    for row in rows:
        description = _first(
            row,
            "description",
            "item_description",
            "item_text",
            "short_description",
            "long_description",
            "specifications",
        )
        quantity_text = _first(row, "quantity")
        quantity = None
        if quantity_text:
            try:
                parsed = float(quantity_text.replace(",", ""))
                quantity = parsed if math.isfinite(parsed) else None
            except ValueError:
                quantity = None
        page_text = _first(row, "source_page", "page")
        page = int(page_text) if page_text.isdigit() and int(page_text) > 0 else None
        known = {
            "description",
            "item_description",
            "item_text",
            "short_description",
            "long_description",
            "specifications",
            "quantity",
            "unit",
            "uom",
            "organization",
            "source_organization",
            "source_system",
            "source_url",
            "document_url",
            "source_section",
            "page",
            "source_page",
            "source_document",
            "section",
            "source_record_id",
            "tender_id",
            "tender_reference",
            "material_code",
            "corpus_id",
            "plant",
        }
        records.append(
            MaterialRecord(
                source_system=_first(row, "source_system") or "unknown",
                source_organization=_first(row, "source_organization", "organization"),
                source_record_id=_first(
                    row,
                    "source_record_id",
                    "tender_id",
                    "tender_reference",
                    "material_code",
                    "corpus_id",
                ),
                source_url=_first(row, "source_url"),
                source_document=_first(row, "source_document", "document_url"),
                source_page=page,
                source_section=_first(row, "source_section", "section"),
                source_hash=digest,
                material_code=_first(row, "material_code", "corpus_id"),
                plant=_first(row, "plant"),
                raw_description=description,
                quantity=quantity,
                unit=_first(row, "unit", "uom"),
                organization=_first(row, "organization"),
                metadata={
                    "ingest_artifact_path": str(path),
                    "ingest_artifact_hash": digest,
                    "original_values": {
                        key: value for key, value in row.items() if key not in known
                    },
                },
            )
        )
    return records


def _first(row: dict[str, Any], *keys: str) -> str:
    return next((str(row[key]).strip() for key in keys if row.get(key) not in (None, "")), "")


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    values = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {source}:{line_number}") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"Expected JSON object at {source}:{line_number}")
                values.append(item)
    return values


def _write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            )


def _read_gold_pairs(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    non_gold = [row for row in rows if row.get("label_source") != "expert_gold"]
    if non_gold:
        raise ValueError(
            "Evaluation/calibration refuses weak_rule or unlabeled examples; label_source must be expert_gold."
        )
    return rows


def _evaluate(path: str, group_field: str, threshold: float) -> int:
    rows = _read_gold_pairs(path)
    if any(group_field not in row or not row[group_field] for row in rows):
        raise ValueError(f"Evaluation requires non-empty group field {group_field!r} on every row.")
    train, test = grouped_holdout_indices([str(row[group_field]) for row in rows])
    if not train or not test:
        raise ValueError("Group holdout split produced an empty partition.")
    selected = [rows[index] for index in test]
    metrics = pair_classification_metrics(
        [int(row["label"]) for row in selected],
        [float(row["score"]) for row in selected],
        threshold=threshold,
        calibrated=all(bool(row.get("calibrated", False)) for row in selected),
    )
    print(
        json.dumps(
            {
                "label_source": "expert_gold",
                "split_strategy": f"group_holdout:{group_field}",
                "training_rows": len(train),
                "test_rows": len(test),
                "metrics": metrics,
            },
            indent=2,
        )
    )
    return 0


def _calibrate(path: str, method: str, output: str) -> int:
    rows = _read_gold_pairs(path)
    if any(not row.get("validation_group") for row in rows):
        raise ValueError("Calibration requires validation_group on every expert-gold row.")
    if len({str(row["validation_group"]) for row in rows}) < 2:
        raise ValueError("Calibration data must span multiple independent validation groups.")
    calibrator = PairCalibrator(method).fit(
        [float(row["score"]) for row in rows],
        [int(row["label"]) for row in rows],
    )
    calibrator.save(output)
    print(
        json.dumps(
            {
                "status": "calibrator_fitted",
                "method": method,
                "examples": len(rows),
                "label_source": "expert_gold",
                "output": output,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
