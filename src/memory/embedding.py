"""
Embedding service interface with ModelScope Qwen3 integration
"""

import os
import random
import time
import hashlib
from typing import List, Optional


# Environment variable configs
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "modelscope")
MODELSCOPE_BASE_URL = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1")
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
INDEX_VECTOR_DIMS = int(os.getenv("INDEX_VECTOR_DIMS", "1024"))

# Embedding cache settings
EMBEDDING_CACHE_ENABLED = os.getenv("EMBEDDING_CACHE_ENABLED", "false").lower() == "true"

# Retry settings
EMBEDDING_TIMEOUT = int(os.getenv("EMBEDDING_TIMEOUT", "30"))
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))


class EmbeddingService:
    """
    Embedding service with ModelScope Qwen3 support
    Falls back to stub if API key not configured or provider set to 'stub'
    """

    def __init__(self, model_name: str = None, dimension: int = None):
        self.model_name = model_name or EMBEDDING_MODEL
        self.dimension = dimension or INDEX_VECTOR_DIMS
        self._client = None
        self._use_stub = self._should_use_stub()
        self._cache = {} if EMBEDDING_CACHE_ENABLED else None

        if not self._use_stub:
            self._init_client()

    def _should_use_stub(self) -> bool:
        """Determine if should use stub based on config"""
        if EMBEDDING_PROVIDER == "stub":
            return True
        if not MODELSCOPE_API_KEY:
            print("[EmbeddingService] No MODELSCOPE_API_KEY, falling back to stub")
            return True
        return False

    def _init_client(self):
        """Initialize OpenAI-compatible client for ModelScope"""
        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=MODELSCOPE_API_KEY,
                base_url=MODELSCOPE_BASE_URL
            )
            print(f"[EmbeddingService] Using ModelScope API with model: {self.model_name}")
        except ImportError:
            print("[EmbeddingService] openai package not installed, falling back to stub")
            self._use_stub = True
        except Exception as e:
            print(f"[EmbeddingService] Failed to init client: {e}, falling back to stub")
            self._use_stub = True

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text hash"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def embed(self, text: str) -> List[float]:
        """Embed single text"""
        if self._use_stub:
            return self._stub_embed(text)

        # Check cache
        if self._cache is not None:
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                return self._cache[cache_key]

        # Call API with retry
        vector = self._embed_with_retry([text])[0]

        # Store in cache
        if self._cache is not None:
            self._cache[cache_key] = vector

        return vector

    def batch_embed(self, texts: List[str]) -> List[List[float]]:
        """Batch embed texts for better throughput"""
        if not texts:
            return []

        if self._use_stub:
            return [self._stub_embed(t) for t in texts]

        # Check cache for already embedded texts
        results = [None] * len(texts)
        texts_to_embed = []
        indices_to_embed = []

        if self._cache is not None:
            for i, text in enumerate(texts):
                cache_key = self._get_cache_key(text)
                if cache_key in self._cache:
                    results[i] = self._cache[cache_key]
                else:
                    texts_to_embed.append(text)
                    indices_to_embed.append(i)
        else:
            texts_to_embed = texts
            indices_to_embed = list(range(len(texts)))

        # Embed uncached texts
        if texts_to_embed:
            vectors = self._embed_with_retry(texts_to_embed)
            for idx, vector in zip(indices_to_embed, vectors):
                results[idx] = vector
                # Store in cache
                if self._cache is not None:
                    cache_key = self._get_cache_key(texts[idx])
                    self._cache[cache_key] = vector

        return results

    def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Call embedding API with timeout and retry"""
        from src.metrics import observe_embedding_latency, inc_embedding_request

        last_error = None
        start_time = time.time()

        for attempt in range(EMBEDDING_MAX_RETRIES):
            try:
                response = self._client.embeddings.create(
                    model=self.model_name,
                    input=texts,
                    timeout=EMBEDDING_TIMEOUT
                )
                # Record success metrics
                observe_embedding_latency(time.time() - start_time)
                inc_embedding_request("success")
                return [item.embedding for item in response.data]

            except Exception as e:
                last_error = e
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(f"[EmbeddingService] Retry {attempt + 1}/{EMBEDDING_MAX_RETRIES} after {wait_time}s: {e}")
                    time.sleep(wait_time)

        # All retries failed, fall back to stub
        observe_embedding_latency(time.time() - start_time)
        inc_embedding_request("fallback")
        print(f"[EmbeddingService] All retries failed: {last_error}, using stub")
        return [self._stub_embed(t) for t in texts]

    def _stub_embed(self, text: str) -> List[float]:
        """Stub implementation: deterministic random vector based on text hash"""
        # Use text hash as seed for reproducible results
        seed = int(hashlib.md5(text.encode('utf-8')).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(self.dimension)]
