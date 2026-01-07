"""
Test the genetic optimization API endpoint

This script tests the optimization logic without requiring full infrastructure.
"""

import sys
import os
import json

# Add paths for imports
module_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'api', 'src', 'memory')
if module_path not in sys.path:
    sys.path.insert(0, module_path)

# Import the genetic optimizer directly
from genetic_optimizer import (
    GeneticOptimizer,
    GAConfig,
    SearchParameters,
    create_fitness_function,
)


def test_optimization_request_schema():
    """Test optimization request schema validation"""
    print("\n" + "=" * 60)
    print("Test 1: Optimization Request Data Structure")
    print("=" * 60)
    
    request_data = {
        "test_queries": [
            {"player_id": "p1", "npc_id": "n1", "query": "找回丢失的剑"},
            {"player_id": "p1", "npc_id": "n1", "query": "昨天的对话"}
        ],
        "ground_truth": [
            ["mem1", "mem2", "mem3"],
            ["mem4", "mem5"]
        ],
        "ga_config": {
            "population_size": 10,
            "generations": 3,
            "mutation_rate": 0.1
        }
    }
    
    try:
        # Validate data structure manually (without pydantic)
        assert "test_queries" in request_data
        assert "ground_truth" in request_data
        assert len(request_data["test_queries"]) == len(request_data["ground_truth"])
        
        print(f"✓ Request data structure validation passed")
        print(f"  Test queries: {len(request_data['test_queries'])}")
        print(f"  Ground truth sets: {len(request_data['ground_truth'])}")
        print(f"  Population size: {request_data['ga_config']['population_size']}")
        print(f"  Generations: {request_data['ga_config']['generations']}")
        return True
    except Exception as e:
        print(f"✗ Request data validation failed: {e}")
        return False


def test_optimization_logic():
    """Test the optimization logic that would run in the API"""
    print("\n" + "=" * 60)
    print("Test 2: Optimization Logic")
    print("=" * 60)
    
    # Prepare test data
    test_queries = [
        {"player_id": "p1", "npc_id": "n1", "query": "购买药水"},
        {"player_id": "p1", "npc_id": "n1", "query": "上次交易"},
    ]
    
    ground_truth = [
        ["mem_trade_001", "mem_trade_002"],
        ["mem_dialogue_015", "mem_trade_001"],
    ]
    
    # Mock search function
    def mock_search(player_id, npc_id, query, params):
        # Simulate: better parameters return better results
        if 45 <= params.rrf_k <= 75 and params.decay_lambda < 0.02:
            # Good parameters
            return ground_truth[0] if "药水" in query else ground_truth[1]
        else:
            # Poor parameters
            return ["mem_random_1", "mem_random_2"]
    
    # Create fitness function
    fitness_func = create_fitness_function(test_queries, ground_truth, mock_search)
    
    # Run optimization
    ga_config = GAConfig(population_size=8, generations=4)
    optimizer = GeneticOptimizer(ga_config)
    
    try:
        result = optimizer.optimize(fitness_func=fitness_func)
        
        print(f"✓ Optimization completed successfully")
        print(f"  Best fitness: {result.best_fitness:.4f}")
        print(f"  Generations run: {result.generations_run}")
        print(f"  Best parameters:")
        for key, value in result.best_parameters.to_dict().items():
            print(f"    {key}: {value:.4f}")
        
        # Verify result structure
        assert result.best_parameters is not None
        assert 0.0 <= result.best_fitness <= 1.0
        assert result.generations_run == ga_config.generations
        assert len(result.fitness_history) == ga_config.generations
        
        return True
    except Exception as e:
        print(f"✗ Optimization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_optimization_with_minimal_config():
    """Test optimization with minimal GA configuration"""
    print("\n" + "=" * 60)
    print("Test 3: Optimization with Minimal Config")
    print("=" * 60)
    
    test_queries = [{"player_id": "p1", "npc_id": "n1", "query": "test"}]
    ground_truth = [["mem1"]]
    
    def simple_search(player_id, npc_id, query, params):
        return ["mem1"]
    
    fitness_func = create_fitness_function(test_queries, ground_truth, simple_search)
    
    # Use default config
    optimizer = GeneticOptimizer()
    
    try:
        result = optimizer.optimize(fitness_func=fitness_func, generations=2)
        
        print(f"✓ Minimal config optimization passed")
        print(f"  Default population size: {optimizer.config.population_size}")
        print(f"  Generations requested: 2")
        print(f"  Generations run: {result.generations_run}")
        
        return True
    except Exception as e:
        print(f"✗ Minimal config optimization failed: {e}")
        return False


def test_json_serialization():
    """Test JSON serialization of optimization results"""
    print("\n" + "=" * 60)
    print("Test 4: JSON Serialization")
    print("=" * 60)
    
    # Run a quick optimization
    test_queries = [{"player_id": "p1", "npc_id": "n1", "query": "test"}]
    ground_truth = [["mem1", "mem2"]]
    
    def mock_search(player_id, npc_id, query, params):
        return ["mem1", "mem2"]
    
    fitness_func = create_fitness_function(test_queries, ground_truth, mock_search)
    optimizer = GeneticOptimizer(GAConfig(population_size=5, generations=2))
    
    try:
        result = optimizer.optimize(fitness_func=fitness_func)
        
        # Convert to dict (as API would do)
        result_dict = result.to_dict()
        
        # Serialize to JSON
        json_str = json.dumps(result_dict, indent=2)
        
        # Deserialize
        loaded_dict = json.loads(json_str)
        
        print(f"✓ JSON serialization passed")
        print(f"  JSON size: {len(json_str)} bytes")
        print(f"  Contains best_parameters: {'best_parameters' in loaded_dict}")
        print(f"  Contains fitness_history: {'fitness_history' in loaded_dict}")
        
        # Verify key fields
        assert 'best_parameters' in loaded_dict
        assert 'best_fitness' in loaded_dict
        assert 'generations_run' in loaded_dict
        assert 'fitness_history' in loaded_dict
        
        return True
    except Exception as e:
        print(f"✗ JSON serialization failed: {e}")
        return False


def run_all_tests():
    """Run all API endpoint tests"""
    print("\n" + "=" * 70)
    print("Genetic Algorithm API Endpoint Tests")
    print("=" * 70)
    
    tests = [
        test_optimization_request_schema,
        test_optimization_logic,
        test_optimization_with_minimal_config,
        test_json_serialization,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n✗ Test {test.__name__} raised exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 70 + "\n")
    
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    
    if success:
        print("✅ All API endpoint tests passed!")
        print("\n📝 Next steps:")
        print("  1. Deploy to Cloud Run to test in production environment")
        print("  2. Test the POST /optimize endpoint with real data")
        print("  3. Monitor optimization performance and resource usage")
    else:
        print("❌ Some tests failed. Please review the output above.")
    
    sys.exit(0 if success else 1)
