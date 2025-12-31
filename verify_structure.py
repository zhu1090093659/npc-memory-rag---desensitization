"""
Verify project structure without running
"""

import os
import sys

def check_file_exists(path):
    """Check if file exists"""
    full_path = os.path.join(".", path)
    exists = os.path.exists(full_path)
    status = "✓" if exists else "✗"
    print(f"{status} {path}")
    return exists

def main():
    print("=== Project Structure Verification ===\n")

    print("Core Memory Module:")
    check_file_exists("src/memory/__init__.py")
    check_file_exists("src/memory/models.py")
    check_file_exists("src/memory/embedding.py")
    check_file_exists("src/memory/es_schema.py")
    check_file_exists("src/memory/search.py")
    check_file_exists("src/memory/write.py")

    print("\nIndexing Module:")
    check_file_exists("src/indexing/__init__.py")
    check_file_exists("src/indexing/tasks.py")
    check_file_exists("src/indexing/pubsub_client.py")
    check_file_exists("src/indexing/worker.py")
    check_file_exists("src/indexing/push_app.py")

    print("\nFacade & Utils:")
    check_file_exists("src/memory_service.py")
    check_file_exists("src/es_client.py")
    check_file_exists("src/metrics.py")

    print("\nExamples:")
    check_file_exists("examples/init_es.py")
    check_file_exists("examples/publish_task.py")
    check_file_exists("examples/run_worker.py")
    check_file_exists("examples/rollover_index.py")

    print("\nDocumentation:")
    check_file_exists("README.md")
    check_file_exists("ASYNC_INDEXING.md")
    check_file_exists("REFACTORING_SUMMARY.md")
    check_file_exists("PROJECT_OVERVIEW.md")
    check_file_exists("CLAUDE.md")
    check_file_exists("requirements.txt")

    print("\nDocker & Config:")
    check_file_exists("docker-compose.yml")
    check_file_exists("prometheus.yml")

    print("\n=== Verification Complete ===")

if __name__ == "__main__":
    main()
