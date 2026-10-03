"""Evidence-preserving, reference-aware industrial text normalization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from cpse_harmonizer.data_quality.checker import read_csv_records


@dataclass(slots=True)
class NormalizationResult:
    raw_text: str
    normalized_text: str
    transformations: list[str] = field(default_factory=list)


class MaterialNormalizer:
    """Normalize formatting and unambiguous domain vocabulary, retaining raw text."""

    def __init__(self, reference_dir: str | Path = "data/reference") -> None:
        self.reference_dir = Path(reference_dir)
        self.abbreviations = self._load_abbreviations()
        self.units = self._load_units()

    def normalize(self, text: str | None) -> NormalizationResult:
        raw = "" if text is None else str(text)
        transformations: list[str] = []
        normalized = unicodedata.normalize("NFKC", raw)
        if normalized != raw:
            transformations.append("unicode_nfkc")

        normalized = normalized.replace("\u00a0", " ")
        normalized = re.sub(r"[\u2010-\u2015\u2212]", "-", normalized)
        normalized = normalized.replace("×", "x").replace("º", "°")
        normalized = re.sub(r"\s*([,;:])\s*", r"\1 ", normalized)
        compact = re.sub(r"\s+", " ", normalized).strip()
        if compact != normalized:
            transformations.append("whitespace")
        normalized = compact

        normalized, changed = self._replace_abbreviations(normalized)
        if changed:
            transformations.append("reference_abbreviation")

        upper = normalized.upper()
        if upper != normalized:
            transformations.append("case_normalization")
        normalized = upper

        normalized, unit_changed = self._normalize_units(normalized)
        if unit_changed:
            transformations.append("reference_unit")

        canonical = self._normalize_engineering_tokens(normalized)
        if canonical != normalized:
            transformations.append("engineering_tokens")
        normalized = re.sub(r"\s+", " ", canonical).strip()
        return NormalizationResult(raw_text=raw, normalized_text=normalized, transformations=transformations)

    def _load_abbreviations(self) -> list[tuple[str, str, str, str]]:
        path = self.reference_dir / "abbreviations" / "material_abbreviations.csv"
        if not path.is_file():
            return []
        rows, _ = read_csv_records(path)
        values = []
        for row in rows:
            surface = (row.get("surface_form") or "").strip()
            canonical = (row.get("canonical_form") or "").strip()
            if surface and canonical:
                values.append((
                    surface,
                    canonical,
                    (row.get("attribute") or "").strip(),
                    (row.get("note") or "").strip(),
                ))
        return sorted(values, key=lambda item: len(item[0]), reverse=True)

    def _load_units(self) -> dict[str, tuple[str, float]]:
        path = self.reference_dir / "units" / "unit_normalisation.csv"
        if not path.is_file():
            return {}
        rows, _ = read_csv_records(path)
        units: dict[str, tuple[str, float]] = {}
        for row in rows:
            surface, canonical = row.get("surface_form"), row.get("canonical_unit")
            if not surface or not canonical:
                continue
            try:
                factor = float(row.get("factor_to_canonical") or 1)
            except ValueError:
                continue
            units[re.sub(r"\s+", "", surface.casefold())] = (canonical.upper(), factor)
        return units

    def _replace_abbreviations(self, text: str) -> tuple[str, bool]:
        result = text
        changed = False
        for surface, canonical, attribute, note in self.abbreviations:
            if "ambiguous" in note.casefold() and not self._abbreviation_context(
                surface, attribute, result
            ):
                continue
            if surface.casefold() == canonical.casefold():
                continue
            pattern = rf"(?<![A-Za-z0-9]){re.escape(surface)}(?![A-Za-z0-9])"
            result, count = re.subn(pattern, canonical, result, flags=re.IGNORECASE)
            changed |= count > 0
        return result, changed

    @staticmethod
    def _abbreviation_context(surface: str, attribute: str, text: str) -> bool:
        context = text.casefold()
        if surface.casefold() == "cv":
            return "valve" in context or "control" in context
        if surface.casefold() in {"tx", "m/s"}:
            return any(word in context for word in ("pump", "seal", "transformer"))
        if attribute == "end_connection":
            return any(word in context for word in ("flange", "pipe", "fitting", "valve"))
        return False

    def _normalize_units(self, text: str) -> tuple[str, bool]:
        result = text
        changed = False
        for surface, (canonical, factor) in sorted(self.units.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{re.escape(surface)})(?![A-Za-z])"

            def replace(
                match: re.Match[str],
                *,
                canonical: str = canonical,
                factor: float = factor,
            ) -> str:
                value = float(match.group("value")) * factor
                rendered = f"{value:g}"
                return f"{rendered} {canonical}"

            result, count = re.subn(pattern, replace, result, flags=re.IGNORECASE)
            changed = changed or count > 0
        return result, changed

    @staticmethod
    def _normalize_engineering_tokens(text: str) -> str:
        result = re.sub(
            r"\b(\d+(?:\.\d+)?)\s*(?:K\s*V|KV|KILOVOLTS?)\b",
            r"\1 KV",
            text,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"\b(\d+(?:\.\d+)?)\s*(?:K\s*VA|KVA)\b",
            r"\1 KVA",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(r"\bCLASS\s*[-:]?\s*(\d{2,4})\b", r"CLASS \1", result, flags=re.IGNORECASE)
        result = re.sub(r"\bPN\s*[-:]?\s*(\d{1,3})\b", r"PN \1", result, flags=re.IGNORECASE)
        result = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", " X ", result)
        result = re.sub(r"(?<!\w)(\d+(?:\.\d+)?)\s*(MM2|SQ\.?\s*MM)\b", r"\1 MM2", result, flags=re.IGNORECASE)
        return result
