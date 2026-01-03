"""
Prometheus metrics for NPC Memory RAG system
"""

import os
import time
from contextlib import contextmanager
from typing import Callable

# Metrics port for pull mode
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Lazy initialization flag
_initialized = False
_metrics = {}


def _init_metrics():
    """Initialize Prometheus metrics (lazy loading)"""
    global _initialized, _metrics

    if _initialized:
        return True

    try:
        from prometheus_client import Counter, Histogram, Gauge

        _metrics["cache_hits"] = Counter(
            "npc_memory_cache_hits_total",
            "Total cache hits"
        )
        _metrics["cache_misses"] = Counter(
            "npc_memory_cache_misses_total",
            "Total cache misses"
        )
        _metrics["embedding_latency"] = Histogram(
            "npc_memory_embedding_latency_seconds",
            "Embedding generation latency",
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        _metrics["embedding_requests"] = Counter(
            "npc_memory_embedding_requests_total",
            "Total embedding requests",
            ["status"]  # success, error, fallback
        )
        _metrics["worker_messages_pulled"] = Counter(
            "npc_memory_worker_messages_pulled_total",
            "Total messages pulled from Pub/Sub"
        )
        _metrics["worker_messages_processed"] = Counter(
            "npc_memory_worker_messages_processed_total",
            "Total messages processed",
            ["status"]  # success, error
        )
        _metrics["worker_bulk_latency"] = Histogram(
            "npc_memory_worker_bulk_latency_seconds",
            "Bulk indexing latency",
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
        )
        _metrics["worker_batch_size"] = Gauge(
            "npc_memory_worker_last_batch_size",
            "Last processed batch size"
        )

        _initialized = True
        return True

    except ImportError:
        print("[Metrics] prometheus_client not installed, metrics disabled")
        return False


def start_metrics_server(port: int = None):
    """Start Prometheus metrics HTTP server (for pull mode)"""
    if not _init_metrics():
        return False

    try:
        from prometheus_client import start_http_server
        port = port or METRICS_PORT
        start_http_server(port)
        print(f"[Metrics] Server started on port {port}")
        return True
    except Exception as e:
        print(f"[Metrics] Failed to start server: {e}")
        return False


# Metric recording functions (safe to call even if prometheus not installed)

def inc_cache_hit():
    """Increment cache hit counter"""
    if _init_metrics():
        _metrics["cache_hits"].inc()


def inc_cache_miss():
    """Increment cache miss counter"""
    if _init_metrics():
        _metrics["cache_misses"].inc()


def observe_embedding_latency(seconds: float):
    """Record embedding latency"""
    if _init_metrics():
        _metrics["embedding_latency"].observe(seconds)


def inc_embedding_request(status: str = "success"):
    """Increment embedding request counter (status: success/error/fallback)"""
    if _init_metrics():
        _metrics["embedding_requests"].labels(status=status).inc()


def inc_worker_pulled(count: int = 1):
    """Increment worker messages pulled counter"""
    if _init_metrics():
        _metrics["worker_messages_pulled"].inc(count)


def inc_worker_processed(status: str = "success", count: int = 1):
    """Increment worker processed counter (status: success/error)"""
    if _init_metrics():
        _metrics["worker_messages_processed"].labels(status=status).inc(count)


def observe_bulk_latency(seconds: float):
    """Record bulk indexing latency"""
    if _init_metrics():
        _metrics["worker_bulk_latency"].observe(seconds)


def set_batch_size(size: int):
    """Set last batch size gauge"""
    if _init_metrics():
        _metrics["worker_batch_size"].set(size)


@contextmanager
def track_latency(observe_fn: Callable[[float], None]):
    """Context manager to track operation latency"""
    start = time.time()
    try:
        yield
    finally:
        observe_fn(time.time() - start)
