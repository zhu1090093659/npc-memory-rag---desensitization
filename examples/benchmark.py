"""
Performance Benchmark Script for NPC Memory RAG System

Tests:
1. Embedding latency (single & batch)
2. ES search latency (BM25 & Vector)
3. Hybrid search end-to-end latency
4. Concurrent search throughput
5. Write throughput

Usage:
    python examples/benchmark.py
"""

import sys
import os
import time
import statistics
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

# =============================================================================
# Cloud Configuration
# =============================================================================
os.environ.setdefault("ES_URL", "https://my-elasticsearch-project-aa20b7.es.asia-southeast1.gcp.elastic.cloud:443")
os.environ.setdefault("ES_API_KEY", "WjMzYWRKc0I0bzBHYktSaWl0LWk6dlY3N25kZ05jYzBZbURjVFV4NF9kZw==")
# Embedding API Configuration
os.environ.setdefault("EMBEDDING_API_KEY", "sk-OI98X2iylUhYtncA518f4c7dEa0746A290D590B90c941d01")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.bltcy.ai/v1")
os.environ.setdefault("EMBEDDING_MODEL", "qwen3-embedding-8b")
os.environ.setdefault("INDEX_VECTOR_DIMS", "1024")
os.environ.setdefault("EMBEDDING_CACHE_ENABLED", "true")  # Enable cache for realistic performance

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.es_client import create_es_client
from src.memory import EmbeddingService, MemorySearcher


@dataclass
class BenchmarkResult:
    """Single benchmark result"""
    name: str
    samples: int
    min_ms: float
    max_ms: float
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput: float = 0.0  # requests per second
    errors: int = 0


@dataclass
class BenchmarkReport:
    """Complete benchmark report"""
    timestamp: str
    environment: Dict[str, str]
    results: List[BenchmarkResult] = field(default_factory=list)
    bottlenecks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


def calculate_percentile(data: List[float], percentile: float) -> float:
    """Calculate percentile value"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    index = int(len(sorted_data) * percentile / 100)
    return sorted_data[min(index, len(sorted_data) - 1)]


def benchmark_function(func, iterations: int = 10, warmup: int = 2) -> BenchmarkResult:
    """Run benchmark on a function"""
    # Warmup
    for _ in range(warmup):
        try:
            func()
        except Exception:
            pass

    # Actual benchmark
    latencies = []
    errors = 0
    start_total = time.time()

    for _ in range(iterations):
        start = time.time()
        try:
            func()
            latencies.append((time.time() - start) * 1000)  # Convert to ms
        except Exception as e:
            errors += 1
            print(f"  Error: {e}")

    total_time = time.time() - start_total

    if not latencies:
        return BenchmarkResult(
            name="unknown",
            samples=iterations,
            min_ms=0, max_ms=0, avg_ms=0,
            p50_ms=0, p95_ms=0, p99_ms=0,
            throughput=0, errors=errors
        )

    return BenchmarkResult(
        name="unknown",
        samples=len(latencies),
        min_ms=min(latencies),
        max_ms=max(latencies),
        avg_ms=statistics.mean(latencies),
        p50_ms=calculate_percentile(latencies, 50),
        p95_ms=calculate_percentile(latencies, 95),
        p99_ms=calculate_percentile(latencies, 99),
        throughput=len(latencies) / total_time if total_time > 0 else 0,
        errors=errors
    )


def benchmark_concurrent(func, concurrency: int, total_requests: int) -> BenchmarkResult:
    """Run concurrent benchmark"""
    latencies = []
    errors = 0
    start_total = time.time()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(func) for _ in range(total_requests)]

        for future in as_completed(futures):
            try:
                latency = future.result()
                if latency is not None:
                    latencies.append(latency)
            except Exception as e:
                errors += 1
                print(f"  Concurrent error: {e}")

    total_time = time.time() - start_total

    if not latencies:
        return BenchmarkResult(
            name="unknown",
            samples=total_requests,
            min_ms=0, max_ms=0, avg_ms=0,
            p50_ms=0, p95_ms=0, p99_ms=0,
            throughput=0, errors=errors
        )

    return BenchmarkResult(
        name="unknown",
        samples=len(latencies),
        min_ms=min(latencies),
        max_ms=max(latencies),
        avg_ms=statistics.mean(latencies),
        p50_ms=calculate_percentile(latencies, 50),
        p95_ms=calculate_percentile(latencies, 95),
        p99_ms=calculate_percentile(latencies, 99),
        throughput=len(latencies) / total_time if total_time > 0 else 0,
        errors=errors
    )


def run_benchmarks():
    """Run all benchmarks - focused on hybrid search with cache comparison"""
    print("=" * 70)
    print("NPC Memory RAG Performance Benchmark")
    print("=" * 70)
    print(f"Start time: {datetime.now().isoformat()}")
    print()

    report = BenchmarkReport(
        timestamp=datetime.now().isoformat(),
        environment={
            "ES_URL": os.getenv("ES_URL", "")[:50] + "...",
            "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "qwen3-embedding-8b"),
            "EMBEDDING_CACHE_ENABLED": os.getenv("EMBEDDING_CACHE_ENABLED", "true"),
        }
    )

    # ==========================================================================
    # 1. ES Connection Test
    # ==========================================================================
    print("[1] Testing ES Connection...")
    try:
        es_client = create_es_client()
        info = es_client.info()
        print(f"    Connected to ES cluster: {info['cluster_name']}")
        print(f"    Version: {info['version']['number']}")
    except Exception as e:
        print(f"    ES connection failed: {e}")
        return report

    # ==========================================================================
    # 2. Embedding Service Verification
    # ==========================================================================
    print("\n[2] Verifying Embedding Service...")
    embedder = EmbeddingService()

    if embedder._use_stub:
        print("    Mode: STUB (no real API calls)")
    else:
        print(f"    Model: {embedder.model_name}")
    print(f"    Dimension: {embedder.dimension}")
    print(f"    Cache: {'ENABLED' if embedder._cache is not None else 'DISABLED'}")

    # Quick verification
    test_vec = embedder.embed("test")
    print(f"    Verification: OK (vector length={len(test_vec)})")

    # ==========================================================================
    # 3. Hybrid Search Performance Test (Core)
    # ==========================================================================
    print("\n[3] Benchmarking Hybrid Search...")

    searcher = MemorySearcher(es_client, embedder)
    player_id = "player_1"
    npc_id = "npc_blacksmith"

    # Test queries with different characteristics
    test_queries = [
        ("剑", "CN_short"),
        ("sword", "EN_short"),
        ("玩家帮助铁匠找回了失落的锤子", "CN_long"),
        ("The blacksmith offered me a sword for the quest", "EN_long"),
    ]

    cold_results = []
    cache_results = []

    # [3.1] Cold Start Test (clear cache first)
    print("\n    [3.1] Cold Start (No Cache):")
    print("    " + "-" * 50)
    print(f"    {'Query Type':<15} {'Avg (ms)':<12} {'P95 (ms)':<12}")
    print("    " + "-" * 50)

    # Clear embedding cache for cold start test
    if hasattr(embedder, '_cache') and embedder._cache is not None:
        with embedder._cache_lock:
            embedder._cache.clear()

    for query, desc in test_queries:
        def hybrid_search(q=query):
            return searcher.search_memories(player_id, npc_id, q, top_k=5)

        # Only 1 iteration for cold start (first call)
        result = benchmark_function(hybrid_search, iterations=1, warmup=0)
        result.name = f"cold_{desc}"
        cold_results.append(result)
        print(f"    {desc:<15} {result.avg_ms:<12.0f} {result.p95_ms:<12.0f}")
        report.results.append(result)

    # [3.2] Cache Hit Test (use same queries again)
    print("\n    [3.2] Cache Hit Performance:")
    print("    " + "-" * 50)
    print(f"    {'Query Type':<15} {'Avg (ms)':<12} {'P95 (ms)':<12}")
    print("    " + "-" * 50)

    for query, desc in test_queries:
        def hybrid_search(q=query):
            return searcher.search_memories(player_id, npc_id, q, top_k=5)

        # Multiple iterations with same query (should hit cache)
        result = benchmark_function(hybrid_search, iterations=5, warmup=1)
        result.name = f"cached_{desc}"
        cache_results.append(result)
        print(f"    {desc:<15} {result.avg_ms:<12.0f} {result.p95_ms:<12.0f}")
        report.results.append(result)

    # [3.3] Cache Effect Summary
    print("\n    [3.3] Cache Effect Summary:")
    print("    " + "-" * 50)

    avg_cold = statistics.mean([r.avg_ms for r in cold_results]) if cold_results else 0
    avg_cached = statistics.mean([r.avg_ms for r in cache_results]) if cache_results else 0
    improvement = avg_cold / avg_cached if avg_cached > 0 else 0

    print(f"    Cold Start Avg:  {avg_cold:.0f}ms")
    print(f"    Cache Hit Avg:   {avg_cached:.0f}ms")
    print(f"    Improvement:     {improvement:.1f}x faster with cache")

    # ==========================================================================
    # 4. Concurrent Search Throughput Test
    # ==========================================================================
    print("\n[4] Benchmarking Concurrent Throughput...")

    def timed_search():
        start = time.time()
        searcher.search_memories(player_id, npc_id, "sword", top_k=5)
        return (time.time() - start) * 1000

    print("    " + "-" * 50)
    print(f"    {'Concurrency':<12} {'Throughput':<15} {'Avg (ms)':<12} {'Errors':<10}")
    print("    " + "-" * 50)

    for concurrency in [2, 4, 8]:
        total_requests = concurrency * 3
        result = benchmark_concurrent(timed_search, concurrency, total_requests)
        result.name = f"concurrent_{concurrency}"
        print(f"    {concurrency:<12} {result.throughput:<15.2f} {result.avg_ms:<12.0f} {result.errors:<10}")
        report.results.append(result)

    # ==========================================================================
    # 5. Analysis and Recommendations
    # ==========================================================================
    print("\n[5] Analysis and Recommendations...")

    # Cache effectiveness
    if improvement > 3:
        report.recommendations.append(f"Cache is highly effective ({improvement:.1f}x improvement)")
    elif improvement > 1.5:
        report.recommendations.append(f"Cache provides moderate benefit ({improvement:.1f}x improvement)")
    else:
        report.bottlenecks.append("Cache benefit is minimal - check cache configuration")

    # Latency analysis
    if avg_cached > 300:
        report.bottlenecks.append(f"Cached search latency is high ({avg_cached:.0f}ms) - ES network latency")
        report.recommendations.append("Deploy to same region as Elasticsearch")

    if avg_cold > 1500:
        report.bottlenecks.append(f"Cold start latency is high ({avg_cold:.0f}ms)")
        report.recommendations.append("Consider Redis for persistent embedding cache")

    # Concurrent scaling
    concurrent_results = [r for r in report.results if "concurrent" in r.name]
    if concurrent_results:
        throughputs = [(int(r.name.split("_")[-1]), r.throughput) for r in concurrent_results]
        throughputs.sort()

        if len(throughputs) >= 2:
            c1, t1 = throughputs[0]
            c2, t2 = throughputs[-1]
            scaling_factor = (t2 / t1) / (c2 / c1) if t1 > 0 and c1 > 0 else 0

            if scaling_factor < 0.5:
                report.bottlenecks.append(f"Poor concurrency scaling ({scaling_factor:.0%})")
            else:
                report.recommendations.append(f"Good concurrency scaling ({scaling_factor:.0%})")

    # ==========================================================================
    # 6. Summary
    # ==========================================================================
    print("\n" + "=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)

    print("\nHybrid Search Performance:")
    print("-" * 70)
    print(f"{'Scenario':<40} {'Avg (ms)':<12} {'P95 (ms)':<12}")
    print("-" * 70)

    for r in report.results:
        if "cold" in r.name or "cached" in r.name:
            print(f"{r.name:<40} {r.avg_ms:<12.0f} {r.p95_ms:<12.0f}")

    print("\nConcurrent Throughput:")
    print("-" * 70)
    for r in report.results:
        if "concurrent" in r.name:
            print(f"{r.name:<40} {r.throughput:.2f} req/s")

    if report.bottlenecks:
        print("\nBottlenecks:")
        for i, b in enumerate(report.bottlenecks, 1):
            print(f"  {i}. {b}")

    if report.recommendations:
        print("\nRecommendations:")
        for i, r in enumerate(report.recommendations, 1):
            print(f"  {i}. {r}")

    # Estimate capacity
    max_throughput = max([r.throughput for r in concurrent_results]) if concurrent_results else 0
    print(f"\nEstimated Single Instance Capacity:")
    print(f"  - Max observed throughput: {max_throughput:.1f} req/s")
    print(f"  - Recommended safe QPS: {max_throughput * 0.7:.1f} req/s")

    return report


def save_report(report: BenchmarkReport, filepath: str):
    """Save benchmark report to JSON"""
    data = {
        "timestamp": report.timestamp,
        "environment": report.environment,
        "results": [asdict(r) for r in report.results],
        "bottlenecks": report.bottlenecks,
        "recommendations": report.recommendations,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to: {filepath}")


if __name__ == "__main__":
    report = run_benchmarks()

    # Save report
    report_path = os.path.join(os.path.dirname(__file__), "benchmark_report.json")
    save_report(report, report_path)

    print("\n" + "=" * 70)
    print("Benchmark completed!")
    print("=" * 70)
