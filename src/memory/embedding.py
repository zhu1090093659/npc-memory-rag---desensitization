"""
Embedding service interface with ModelScope Qwen3 integration
"""

import os
import json
import random
import time
import hashlib
import threading
from typing import List, Optional


# Environment variable configs
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai_compatible")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://your-embedding-api.com/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding-8b")
# qwen3-embedding-8b outputs 1024 dimensions
INDEX_VECTOR_DIMS = int(os.getenv("INDEX_VECTOR_DIMS", "1024"))

# Backward compatibility aliases
MODELSCOPE_BASE_URL = os.getenv("MODELSCOPE_BASE_URL", EMBEDDING_BASE_URL)
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", EMBEDDING_API_KEY)

# Embedding cache settings
EMBEDDING_CACHE_ENABLED = os.getenv("EMBEDDING_CACHE_ENABLED", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "")
EMBEDDING_CACHE_PREFIX = "emb:v1:"
EMBEDDING_CACHE_TTL = 86400 * 7  # 7 days TTL for embedding vectors

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
        self._redis_client = None
        self._cache = None
        self._cache_lock = threading.Lock()  # Thread safety for cache access

        # Initialize cache: prefer Redis, fallback to memory
        if EMBEDDING_CACHE_ENABLED:
            self._init_redis_cache()
            if self._redis_client is None:
                self._cache = {}  # Fallback to memory cache

        if not self._use_stub:
            self._init_client()

    def _init_redis_cache(self):
        """Initialize Redis cache if available"""
        if not REDIS_URL:
            return
        try:
            import redis
            self._redis_client = redis.from_url(REDIS_URL, decode_responses=False)
            self._redis_client.ping()
            print(f"[EmbeddingService] Redis cache enabled at {REDIS_URL[:30]}...")
        except ImportError:
            print("[EmbeddingService] redis package not installed, using memory cache")
        except Exception as e:
            print(f"[EmbeddingService] Redis unavailable: {e}, using memory cache")

    def _should_use_stub(self) -> bool:
        """Determine if should use stub based on config"""
        if EMBEDDING_PROVIDER == "stub":
            return True
        # Check both new and legacy env var names
        api_key = EMBEDDING_API_KEY or MODELSCOPE_API_KEY
        if not api_key:
            print("[EmbeddingService] No EMBEDDING_API_KEY, falling back to stub")
            return True
        return False

    def _init_client(self):
        """Initialize OpenAI-compatible client"""
        try:
            from openai import OpenAI
            # Use new env vars with fallback to legacy names
            api_key = EMBEDDING_API_KEY or MODELSCOPE_API_KEY
            base_url = EMBEDDING_BASE_URL or MODELSCOPE_BASE_URL
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url
            )
            print(f"[EmbeddingService] Using {base_url} with model: {self.model_name}")
        except ImportError:
            print("[EmbeddingService] openai package not installed, falling back to stub")
            self._use_stub = True
        except Exception as e:
            print(f"[EmbeddingService] Failed to init client: {e}, falling back to stub")
            self._use_stub = True

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text hash"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[List[float]]:
        """Get vector from Redis or memory cache"""
        # Try Redis first
        if self._redis_client:
            try:
                data = self._redis_client.get(f"{EMBEDDING_CACHE_PREFIX}{cache_key}")
                if data:
                    return json.loads(data)
            except Exception as e:
                print(f"[EmbeddingService] Redis get error: {e}")
        # Fallback to memory cache
        elif self._cache is not None:
            with self._cache_lock:
                return self._cache.get(cache_key)
        return None

    def _set_to_cache(self, cache_key: str, vector: List[float]):
        """Set vector to Redis or memory cache"""
        # Try Redis first
        if self._redis_client:
            try:
                self._redis_client.setex(
                    f"{EMBEDDING_CACHE_PREFIX}{cache_key}",
                    EMBEDDING_CACHE_TTL,
                    json.dumps(vector)
                )
            except Exception as e:
                print(f"[EmbeddingService] Redis set error: {e}")
        # Fallback to memory cache
        elif self._cache is not None:
            with self._cache_lock:
                self._cache[cache_key] = vector

    def embed(self, text: str) -> List[float]:
        """Embed single text"""
        if self._use_stub:
            return self._stub_embed(text)

        cache_key = self._get_cache_key(text)

        # Check cache (Redis or memory)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Call API with retry
        vector = self._embed_with_retry([text])[0]

        # Cache the result
        self._set_to_cache(cache_key, vector)

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

        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                results[i] = cached
            else:
                texts_to_embed.append(text)
                indices_to_embed.append(i)

        # Embed uncached texts
        if texts_to_embed:
            vectors = self._embed_with_retry(texts_to_embed)
            for idx, vector in zip(indices_to_embed, vectors):
                results[idx] = vector
                cache_key = self._get_cache_key(texts[idx])
                self._set_to_cache(cache_key, vector)

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
