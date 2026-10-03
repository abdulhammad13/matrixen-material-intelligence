"""Layer 5 master-data: National Material Code generation and registry support."""

from __future__ import annotations

import hashlib
import re


class NMCGenerator:
    """Generate a deterministic National Material Code from a description and metadata."""

    def __init__(self, registry: dict[str, str] | None = None) -> None:
        self.registry = registry or {}

    @staticmethod
    def _family(value: str | None) -> str:
        text = (value or "generic").lower()
        if "transformer" in text:
            return "TRF"
        if "valve" in text:
            return "VAL"
        if "pipe" in text:
            return "PIP"
        if "pump" in text:
            return "PMP"
        if "cable" in text:
            return "CAB"
        if "tank" in text:
            return "TNK"
        return "GEN"

    @staticmethod
    def _key_attr(value: str | None) -> str:
        text = (value or "").upper()
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:KV|KVA|MW|HP|MM|M)", text)
        if match:
            return match.group(0).replace(" ", "").replace(".", "D")
        slug = re.sub(r"[^A-Z0-9]", "", text)[:6]
        return slug or "GEN"

    @staticmethod
    def _sector_from_cpse(cpse: str | None) -> str:
        key = (cpse or "NAT").upper()
        if "NTPC" in key:
            return "NTPC"
        if "IOCL" in key:
            return "IOCL"
        if "OIL" in key:
            return "OIL"
        return "NAT"

    def generate(self, description: str, cpse: str | None = None, plant: str | None = None) -> str:
        text = str(description or "").strip()
        if not text:
            raise ValueError("Material description is required for NMC generation.")
        family = self._family(text)
        key_attr = self._key_attr(text)
        sector = self._sector_from_cpse(cpse)
        digest = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:4].upper()
        nmc = f"NMC-{sector}-{family}-{key_attr}-{digest}"
        self.registry[nmc] = text
        return nmc

    def assign(self, description: str, cpse: str | None = None, plant: str | None = None) -> str:
        return self.generate(description=description, cpse=cpse, plant=plant)


def generate_nmc(description: str, cpse: str | None = None, plant: str | None = None) -> str:
    return NMCGenerator().generate(description, cpse=cpse, plant=plant)
