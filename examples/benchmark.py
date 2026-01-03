"""
Performance Benchmark Script for NPC Memory RAG System

End-to-end tests against Cloud Run API Service:
1. Health/ready check latency
2. Write latency (POST /memories, request-reply via Pub/Sub + Worker + Redis)
3. Search latency (GET /search, request-reply via Pub/Sub + Worker + Redis)
4. Concurrent search throughput

Usage:
    python examples/benchmark.py
"""

import os
import time
import statistics
import json
import ssl
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
from urllib import request as urllib_request
from urllib import parse as urllib_parse
from urllib import error as urllib_error

ENV_BENCH_API_BASE_URL = "BENCH_API_BASE_URL"  # required
ENV_TIMEOUT_SECONDS = "BENCH_TIMEOUT_SECONDS"
ENV_PLAYER_ID = "BENCH_PLAYER_ID"
ENV_NPC_ID = "BENCH_NPC_ID"
ENV_SEED_COUNT = "BENCH_SEED_COUNT"
ENV_SEED_ENABLED = "BENCH_SEED_ENABLED"
ENV_SEARCH_ITERATIONS = "BENCH_SEARCH_ITERATIONS"
ENV_WRITE_ITERATIONS = "BENCH_WRITE_ITERATIONS"
ENV_WARMUP = "BENCH_WARMUP"
ENV_CONCURRENCY_LIST = "BENCH_CONCURRENCY_LIST"
ENV_TOTAL_REQUESTS = "BENCH_TOTAL_REQUESTS"  # total requests per concurrency level
ENV_VERBOSE_ERRORS = "BENCH_VERBOSE_ERRORS"
ENV_HTTP_MAX_RETRIES = "BENCH_HTTP_MAX_RETRIES"


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


def _get_env_required(name: str) -> str:
    """Get required env var, raise if missing/empty."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        raise RuntimeError(f"{name} is required")
    return raw


def _get_env_int(name: str) -> int:
    """Parse required int env var."""
    raw = _get_env_required(name)
    try:
        return int(raw)
    except Exception as e:
        raise RuntimeError(f"{name} must be int, got {raw!r}") from e


def _get_env_bool(name: str) -> bool:
    """Parse required bool env var."""
    raw = _get_env_required(name).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    raise RuntimeError(f"{name} must be bool, got {raw!r}")


def _parse_int_list(raw: str) -> List[int]:
    """Parse comma-separated int list (required)"""
    if not raw:
        raise RuntimeError(f"{ENV_CONCURRENCY_LIST} is required")
    items: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            items.append(int(part))
        except Exception:
            continue
    if not items:
        raise RuntimeError(f"{ENV_CONCURRENCY_LIST} is invalid: {raw!r}")
    return items


def _http_json(
    method: str,
    url: str,
    payload: Optional[dict],
    timeout_seconds: int,
) -> Tuple[int, Optional[dict], float, Optional[str]]:
    """
    Perform an HTTP request and parse JSON response.
    Returns (status_code, json_or_none, latency_ms, error_message_or_none).
    """
    data: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib_request.Request(url=url, data=data, method=method, headers=headers)
    start = time.time()
    max_retries = _get_env_int(ENV_HTTP_MAX_RETRIES)

    for attempt in range(max_retries + 1):
        try:
            with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
                body = resp.read().decode("utf-8") if resp is not None else ""
                latency_ms = (time.time() - start) * 1000
                if not body:
                    return resp.status, None, latency_ms, None
                try:
                    return resp.status, json.loads(body), latency_ms, None
                except Exception:
                    return resp.status, None, latency_ms, "Invalid JSON response"
        except urllib_error.HTTPError as e:
            latency_ms = (time.time() - start) * 1000
            try:
                body = e.read().decode("utf-8")
            except Exception:
                body = ""
            err = body or str(e)
            return int(getattr(e, "code", 0) or 0), None, latency_ms, err
        except (ssl.SSLError, urllib_error.URLError, TimeoutError) as e:
            if attempt < max_retries:
                time.sleep(0.2 * (2 ** attempt))
                continue
            latency_ms = (time.time() - start) * 1000
            return 0, None, latency_ms, str(e)
        except Exception as e:
            if attempt < max_retries:
                time.sleep(0.2 * (2 ** attempt))
                continue
            latency_ms = (time.time() - start) * 1000
            return 0, None, latency_ms, str(e)


def benchmark_function(func, iterations: int = 10, warmup: int = 2) -> BenchmarkResult:
    """Run benchmark on a latency-returning function (returns ms)"""
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
        try:
            latency = func()
            if latency is not None:
                latencies.append(float(latency))
        except Exception as e:
            errors += 1
            if _get_env_bool(ENV_VERBOSE_ERRORS, False):
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
    """Run concurrent benchmark on a latency-returning function (returns ms)"""
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
                if _get_env_bool(ENV_VERBOSE_ERRORS, False):
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
    """Run all benchmarks against Cloud Run API (end-to-end)"""
    print("=" * 70)
    print("NPC Memory RAG Performance Benchmark")
    print("=" * 70)
    print(f"Start time: {datetime.now().isoformat()}")
    print()

    api_base = _get_env_required(ENV_BENCH_API_BASE_URL).strip().rstrip("/")

    # Cloud Run request-reply may block up to REQUEST_TIMEOUT_SECONDS (default 25s),
    # so the client timeout should be safely higher to avoid false timeouts.
    timeout_seconds = _get_env_int(ENV_TIMEOUT_SECONDS)
    player_id = _get_env_required(ENV_PLAYER_ID)
    npc_id = _get_env_required(ENV_NPC_ID)
    seed_count = _get_env_int(ENV_SEED_COUNT)
    seed_enabled = _get_env_bool(ENV_SEED_ENABLED)
    search_iterations = _get_env_int(ENV_SEARCH_ITERATIONS)
    write_iterations = _get_env_int(ENV_WRITE_ITERATIONS)
    warmup = _get_env_int(ENV_WARMUP)
    concurrency_list = _parse_int_list(_get_env_required(ENV_CONCURRENCY_LIST))
    total_requests = _get_env_int(ENV_TOTAL_REQUESTS)

    report = BenchmarkReport(
        timestamp=datetime.now().isoformat(),
        environment={
            "BENCH_API_BASE_URL": api_base[:80] + ("..." if len(api_base) > 80 else ""),
            "BENCH_TIMEOUT_SECONDS": str(timeout_seconds),
            "BENCH_PLAYER_ID": player_id,
            "BENCH_NPC_ID": npc_id,
            "BENCH_SEED_ENABLED": str(seed_enabled),
            "BENCH_SEED_COUNT": str(seed_count),
            "BENCH_SEARCH_ITERATIONS": str(search_iterations),
            "BENCH_WRITE_ITERATIONS": str(write_iterations),
            "BENCH_WARMUP": str(warmup),
            "BENCH_CONCURRENCY_LIST": ",".join(str(x) for x in concurrency_list),
            "BENCH_TOTAL_REQUESTS": str(total_requests),
        }
    )

    # ==========================================================================
    # 1. Health / Ready
    # ==========================================================================
    print("[1] Testing API Health/Ready...")

    def call_health() -> float:
        status, _, latency, err = _http_json("GET", f"{api_base}/health", None, timeout_seconds)
        if status != 200:
            raise RuntimeError(f"/health failed: status={status}, err={err}")
        return latency

    def call_ready() -> float:
        status, _, latency, err = _http_json("GET", f"{api_base}/ready", None, timeout_seconds)
        if status != 200:
            raise RuntimeError(f"/ready failed: status={status}, err={err}")
        return latency

    health_result = benchmark_function(call_health, iterations=3, warmup=0)
    health_result.name = "api_health"
    report.results.append(health_result)
    ready_result = benchmark_function(call_ready, iterations=3, warmup=0)
    ready_result.name = "api_ready"
    report.results.append(ready_result)

    print(f"    /health avg={health_result.avg_ms:.0f}ms p95={health_result.p95_ms:.0f}ms")
    print(f"    /ready  avg={ready_result.avg_ms:.0f}ms p95={ready_result.p95_ms:.0f}ms")

    # ==========================================================================
    # 2. Seed Data (optional, recommended)
    # ==========================================================================
    print("\n[2] Seeding memories (optional)...")

    def post_memory(content: str, memory_type: str = "dialogue", importance: float = 0.8) -> float:
        payload = {
            "player_id": player_id,
            "npc_id": npc_id,
            "memory_type": memory_type,
            "content": content,
            "importance": importance,
            "emotion_tags": ["benchmark"],
            "game_context": {"source": "benchmark"},
        }
        status, body, latency, err = _http_json("POST", f"{api_base}/memories", payload, timeout_seconds)
        if status != 200:
            raise RuntimeError(f"POST /memories failed: status={status}, err={err}")
        if body and body.get("status") not in (None, "completed"):
            raise RuntimeError(f"POST /memories unexpected response: {body}")
        return latency

    if seed_enabled:
        seed_latencies: List[float] = []
        for i in range(seed_count):
            content = f"[seed] The blacksmith sold me a sword #{i} at {datetime.now().isoformat()}"
            try:
                seed_latencies.append(post_memory(content))
            except Exception as e:
                print(f"    Seed error: {e}")
        if seed_latencies:
            print(
                f"    Seeded {len(seed_latencies)}/{seed_count} memories, avg={statistics.mean(seed_latencies):.0f}ms"
            )
        else:
            print("    Seed failed (no successful writes). Search benchmark may be unstable.")
    else:
        print("    Seed disabled by BENCH_SEED_ENABLED=false")

    # ==========================================================================
    # 3. Write Latency Benchmark
    # ==========================================================================
    print("\n[3] Benchmarking Write Latency (POST /memories)...")

    write_counter = [0]

    def timed_write() -> float:
        write_counter[0] += 1
        content = f"[write_bench] I need a sword {write_counter[0]} {time.time_ns()}"
        return post_memory(content, memory_type="dialogue", importance=0.7)

    write_result = benchmark_function(timed_write, iterations=write_iterations, warmup=warmup)
    write_result.name = "write_memories"
    report.results.append(write_result)
    print(f"    avg={write_result.avg_ms:.0f}ms p95={write_result.p95_ms:.0f}ms errors={write_result.errors}")

    # ==========================================================================
    # 4. Search Latency Benchmark (cold vs cached approximation)
    # ==========================================================================
    print("\n[4] Benchmarking Search Latency (GET /search)...")

    def get_search_latency(query: str, top_k: int = 5) -> float:
        params = {
            "player_id": player_id,
            "npc_id": npc_id,
            "query": query,
            "top_k": str(top_k),
        }
        url = f"{api_base}/search?{urllib_parse.urlencode(params)}"
        status, body, latency, err = _http_json("GET", url, None, timeout_seconds)
        if status != 200:
            raise RuntimeError(f"GET /search failed: status={status}, err={err}")
        if body is None or "memories" not in body:
            raise RuntimeError(f"GET /search invalid response: {body}")
        return latency

    # Cold: unique query each time (approximate cache miss)
    cold_counter = [0]

    def timed_search_cold() -> float:
        cold_counter[0] += 1
        q = f"sword cold {cold_counter[0]} {time.time_ns()}"
        return get_search_latency(q)

    # Cached: same query repeated
    def timed_search_cached() -> float:
        return get_search_latency("sword")

    cold_result = benchmark_function(timed_search_cold, iterations=min(5, search_iterations), warmup=0)
    cold_result.name = "search_cold_unique_query"
    report.results.append(cold_result)

    cached_result = benchmark_function(timed_search_cached, iterations=search_iterations, warmup=warmup)
    cached_result.name = "search_cached_same_query"
    report.results.append(cached_result)

    improvement = (cold_result.avg_ms / cached_result.avg_ms) if cached_result.avg_ms > 0 else 0.0

    print(f"    cold avg={cold_result.avg_ms:.0f}ms p95={cold_result.p95_ms:.0f}ms")
    print(f"    cached avg={cached_result.avg_ms:.0f}ms p95={cached_result.p95_ms:.0f}ms")
    if improvement > 0:
        print(f"    improvement={improvement:.1f}x (cached vs cold approximation)")

    # Cache effectiveness
    if improvement > 3:
        report.recommendations.append(f"Cache is highly effective ({improvement:.1f}x improvement)")
    elif improvement > 1.5:
        report.recommendations.append(f"Cache provides moderate benefit ({improvement:.1f}x improvement)")
    else:
        report.bottlenecks.append("Cache benefit is minimal - check cache configuration")

    # Latency analysis
    if cached_result.avg_ms > 300:
        report.bottlenecks.append(f"Cached search latency is high ({cached_result.avg_ms:.0f}ms) - network/ES latency")
        report.recommendations.append("Deploy to same region as Elasticsearch")

    if cold_result.avg_ms > 1500:
        report.bottlenecks.append(f"Cold search latency is high ({cold_result.avg_ms:.0f}ms)")
        report.recommendations.append("Consider Redis for persistent embedding cache")

    # Concurrent scaling
    # ==========================================================================
    # 5. Concurrent Search Throughput Test
    # ==========================================================================
    print("\n[5] Benchmarking Concurrent Throughput (GET /search)...")
    print("    " + "-" * 50)
    print(f"    {'Concurrency':<12} {'Throughput':<15} {'Avg (ms)':<12} {'Errors':<10}")
    print("    " + "-" * 50)

    for concurrency in concurrency_list:
        result = benchmark_concurrent(timed_search_cached, concurrency, total_requests)
        result.name = f"search_concurrent_{concurrency}"
        print(f"    {concurrency:<12} {result.throughput:<15.2f} {result.avg_ms:<12.0f} {result.errors:<10}")
        report.results.append(result)

    concurrent_results = [r for r in report.results if r.name.startswith("search_concurrent_")]
    if len(concurrent_results) >= 2:
        low = min(concurrent_results, key=lambda r: int(r.name.split("_")[-1]))
        high = max(concurrent_results, key=lambda r: int(r.name.split("_")[-1]))
        c1 = int(low.name.split("_")[-1])
        c2 = int(high.name.split("_")[-1])
        t1 = low.throughput
        t2 = high.throughput
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

    print("\nAPI Health:")
    print("-" * 70)
    print(f"{'Scenario':<40} {'Avg (ms)':<12} {'P95 (ms)':<12} {'Errors':<8}")
    print("-" * 70)

    for r in report.results:
        if r.name in ("api_health", "api_ready"):
            print(f"{r.name:<40} {r.avg_ms:<12.0f} {r.p95_ms:<12.0f} {r.errors:<8d}")

    print("\nWrite:")
    print("-" * 70)
    print(f"{'Scenario':<40} {'Avg (ms)':<12} {'P95 (ms)':<12} {'Errors':<8}")
    print("-" * 70)
    for r in report.results:
        if r.name == "write_memories":
            print(f"{r.name:<40} {r.avg_ms:<12.0f} {r.p95_ms:<12.0f} {r.errors:<8d}")

    print("\nSearch:")
    print("-" * 70)
    print(f"{'Scenario':<40} {'Avg (ms)':<12} {'P95 (ms)':<12} {'Errors':<8}")
    print("-" * 70)
    for r in report.results:
        if r.name.startswith("search_") and not r.name.startswith("search_concurrent_"):
            print(f"{r.name:<40} {r.avg_ms:<12.0f} {r.p95_ms:<12.0f} {r.errors:<8d}")

    print("\nConcurrent Throughput:")
    print("-" * 70)
    for r in report.results:
        if r.name.startswith("search_concurrent_"):
            print(f"{r.name:<40} {r.throughput:.2f} req/s (avg {r.avg_ms:.0f}ms)")

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
