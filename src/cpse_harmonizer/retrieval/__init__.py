"""Layer 4 retrieval: hybrid sparse/dense matching entry points."""

from .hybrid_search import HybridSearchEngine, rrf_fusion

__all__ = ["HybridSearchEngine", "rrf_fusion"]
