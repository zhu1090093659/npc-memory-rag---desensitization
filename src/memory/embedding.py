"""
Embedding service interface
"""

from typing import List
import random


class EmbeddingService:
    """Embedding service with stub implementation"""

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5"):
        self.model_name = model_name
        self.dimension = 1024

    def embed(self, text: str) -> List[float]:
        """Embed single text"""
        # Stub: return random vector (in production use real model)
        return [random.uniform(-1, 1) for _ in range(self.dimension)]

    def batch_embed(self, texts: List[str]) -> List[List[float]]:
        """Batch embed texts for better throughput"""
        return [self.embed(t) for t in texts]
