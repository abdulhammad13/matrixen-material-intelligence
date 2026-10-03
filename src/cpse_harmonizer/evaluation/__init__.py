"""Evaluation and calibration utilities; caller must supply reviewed labels."""

from .metrics import pair_classification_metrics, retrieval_metrics

__all__ = ["pair_classification_metrics", "retrieval_metrics"]
