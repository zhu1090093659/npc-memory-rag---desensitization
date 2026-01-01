"""
Example: Live demo with cloud services (Cloud Run + Pub/Sub + Elastic Cloud)

Usage:
    python examples/live_demo.py

This script connects to:
    - Cloud Run (asia-east2): Push Worker service
    - Elastic Cloud: Vector database
    - Pub/Sub: Message queue
    - ModelScope: Qwen3 embedding
"""

import sys
import os
import time
import json
from datetime import datetime

# =============================================================================
# Cloud Configuration (Pre-configured for one-click demo)
# =============================================================================
os.environ.setdefault("ES_URL", "https://my-elasticsearch-project-aa20b7.es.asia-southeast1.gcp.elastic.cloud:443")
os.environ.setdefault("ES_API_KEY", "WjMzYWRKc0I0bzBHYktSaWl0LWk6dlY3N25kZ05jYzBZbURjVFV4NF9kZw==")
os.environ.setdefault("MODELSCOPE_API_KEY", "ms-970ab2e7-05a6-4fef-8561-869dc1ea2cac")
os.environ.setdefault("PUBSUB_PROJECT_ID", "npc-memory-rag")
os.environ.setdefault("CLOUD_RUN_URL", "https://npc-memory-worker-257652255998.asia-east2.run.app")
# =============================================================================

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.es_client import create_es_client
from src.memory import EmbeddingService, MemorySearcher
from src.indexing import IndexTask, PubSubPublisher


def check_cloud_run_health(base_url: str) -> bool:
    """Check Cloud Run service health"""
    import urllib.request
    import urllib.error

    endpoints = ["/health", "/ready"]
    print(f"\n[1] Checking Cloud Run service: {base_url}")

    for endpoint in endpoints:
        url = f"{base_url}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                status = data.get("status", "unknown")
                print(f"    {endpoint}: {status}")
        except urllib.error.URLError as e:
            print(f"    {endpoint}: FAILED - {e}")
            return False
        except Exception as e:
            print(f"    {endpoint}: ERROR - {e}")
            return False

    return True


def publish_test_memories(publisher: PubSubPublisher) -> list:
    """Publish test memories to Pub/Sub"""
    print("\n[2] Publishing test memories to Pub/Sub...")

    # Use timestamp suffix for unique IDs
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    tasks = [
        IndexTask.create(
            player_id="demo_player",
            npc_id="demo_blacksmith",
            content="玩家帮助铁匠找回了被盗的祖传锤子，铁匠非常感激",
            memory_type="quest",
            importance=0.9,
            emotion_tags=["感谢", "信任"],
            game_context={"location": "village_01", "quest_id": "find_hammer"}
        ),
        IndexTask.create(
            player_id="demo_player",
            npc_id="demo_blacksmith",
            content="玩家送给铁匠一瓶上好的麦酒作为礼物",
            memory_type="gift",
            importance=0.7,
            emotion_tags=["感谢", "友好"],
            game_context={"location": "village_01", "item": "fine_ale"}
        ),
        IndexTask.create(
            player_id="demo_player",
            npc_id="demo_blacksmith",
            content="玩家购买了一把精钢长剑，支付了150金币",
            memory_type="trade",
            importance=0.5,
            emotion_tags=["满意"],
            game_context={"location": "village_01", "item": "steel_sword", "price": 150}
        ),
        IndexTask.create(
            player_id="demo_player",
            npc_id="demo_blacksmith",
            content="玩家保护铁匠铺免受强盗袭击，击退了三名歹徒",
            memory_type="combat",
            importance=0.95,
            emotion_tags=["感谢", "尊敬", "信任"],
            game_context={"location": "village_01", "enemies": 3}
        ),
    ]

    # Publish
    message_ids = publisher.publish_batch(tasks)

    for task, msg_id in zip(tasks, message_ids):
        print(f"    Published: {task.task_id[:8]}... -> {task.content[:30]}...")

    print(f"    Total: {len(message_ids)} messages published")
    return tasks


def wait_for_indexing(seconds: int = 5):
    """Wait for Pub/Sub -> Worker -> ES pipeline"""
    print(f"\n[3] Waiting {seconds}s for indexing pipeline...")
    for i in range(seconds, 0, -1):
        print(f"    {i}...", end=" ", flush=True)
        time.sleep(1)
    print("Done!")


def search_memories(es_client, embedder, player_id: str, npc_id: str, query: str):
    """Execute hybrid search and display results"""
    print(f"\n[4] Executing hybrid search...")
    print(f"    Query: \"{query}\"")
    print(f"    Player: {player_id}, NPC: {npc_id}")

    searcher = MemorySearcher(es_client, embedder)

    try:
        memories = searcher.search_memories(
            player_id=player_id,
            npc_id=npc_id,
            query=query,
            top_k=5
        )

        print(f"\n    Results ({len(memories)} found):")
        print("    " + "-" * 60)

        for i, m in enumerate(memories, 1):
            days_ago = (datetime.now() - m.timestamp).days
            time_desc = "today" if days_ago == 0 else f"{days_ago}d ago"
            print(f"    {i}. [{m.memory_type.value}] {m.content[:50]}...")
            print(f"       Importance: {m.importance:.3f} (decayed), Time: {time_desc}")
            print(f"       Emotions: {m.emotion_tags}")

        return memories

    except Exception as e:
        print(f"    Search failed: {e}")
        return []


def query_es_directly(es_client, player_id: str, npc_id: str):
    """Query ES directly to verify data exists"""
    print(f"\n[5] Querying ES directly...")

    try:
        result = es_client.search(
            index="npc_memories",
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"player_id": player_id}},
                            {"term": {"npc_id": npc_id}}
                        ]
                    }
                },
                "size": 10,
                "_source": ["content", "memory_type", "importance", "timestamp"]
            }
        )

        hits = result["hits"]["hits"]
        print(f"    Found {len(hits)} documents in ES:")

        for hit in hits:
            doc = hit["_source"]
            print(f"    - [{doc['memory_type']}] {doc['content'][:40]}...")

        return hits

    except Exception as e:
        print(f"    ES query failed: {e}")
        return []


def generate_llm_context(memories: list) -> str:
    """Generate context for LLM prompt"""
    if not memories:
        return "This is your first time meeting this player."

    context_parts = ["Your memories of this player:"]
    for i, m in enumerate(memories, 1):
        days_ago = (datetime.now() - m.timestamp).days
        time_desc = "today" if days_ago == 0 else f"{days_ago} days ago"
        context_parts.append(f"{i}. [{time_desc}] {m.content}")

    # Relationship assessment
    positive = sum(1 for m in memories if any(t in m.emotion_tags for t in ["感谢", "友好", "信任"]))
    negative = sum(1 for m in memories if any(t in m.emotion_tags for t in ["愤怒", "失望"]))

    if positive > negative:
        context_parts.append(f"\nRelationship: Friendly ({positive} positive interactions)")
    elif negative > positive:
        context_parts.append(f"\nRelationship: Tense ({negative} negative interactions)")
    else:
        context_parts.append("\nRelationship: Neutral")

    return "\n".join(context_parts)


def main():
    print("""
================================================================================
                    NPC Memory RAG - Live Cloud Demo
================================================================================
    Cloud Run (asia-east2) + Pub/Sub + Elastic Cloud + ModelScope Qwen3
================================================================================
""")

    # Check required environment variables
    es_url = os.getenv("ES_URL")
    es_api_key = os.getenv("ES_API_KEY")
    pubsub_project = os.getenv("PUBSUB_PROJECT_ID")
    cloud_run_url = os.getenv("CLOUD_RUN_URL")

    if not es_url or not es_api_key:
        print("ERROR: ES_URL and ES_API_KEY are required")
        print("Please set environment variables:")
        print("  export ES_URL='https://your-es-host:443'")
        print("  export ES_API_KEY='your-api-key'")
        sys.exit(1)

    # Step 1: Check Cloud Run health (optional)
    if cloud_run_url:
        check_cloud_run_health(cloud_run_url)
    else:
        print("[1] Skipping Cloud Run health check (CLOUD_RUN_URL not set)")

    # Step 2: Publish test memories (optional)
    if pubsub_project:
        try:
            publisher = PubSubPublisher()
            tasks = publish_test_memories(publisher)
            wait_for_indexing(8)
        except Exception as e:
            print(f"[2] Pub/Sub publish failed: {e}")
            print("    Continuing with existing data...")
    else:
        print("[2] Skipping Pub/Sub publish (PUBSUB_PROJECT_ID not set)")
        print("    Will search existing data in ES...")

    # Step 3: Connect to ES
    print("\n[3] Connecting to Elasticsearch...")
    try:
        es_client = create_es_client()
        info = es_client.info()
        print(f"    Connected to: {info.get('cluster_name', 'unknown')}")
        print(f"    Version: {info.get('version', {}).get('number', 'unknown')}")
    except Exception as e:
        print(f"    Connection failed: {e}")
        sys.exit(1)

    # Step 4: Initialize embedding service
    print("\n[4] Initializing embedding service...")
    try:
        embedder = EmbeddingService()
        provider = "stub" if embedder._use_stub else f"ModelScope ({embedder.model_name})"
        print(f"    Provider: {provider}")
    except Exception as e:
        print(f"    Failed: {e}")
        sys.exit(1)

    # Step 5: Query ES directly (use existing test data)
    # Note: player_1/npc_blacksmith were created during Cloud Run deployment testing
    player_id = "player_1"
    npc_id = "npc_blacksmith"
    query_es_directly(es_client, player_id, npc_id)

    # Step 6: Hybrid search demo
    print("\n" + "=" * 60)
    print("HYBRID SEARCH DEMO (BM25 + Vector + RRF)")
    print("=" * 60)

    queries = [
        "你还记得我吗？",
        "sword",
        "blacksmith"
    ]

    for query in queries:
        memories = search_memories(
            es_client, embedder,
            player_id=player_id,
            npc_id=npc_id,
            query=query
        )

        if memories:
            print("\n    LLM Context:")
            print("    " + "-" * 60)
            context = generate_llm_context(memories)
            for line in context.split("\n"):
                print(f"    {line}")

        print()

    print("=" * 60)
    print("Demo completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
