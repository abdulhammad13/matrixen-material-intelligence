"""Layer 2 normalization: Pint-based unit canonicalization for industrial material data."""

from __future__ import annotations

from pint import UnitRegistry


class PintUnitNormalizer:
    """Normalize industrial units and allow safe conversions between common Indian units."""

    _ALIASES = {
        "kg": "kilogram",
        "kgs": "kilogram",
        "kilogram": "kilogram",
        "kilograms": "kilogram",
        "gm": "gram",
        "g": "gram",
        "gram": "gram",
        "ton": "metric_ton",
        "tonne": "metric_ton",
        "mt": "metric_ton",
        "metric_ton": "metric_ton",
        "l": "liter",
        "litre": "liter",
        "liter": "liter",
        "ltr": "liter",
        "liters": "liter",
        "kl": "kiloliter",
        "kiloliter": "kiloliter",
        "m3": "cubic_meter",
        "m^3": "cubic_meter",
        "cu.m": "cubic_meter",
        "cum": "cubic_meter",
        "mm": "millimeter",
        "cm": "centimeter",
        "m": "meter",
        "meter": "meter",
        "mm2": "square_millimeter",
        "sqmm": "square_millimeter",
        "cm2": "square_centimeter",
        "sqm": "square_meter",
        "m2": "square_meter",
        "kw": "kilowatt",
        "kva": "kilovolt_ampere",
        "mva": "megavolt_ampere",
        "kv": "kilovolt",
        "v": "volt",
        "amp": "ampere",
        "a": "ampere",
    }

    def __init__(self) -> None:
        self.ureg = UnitRegistry()

    def normalize_symbol(self, unit: str | None) -> str:
        if not unit:
            return ""
        key = str(unit).strip().lower().replace(" ", "")
        return self._ALIASES.get(key, key)

    def convert_quantity(self, value: float, from_unit: str | None, to_unit: str | None) -> float:
        source = self.normalize_symbol(from_unit)
        target = self.normalize_symbol(to_unit)
        if not source or not target:
            raise ValueError("Both source and target units are required for conversion.")
        try:
            result = (value * self.ureg.Quantity(1, source)).to(target)
            return float(result.magnitude)
        except Exception as exc:  # pragma: no cover - trait of pint for incompatible units
            raise ValueError(f"Cannot convert '{from_unit}' to '{to_unit}'") from exc

    def is_convertible(self, from_unit: str | None, to_unit: str | None) -> bool:
        source = self.normalize_symbol(from_unit)
        target = self.normalize_symbol(to_unit)
        if not source or not target:
            return False
        try:
            self.ureg.Quantity(1, source).to(target)
            return True
        except Exception:
            return False


def canonicalize_unit(unit: str | None) -> str:
    """Return a canonical unit symbol for a material description."""
    return PintUnitNormalizer().normalize_symbol(unit)


def convert_quantity(value: float, from_unit: str | None, to_unit: str | None) -> float:
    """Convert a numeric quantity between units."""
    return PintUnitNormalizer().convert_quantity(value, from_unit, to_unit)


def is_convertible(from_unit: str | None, to_unit: str | None) -> bool:
    """Check whether units can be converted without requiring custom logic."""
    return PintUnitNormalizer().is_convertible(from_unit, to_unit)
