"""Layer 2 normalization: units and material attribute unification."""

from .attribute_extractor import AttributeExtractor, MaterialAttributes, extract_attributes
from .service import NormalizationService
from .uom_pint import PintUnitNormalizer, canonicalize_unit, convert_quantity, is_convertible

__all__ = [
    "AttributeExtractor",
    "MaterialAttributes",
    "PintUnitNormalizer",
    "NormalizationService",
    "canonicalize_unit",
    "convert_quantity",
    "extract_attributes",
    "is_convertible",
]
