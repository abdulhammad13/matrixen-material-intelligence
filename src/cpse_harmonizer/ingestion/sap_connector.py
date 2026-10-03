"""Layer 1 ingestion: SAP / ERP connectors for CPSE material datasets.

The connector supports flat CSV ingestion and Excel fallback while preserving
provenance metadata for every record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(slots=True)
class MaterialRecord:
    """A single SAP or file-based material record with provenance."""

    source: str
    material_code: str
    description: str
    plant: str = ""
    uom: str = ""
    quantity: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("metadata") is None:
            data["metadata"] = {}
        return data


class SapConnector:
    """Minimal source connector used to import material rows from CSV or Excel."""

    def __init__(self, base_path: str | Path | None = None) -> None:
        self.base_path = Path(base_path) if base_path is not None else Path.cwd()

    def _read_table(self, path: str | Path) -> list[dict[str, Any]]:
        source = Path(path)
        if not source.exists():
            return []
        if source.suffix.lower() == ".csv":
            df = pd.read_csv(source)
        elif source.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(source)
        else:
            raise ValueError(f"Unsupported source format: {source.suffix}")
        return df.fillna("").to_dict(orient="records")

    def fetch_materials(self, source: str | Path) -> list[MaterialRecord]:
        rows = self._read_table(source)
        materials: list[MaterialRecord] = []
        for row in rows:
            description = str(row.get("description") or row.get("material_description") or row.get("text") or "")
            material_code = str(row.get("material_code") or row.get("code") or row.get("matnr") or "")
            plant = str(row.get("plant") or row.get("plant_code") or "")
            uom = str(row.get("uom") or row.get("unit") or "")
            quantity = str(row.get("quantity") or "")
            metadata = {key: value for key, value in row.items() if key not in {"description", "material_code", "code", "matnr", "plant", "uom", "quantity"}}
            materials.append(
                MaterialRecord(
                    source=str(source),
                    material_code=material_code,
                    description=description,
                    plant=plant,
                    uom=uom,
                    quantity=quantity,
                    metadata=metadata,
                )
            )
        return materials

    def load_directory(self, directory: str | Path) -> list[MaterialRecord]:
        records: list[MaterialRecord] = []
        for path in sorted(Path(directory).glob("*")):
            if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
                records.extend(self.fetch_materials(path))
        return records

    def ingest(self, source: str | Path) -> list[MaterialRecord]:
        """Public API for source ingestion, returning a provenance-tagged material list."""
        if isinstance(source, (str, Path)) and Path(source).is_dir():
            return self.load_directory(source)
        return self.fetch_materials(source)
