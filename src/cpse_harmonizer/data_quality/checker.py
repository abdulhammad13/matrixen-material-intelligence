"""Row-level data-quality checks that report findings without dropping evidence."""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cpse_harmonizer.domain.models import stable_id

_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_ADMIN_TERMS = re.compile(
    r"\b(?:tender|bid submission|earnest money|emd|corrigendum|pre[- ]bid meeting|"
    r"contractor registration|vendor enlistment)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QualityIssue:
    row_id: str
    severity: str
    check: str
    field: str
    message: str


@dataclass(slots=True)
class DataQualityReport:
    source_path: str
    encoding: str
    records_seen: int = 0
    records_valid: int = 0
    records_quarantined: int = 0
    records_changed: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    warning_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    info_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "encoding": self.encoding,
            "records_seen": self.records_seen,
            "records_valid": self.records_valid,
            "records_quarantined": self.records_quarantined,
            "records_changed": self.records_changed,
            "warning_counts": self.warning_counts,
            "error_counts": self.error_counts,
            "info_counts": self.info_counts,
            "issues": [
                issue.__dict__
                if hasattr(issue, "__dict__")
                else {
                    "row_id": issue.row_id,
                    "severity": issue.severity,
                    "check": issue.check,
                    "field": issue.field,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


def read_csv_records(path: str | Path) -> tuple[list[dict[str, str]], str]:
    """Read a CSV only after ruling out an unresolved Git LFS pointer."""
    source = Path(path)
    with source.open("rb") as raw:
        prefix = raw.read(512)
    if prefix.startswith(_LFS_PREFIX):
        raise ValueError(f"Unresolved Git LFS pointer; refusing to parse as CSV: {source}")
    errors: list[UnicodeDecodeError] = []
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with source.open("r", encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle)), encoding
        except UnicodeDecodeError as exc:
            errors.append(exc)
    raise UnicodeError(f"Unable to decode CSV {source} as UTF-8 or CP1252: {errors[-1]}")


class DataQualityChecker:
    """Profile source rows and retain every row with a stable ID and issue list."""

    def __init__(self) -> None:
        self._known_units: set[str] | None = None

    def check_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        source_path: str = "",
        encoding: str = "unknown",
    ) -> tuple[DataQualityReport, list[dict[str, Any]], list[dict[str, Any]]]:
        rows = [dict(row) for row in records]
        report = DataQualityReport(
            source_path=source_path, encoding=encoding, records_seen=len(rows)
        )
        issue_lists: list[list[QualityIssue]] = [[] for _ in rows]
        descs: dict[str, list[int]] = defaultdict(list)
        by_desc: dict[str, set[str]] = defaultdict(set)
        by_tender_title: dict[tuple[str, str], list[int]] = defaultdict(list)

        for index, row in enumerate(rows):
            description = self._first(
                row, "description", "item_description", "item_text", "short_description"
            )
            organization = self._first(row, "organization", "source_organization", "cpse")
            identity = str(
                row.get("corpus_id")
                or row.get("id")
                or stable_id("row", source_path, str(index), description)
            )
            row["_quality_id"] = identity
            folded = " ".join(description.casefold().split())
            if folded:
                descs[folded].append(index)
                by_desc[folded].add(organization.casefold())
            tender_id = self._first(row, "tender_id", "tender_reference")
            if tender_id and str(row.get("description_kind") or "").casefold() in {
                "tender_title",
                "nit_brief_description",
            }:
                by_tender_title[(tender_id.casefold(), folded)].append(index)

            if not description:
                self._add(
                    issue_lists[index],
                    identity,
                    "ERROR",
                    "empty_description",
                    "description",
                    "No material description is present.",
                )
            elif re.fullmatch(r"[\W\d.,/+_-]+", description, flags=re.UNICODE):
                self._add(
                    issue_lists[index],
                    identity,
                    "ERROR",
                    "numeric_only_description",
                    "description",
                    "Description contains no alphabetic material evidence.",
                )
            if description and _ADMIN_TERMS.search(description):
                self._add(
                    issue_lists[index],
                    identity,
                    "WARNING",
                    "administrative_text",
                    "description",
                    "Text may describe a tender or administrative process rather than a material.",
                )
            if not any(
                (row.get(key) or "").strip()
                for key in ("source_url", "document_url", "source_document")
            ):
                self._add(
                    issue_lists[index],
                    identity,
                    "WARNING",
                    "missing_provenance_url",
                    "source_url",
                    "No source URL or document reference is recorded.",
                )
            if not any(
                (row.get(key) or "").strip() for key in ("source_system", "source", "source_table")
            ):
                self._add(
                    issue_lists[index],
                    identity,
                    "WARNING",
                    "missing_source_system",
                    "source_system",
                    "No source system/table is recorded.",
                )
            quantity = self._first(row, "quantity")
            if quantity:
                try:
                    numeric = float(quantity.replace(",", ""))
                    if not math.isfinite(numeric) or numeric < 0:
                        raise ValueError
                except ValueError:
                    self._add(
                        issue_lists[index],
                        identity,
                        "ERROR",
                        "invalid_quantity",
                        "quantity",
                        "Quantity is not a finite, non-negative number.",
                    )
            if len(description) > 1200:
                self._add(
                    issue_lists[index],
                    identity,
                    "WARNING",
                    "malformed_specification",
                    "description",
                    "Description exceeds 1,200 characters; inspect for concatenated document text.",
                )
            unit = self._first(row, "unit", "uom")
            if unit and not self._known_unit(unit):
                self._add(
                    issue_lists[index],
                    identity,
                    "WARNING",
                    "invalid_unit",
                    "unit",
                    f"Unit {unit!r} is not in the repository unit reference table.",
                )
            taxonomy_code = self._first(row, "unspsc_code", "taxonomy_code")
            if taxonomy_code and not re.fullmatch(r"\d{8}", taxonomy_code):
                self._add(
                    issue_lists[index],
                    identity,
                    "WARNING",
                    "invalid_taxonomy_code",
                    "taxonomy_code",
                    "UNSPSC taxonomy codes should contain exactly eight digits.",
                )

        for normalized, indices in descs.items():
            if len(indices) > 1:
                for index in indices:
                    identity = rows[index]["_quality_id"]
                    code = (
                        "cross_organization_duplicate"
                        if len(by_desc[normalized]) > 1
                        else "duplicate_description"
                    )
                    message = (
                        "Exact normalized description occurs across organizations."
                        if code.startswith("cross_")
                        else "Exact normalized description occurs more than once."
                    )
                    self._add(issue_lists[index], identity, "INFO", code, "description", message)
        for indices in by_tender_title.values():
            if len(indices) > 1:
                for index in indices:
                    self._add(
                        issue_lists[index],
                        rows[index]["_quality_id"],
                        "WARNING",
                        "repeated_tender_title",
                        "description",
                        f"Same tender title/brief appears {len(indices)} times for one tender reference.",
                    )

        clean: list[dict[str, Any]] = []
        quarantine: list[dict[str, Any]] = []
        warning_counts: Counter[str] = Counter()
        error_counts: Counter[str] = Counter()
        info_counts: Counter[str] = Counter()
        for row, issues in zip(rows, issue_lists, strict=True):
            report.issues.extend(issues)
            for issue in issues:
                if issue.severity == "ERROR":
                    error_counts[issue.check] += 1
                elif issue.severity == "WARNING":
                    warning_counts[issue.check] += 1
                else:
                    info_counts[issue.check] += 1
            if any(issue.severity == "ERROR" for issue in issues):
                row["_quality_status"] = "quarantined"
                quarantine.append(row)
            else:
                row["_quality_status"] = "clean_with_warnings" if issues else "clean"
                clean.append(row)
        report.records_quarantined = len(quarantine)
        report.records_valid = len(clean)
        report.warning_counts = dict(sorted(warning_counts.items()))
        report.error_counts = dict(sorted(error_counts.items()))
        report.info_counts = dict(sorted(info_counts.items()))
        return report, clean, quarantine

    def profile_csv(
        self, path: str | Path
    ) -> tuple[DataQualityReport, list[dict[str, Any]], list[dict[str, Any]]]:
        source = Path(path)
        records, encoding = read_csv_records(source)
        return self.check_records(records, source_path=str(source), encoding=encoding)

    @staticmethod
    def _first(row: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _add(
        target: list[QualityIssue], row_id: str, severity: str, check: str, field: str, message: str
    ) -> None:
        target.append(QualityIssue(row_id, severity, check, field, message))

    def _known_unit(self, unit: str) -> bool:
        if self._known_units is None:
            path = Path("data/reference/units/unit_normalisation.csv")
            records, _ = read_csv_records(path) if path.is_file() else ([], "unknown")
            self._known_units = {
                (row.get("surface_form") or "").strip().casefold()
                for row in records
                if row.get("surface_form")
            }
        return not self._known_units or unit.strip().casefold() in self._known_units


def write_quality_outputs(
    report: DataQualityReport,
    clean: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
    output_dir: str | Path,
) -> None:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "quality_report.json").write_text(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        target / "row_issues.csv",
        [
            {
                "row_id": issue.row_id,
                "severity": issue.severity,
                "check": issue.check,
                "field": issue.field,
                "message": issue.message,
            }
            for issue in report.issues
        ],
    )
    if clean or quarantine:
        columns = list(dict.fromkeys(key for row in clean + quarantine for key in row))
        _write_csv(target / "clean.csv", clean, columns)
        _write_csv(target / "quarantine.csv", quarantine, columns)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if columns is None:
        columns = list(rows[0]) if rows else ["row_id", "severity", "check", "field", "message"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
