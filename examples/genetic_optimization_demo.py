"""
Genetic Algorithm Optimization Demo

This example demonstrates how to use genetic algorithms to optimize
search parameters for the NPC Memory RAG system.

Usage:
    python examples/genetic_optimization_demo.py
"""

import os
import sys
import json
from typing import List, Dict, Any

# Direct import of genetic optimizer (standalone, no dependencies on other modules)
# Add the memory module to path
module_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'api', 'src', 'memory')
if module_path not in sys.path:
    sys.path.insert(0, module_path)

from genetic_optimizer import (
    GeneticOptimizer,
    GAConfig,
    SearchParameters,
    create_fitness_function,
)


def demo_basic_optimization():
    """Demo: Basic genetic algorithm optimization"""
    print("=" * 60)
    print("Demo 1: Basic Genetic Algorithm Optimization")
    print("=" * 60)
    
    # Create GA configuration
    config = GAConfig(
        population_size=10,
        generations=5,
        mutation_rate=0.15,
        mutation_strength=0.25,
        crossover_rate=0.7,
        elitism_count=2,
        tournament_size=3,
    )
    
    print(f"\nGA Configuration:")
    for key, value in config.to_dict().items():
        print(f"  {key}: {value}")
    
    # Simple fitness function (for demo purposes)
    # In real usage, this would evaluate actual search quality
    def simple_fitness(params: SearchParameters) -> float:
        """
        Demo fitness function that prefers:
        - RRF k around 60
        - Decay lambda around 0.01
        - Balanced BM25/vector weights
        """
        score = 0.0
        
        # Prefer RRF k around 60
        rrf_score = 1.0 - min(abs(params.rrf_k - 60.0) / 60.0, 1.0)
        score += rrf_score * 0.3
        
        # Prefer decay lambda around 0.01
        decay_score = 1.0 - min(abs(params.decay_lambda - 0.01) / 0.01, 1.0)
        score += decay_score * 0.2
        
        # Prefer balanced weights
        weight_balance = 1.0 - abs(params.bm25_weight - params.vector_weight)
        score += weight_balance * 0.3
        
        # Prefer importance floor around 0.2
        floor_score = 1.0 - min(abs(params.importance_floor - 0.2) / 0.2, 1.0)
        score += floor_score * 0.2
        
        return score
    
    # Run optimization
    optimizer = GeneticOptimizer(config)
    print("\nRunning genetic algorithm optimization...")
    result = optimizer.optimize(fitness_func=simple_fitness)
    
    # Display results
    print(f"\n{'Generation':<12} {'Best':<12} {'Average':<12} {'Worst':<12}")
    print("-" * 50)
    for gen, (best, avg, worst) in enumerate(result.fitness_history):
        print(f"{gen:<12} {best:<12.4f} {avg:<12.4f} {worst:<12.4f}")
    
    print(f"\n\nBest Parameters Found:")
    print(f"  Fitness: {result.best_fitness:.4f}")
    for key, value in result.best_parameters.to_dict().items():
        print(f"  {key}: {value:.4f}")
    
    return result


def demo_parameter_evolution():
    """Demo: Show how parameters evolve over generations"""
    print("\n" + "=" * 60)
    print("Demo 2: Parameter Evolution Visualization")
    print("=" * 60)
    
    config = GAConfig(
        population_size=15,
        generations=8,
        mutation_rate=0.1,
        elitism_count=3,
    )
    
    def fitness(params: SearchParameters) -> float:
        # Prefer specific parameter values
        target_rrf_k = 50.0
        target_decay = 0.015
        
        rrf_error = abs(params.rrf_k - target_rrf_k) / target_rrf_k
        decay_error = abs(params.decay_lambda - target_decay) / target_decay
        
        return 1.0 / (1.0 + rrf_error + decay_error)
    
    optimizer = GeneticOptimizer(config)
    result = optimizer.optimize(fitness_func=fitness)
    
    # Show parameter convergence
    print("\nParameter Convergence:")
    print(f"{'Gen':<5} {'RRF_k (Best)':<15} {'Decay_λ (Best)':<15} {'Fitness':<10}")
    print("-" * 50)
    
    for gen, population in enumerate(result.population_history):
        best = max(population, key=lambda ind: ind.fitness)
        print(f"{gen:<5} {best.parameters.rrf_k:<15.4f} "
              f"{best.parameters.decay_lambda:<15.6f} {best.fitness:<10.4f}")
    
    return result


def demo_with_test_data():
    """Demo: Optimization with simulated test queries"""
    print("\n" + "=" * 60)
    print("Demo 3: Optimization with Test Queries")
    print("=" * 60)
    
    # Simulated test queries and ground truth
    test_queries = [
        {"player_id": "player1", "npc_id": "npc1", "query": "找回丢失的剑"},
        {"player_id": "player1", "npc_id": "npc1", "query": "昨天的对话"},
        {"player_id": "player2", "npc_id": "npc2", "query": "购买药水"},
    ]
    
    ground_truth = [
        ["mem1", "mem2", "mem3"],
        ["mem4", "mem5"],
        ["mem6", "mem7", "mem8"],
    ]
    
    # Simulated search function
    def mock_search(player_id: str, npc_id: str, query: str, params: SearchParameters) -> List[str]:
        """Mock search that returns results based on parameters"""
        # Simulate: better parameters = better results
        if params.rrf_k > 40 and params.rrf_k < 80 and params.decay_lambda < 0.02:
            # Good parameters return correct results
            query_idx = len(query) % len(ground_truth)
            return ground_truth[query_idx]
        else:
            # Poor parameters return random results
            return [f"mem{i}" for i in range(1, 4)]
    
    # Create fitness function
    fitness_func = create_fitness_function(test_queries, ground_truth, mock_search)
    
    # Optimize
    config = GAConfig(population_size=12, generations=6)
    optimizer = GeneticOptimizer(config)
    
    print("\nOptimizing parameters using test queries...")
    result = optimizer.optimize(fitness_func=fitness_func)
    
    print(f"\nOptimization complete!")
    print(f"Best fitness: {result.best_fitness:.4f}")
    print(f"Best parameters:")
    for key, value in result.best_parameters.to_dict().items():
        print(f"  {key}: {value:.4f}")
    
    return result


def demo_save_and_load():
    """Demo: Save and load optimization results"""
    print("\n" + "=" * 60)
    print("Demo 4: Save and Load Results")
    print("=" * 60)
    
    # Run quick optimization
    config = GAConfig(population_size=8, generations=3)
    optimizer = GeneticOptimizer(config)
    
    def simple_fitness(params: SearchParameters) -> float:
        return 1.0 - abs(params.rrf_k - 55.0) / 100.0
    
    result = optimizer.optimize(fitness_func=simple_fitness)
    
    # Save to JSON
    output_file = "/tmp/ga_optimization_result.json"
    result_dict = result.to_dict()
    
    with open(output_file, 'w') as f:
        json.dump(result_dict, f, indent=2)
    
    print(f"\nSaved optimization result to: {output_file}")
    print(f"File size: {os.path.getsize(output_file)} bytes")
    
    # Load from JSON
    with open(output_file, 'r') as f:
        loaded_dict = json.load(f)
    
    loaded_params = SearchParameters.from_dict(loaded_dict['best_parameters'])
    
    print(f"\nLoaded parameters:")
    for key, value in loaded_params.to_dict().items():
        print(f"  {key}: {value:.4f}")
    
    print(f"\nMatches original: {loaded_params.to_dict() == result.best_parameters.to_dict()}")
    
    return result


def main():
    """Run all demos"""
    print("\n" + "=" * 60)
    print("Genetic Algorithm Optimization Examples")
    print("NPC Memory RAG System")
    print("=" * 60)
    
    try:
        # Run demos
        demo_basic_optimization()
        demo_parameter_evolution()
        demo_with_test_data()
        demo_save_and_load()
        
        print("\n" + "=" * 60)
        print("All demos completed successfully!")
        print("=" * 60)
        
        print("\n📚 Next Steps:")
        print("  1. Collect real search queries and ground truth data")
        print("  2. Implement actual search evaluation metrics")
        print("  3. Run optimization with production data")
        print("  4. Deploy optimized parameters to production")
        print("  5. Monitor search quality improvements")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
