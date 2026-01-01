"""Quick test for new embedding configuration"""
import os
import sys

# Set environment variables
os.environ['EMBEDDING_API_KEY'] = 'sk-OI98X2iylUhYtncA518f4c7dEa0746A290D590B90c941d01'
os.environ['EMBEDDING_BASE_URL'] = 'https://api.bltcy.ai/v1'
os.environ['EMBEDDING_MODEL'] = 'qwen3-embedding-8b'
os.environ['INDEX_VECTOR_DIMS'] = '1024'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.memory import EmbeddingService

def main():
    print("=" * 60)
    print("Testing New Embedding Configuration")
    print("=" * 60)

    embedder = EmbeddingService()
    print(f"Model: {embedder.model_name}")
    print(f"Dimension: {embedder.dimension}")
    print(f"Using stub: {embedder._use_stub}")

    # Test embedding
    text = "你好，这是一个测试"
    print(f"\nTest text: '{text}'")

    vector = embedder.embed(text)
    print(f"Vector length: {len(vector)}")
    print(f"First 5 values: {vector[:5]}")

    if len(vector) == 1024:
        print("\n[OK] Vector dimension is correct (1024)")
    else:
        print(f"\n[WARNING] Vector dimension mismatch: expected 1024, got {len(vector)}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
