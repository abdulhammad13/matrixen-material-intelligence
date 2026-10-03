"""Layer 3 extraction: semantic embeddings and text feature generation."""

from .deepseek_extractor import DeepSeekMaterialExtractor, MaterialLine
from .embedding_service import EmbeddingService

__all__ = ["EmbeddingService", "DeepSeekMaterialExtractor", "MaterialLine"]
