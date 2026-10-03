"""Generate source, file, and explicit-lineage manifests without mutating raw data."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cpse_harmonizer.data_quality.checker import DataQualityChecker
from cpse_harmonizer.domain.models import stable_id

_SOURCE_INFO = {
    "ntpc": ("NTPC", "https://ntpctender.ntpc.co.in"),
    "iocl": ("IOCL", "https://iocletenders.nic.in"),
    "oil_india": ("Oil India Limited", "https://www.oil-india.com"),
    "cppp": ("Central Public Procurement Portal", "https://eprocure.gov.in"),
    "unspsc": ("UNSPSC reference", ""),
}


def generate_manifests(
    data_root: str | Path = "data",
    *,
    corpus_path: str | Path = "data/processed/extracted_items/material_description_corpus.csv",
) -> dict[str, Any]:
    root = Path(data_root)
    manifests = root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "manifests" not in path.relative_to(root).parts
        and path.name != "nummf.db"
    )
    timestamp = datetime.now(UTC).isoformat()
    file_rows: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []

    for path in files:
        relative = path.relative_to(root).as_posix()
        if _is_lfs_pointer(path):
            file_rows.append(
                {
                    "path": relative,
                    "source_id": _source_id(relative),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                    "encoding": "",
                    "csv_rows": "",
                    "status": "unresolved_pointer",
                    "content_type": "git-lfs-pointer",
                    "retrieved_at": timestamp,
                }
            )
            continue
        source_id = _source_id(relative)
        source_name, base_url = _source_info(relative)
        sources.setdefault(
            source_id,
            {
                "source_id": source_id,
                "name": source_name,
                "base_url": base_url,
                "collector_type": "repository-artifact",
                "terms_url": "",
                "license_note": "Original source redistribution terms have not been verified.",
                "usage_status": "reference-only-unverified",
            },
        )
        encoding = ""
        row_count: int | str = ""
        status = "available"
        if path.suffix.casefold() == ".csv":
            try:
                encoding, row_count = _csv_profile(path)
            except UnicodeDecodeError:
                status = "decode_error"
            except csv.Error:
                status = "malformed_csv"
        content_type = _content_type(path)
        file_rows.append(
            {
                "path": relative,
                "source_id": source_id,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "encoding": encoding,
                "csv_rows": row_count,
                "status": status,
                "content_type": content_type,
                "retrieved_at": timestamp,
            }
        )
        if relative.startswith("raw/"):
            transform = "immutable source artifact"
            lineage_status = "source"
        elif relative.startswith(("processed/", "interim/", "gold/")):
            transform = "legacy-derived artifact; exact inputs/version not recorded"
            lineage_status = "unresolved_legacy_lineage"
        else:
            transform = "reference artifact; no derivation asserted"
            lineage_status = "reference"
        lineage.append(
            {
                "artifact_path": relative,
                "source_id": source_id,
                "source_artifact_hash": _sha256(path),
                "transformation": transform,
                "transformation_version": "unknown"
                if lineage_status == "unresolved_legacy_lineage"
                else "1",
                "lineage_status": lineage_status,
                "created_at": timestamp,
            }
        )

    _write_csv(
        manifests / "sources.csv",
        list(sources.values()),
        [
            "source_id",
            "name",
            "base_url",
            "collector_type",
            "terms_url",
            "license_note",
            "usage_status",
        ],
    )
    _write_csv(
        manifests / "files.csv",
        file_rows,
        [
            "path",
            "source_id",
            "bytes",
            "sha256",
            "encoding",
            "csv_rows",
            "status",
            "content_type",
            "retrieved_at",
        ],
    )
    _write_csv(
        manifests / "lineage.csv",
        lineage,
        [
            "artifact_path",
            "source_id",
            "source_artifact_hash",
            "transformation",
            "transformation_version",
            "lineage_status",
            "created_at",
        ],
    )

    quality = None
    if Path(corpus_path).is_file():
        report, clean, quarantine = DataQualityChecker().profile_csv(corpus_path)
        quality = report.as_dict()
        (manifests / "quality_report.json").write_text(
            json.dumps(quality, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        from cpse_harmonizer.data_quality.checker import write_quality_outputs

        write_quality_outputs(report, clean, quarantine, root / "interim" / "data_quality")
    return {
        "sources": len(sources),
        "files": len(file_rows),
        "lineage_rows": len(lineage),
        "quality_report": quality,
        "output_directory": str(manifests),
    }


def _source_id(relative: str) -> str:
    parts = relative.split("/")
    if len(parts) > 1 and parts[0] == "raw":
        key = parts[1].casefold()
    elif len(parts) > 1 and parts[0] == "reference":
        key = parts[1].casefold()
    else:
        key = parts[0].casefold() if parts else "unknown"
    return stable_id("source", key)


def _source_info(relative: str) -> tuple[str, str]:
    parts = relative.split("/")
    if len(parts) > 1 and parts[0] in {"raw", "reference"}:
        key = parts[1].casefold()
        return _SOURCE_INFO.get(key, (f"Unverified source: {key}", ""))
    return "Repository-derived artifact", ""


def _is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(128).startswith(b"version https://git-lfs.github.com/spec/v1")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_type(path: Path) -> str:
    if path.suffix.casefold() == ".pdf":
        with path.open("rb") as handle:
            return "application/pdf" if handle.read(5) == b"%PDF-" else "invalid-pdf-magic"
    return {
        ".csv": "text/csv",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".txt": "text/plain",
        ".html": "text/html",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(path.suffix.casefold(), "application/octet-stream")


def _csv_profile(path: Path) -> tuple[str, int]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                row_count = max(sum(1 for _ in csv.reader(handle)) - 1, 0)
            return encoding, row_count
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, "unsupported encoding")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
