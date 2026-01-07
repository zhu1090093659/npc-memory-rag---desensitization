"""
Complete Example: Using Genetic Algorithm to Optimize NPC Memory Search

This example demonstrates:
1. Collecting test queries and ground truth
2. Running genetic algorithm optimization
3. Evaluating and comparing results
4. Applying optimized parameters
"""

import sys
import os
import json
from typing import List, Dict, Any

# Add memory module to path
module_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'api', 'src', 'memory')
if module_path not in sys.path:
    sys.path.insert(0, module_path)

from genetic_optimizer import (
    GeneticOptimizer,
    GAConfig,
    SearchParameters,
    create_fitness_function,
)


def simulate_search_system(query: Dict[str, str], params: SearchParameters) -> List[str]:
    """
    Simulated search system for demonstration.
    
    In production, this would call your actual search API with custom parameters.
    """
    # Simulate different results based on parameters
    query_text = query.get('query', '')
    
    # Simulate: good parameters (balanced, moderate values) return better results
    is_good_params = (
        40 <= params.rrf_k <= 80 and
        0.005 <= params.decay_lambda <= 0.02 and
        0.15 <= params.importance_floor <= 0.3 and
        0.4 <= params.bm25_weight <= 0.6
    )
    
    if is_good_params:
        # Good parameters: return relevant results
        if "药水" in query_text or "potion" in query_text:
            return ["trade_potion_001", "trade_potion_002", "dialogue_shop_015"]
        elif "任务" in query_text or "quest" in query_text:
            return ["quest_main_042", "dialogue_quest_033", "quest_side_011"]
        elif "对话" in query_text or "talk" in query_text:
            return ["dialogue_casual_088", "dialogue_quest_033", "dialogue_shop_015"]
        else:
            return ["memory_001", "memory_002", "memory_003"]
    else:
        # Poor parameters: return less relevant results
        return ["random_mem_1", "random_mem_2", "random_mem_3"]


def create_test_dataset() -> tuple[List[Dict[str, str]], List[List[str]]]:
    """
    Create a test dataset with queries and expected results.
    
    In production, collect these from:
    - User logs
    - Expert annotations
    - A/B test results
    """
    test_queries = [
        {"player_id": "p001", "npc_id": "merchant_zhao", "query": "购买药水"},
        {"player_id": "p001", "npc_id": "merchant_zhao", "query": "上次买的药水效果如何"},
        {"player_id": "p002", "npc_id": "guard_li", "query": "城门任务"},
        {"player_id": "p002", "npc_id": "guard_li", "query": "关于守卫的对话"},
        {"player_id": "p003", "npc_id": "elder_wang", "query": "村长交代的任务"},
    ]
    
    ground_truth = [
        ["trade_potion_001", "trade_potion_002", "dialogue_shop_015"],
        ["trade_potion_001", "dialogue_shop_015", "trade_potion_002"],
        ["quest_main_042", "dialogue_quest_033", "quest_side_011"],
        ["dialogue_casual_088", "dialogue_quest_033"],
        ["quest_main_042", "quest_side_011", "dialogue_quest_033"],
    ]
    
    return test_queries, ground_truth


def evaluate_parameters(
    params: SearchParameters,
    test_queries: List[Dict[str, str]],
    ground_truth: List[List[str]]
) -> tuple[float, Dict[str, Any]]:
    """
    Evaluate search parameters and return detailed metrics.
    
    Returns:
        (overall_score, detailed_metrics)
    """
    total_precision = 0.0
    total_recall = 0.0
    query_scores = []
    
    for i, query in enumerate(test_queries):
        results = simulate_search_system(query, params)
        expected = set(ground_truth[i])
        
        if not expected:
            continue
        
        # Calculate precision@k
        k = min(len(results), len(expected), 5)
        relevant_found = len(set(results[:k]) & expected)
        precision = relevant_found / k if k > 0 else 0.0
        
        # Calculate recall@k
        recall = relevant_found / len(expected) if expected else 0.0
        
        total_precision += precision
        total_recall += recall
        query_scores.append({
            'query': query['query'],
            'precision': precision,
            'recall': recall,
            'found': relevant_found,
            'expected': len(expected)
        })
    
    n = len(test_queries)
    avg_precision = total_precision / n if n > 0 else 0.0
    avg_recall = total_recall / n if n > 0 else 0.0
    f1_score = 2 * avg_precision * avg_recall / (avg_precision + avg_recall) if (avg_precision + avg_recall) > 0 else 0.0
    
    return avg_precision, {
        'avg_precision': avg_precision,
        'avg_recall': avg_recall,
        'f1_score': f1_score,
        'query_scores': query_scores,
    }


def main():
    """Run complete genetic algorithm optimization example"""
    print("\n" + "=" * 70)
    print("Genetic Algorithm Optimization - Complete Example")
    print("=" * 70)
    
    # Step 1: Create test dataset
    print("\n📊 Step 1: Creating test dataset...")
    test_queries, ground_truth = create_test_dataset()
    print(f"  Created {len(test_queries)} test queries")
    print(f"  Sample query: {test_queries[0]['query']}")
    print(f"  Sample expected results: {ground_truth[0][:2]}")
    
    # Step 2: Evaluate baseline (default parameters)
    print("\n📏 Step 2: Evaluating baseline (default parameters)...")
    baseline_params = SearchParameters()
    baseline_score, baseline_metrics = evaluate_parameters(
        baseline_params, test_queries, ground_truth
    )
    print(f"  Baseline precision: {baseline_metrics['avg_precision']:.4f}")
    print(f"  Baseline recall: {baseline_metrics['avg_recall']:.4f}")
    print(f"  Baseline F1: {baseline_metrics['f1_score']:.4f}")
    
    # Step 3: Run genetic algorithm optimization
    print("\n🧬 Step 3: Running genetic algorithm optimization...")
    
    # Configure GA
    ga_config = GAConfig(
        population_size=20,
        generations=12,
        mutation_rate=0.12,
        mutation_strength=0.25,
        crossover_rate=0.7,
        elitism_count=3,
        tournament_size=3,
    )
    
    print(f"  Population size: {ga_config.population_size}")
    print(f"  Generations: {ga_config.generations}")
    print(f"  Mutation rate: {ga_config.mutation_rate}")
    
    # Create fitness function
    def fitness_func(params: SearchParameters) -> float:
        score, _ = evaluate_parameters(params, test_queries, ground_truth)
        return score
    
    # Run optimization
    optimizer = GeneticOptimizer(ga_config)
    print("\n  Optimizing... (this may take a moment)")
    result = optimizer.optimize(fitness_func=fitness_func)
    
    print(f"\n  ✓ Optimization complete!")
    print(f"  Best fitness: {result.best_fitness:.4f}")
    print(f"  Improvement: {((result.best_fitness - baseline_score) / baseline_score * 100):.1f}%")
    
    # Step 4: Show optimization progress
    print("\n📈 Step 4: Optimization progress:")
    print(f"  {'Generation':<12} {'Best':<12} {'Average':<12} {'Worst':<12}")
    print("  " + "-" * 50)
    for gen, (best, avg, worst) in enumerate(result.fitness_history[:5]):
        print(f"  {gen:<12} {best:<12.4f} {avg:<12.4f} {worst:<12.4f}")
    if len(result.fitness_history) > 5:
        print(f"  ...")
        gen, (best, avg, worst) = len(result.fitness_history) - 1, result.fitness_history[-1]
        print(f"  {gen:<12} {best:<12.4f} {avg:<12.4f} {worst:<12.4f}")
    
    # Step 5: Evaluate optimized parameters
    print("\n🎯 Step 5: Evaluating optimized parameters...")
    optimized_score, optimized_metrics = evaluate_parameters(
        result.best_parameters, test_queries, ground_truth
    )
    print(f"  Optimized precision: {optimized_metrics['avg_precision']:.4f}")
    print(f"  Optimized recall: {optimized_metrics['avg_recall']:.4f}")
    print(f"  Optimized F1: {optimized_metrics['f1_score']:.4f}")
    
    # Step 6: Compare parameters
    print("\n🔍 Step 6: Parameter comparison:")
    print(f"  {'Parameter':<25} {'Baseline':<15} {'Optimized':<15} {'Change':<15}")
    print("  " + "-" * 70)
    
    baseline_dict = baseline_params.to_dict()
    optimized_dict = result.best_parameters.to_dict()
    
    for key in baseline_dict.keys():
        baseline_val = baseline_dict[key]
        optimized_val = optimized_dict[key]
        change = ((optimized_val - baseline_val) / baseline_val * 100) if baseline_val != 0 else 0
        print(f"  {key:<25} {baseline_val:<15.4f} {optimized_val:<15.4f} {change:>+6.1f}%")
    
    # Step 7: Save results
    print("\n💾 Step 7: Saving optimized parameters...")
    output_file = "/tmp/optimized_search_params.json"
    
    output_data = {
        'optimized_parameters': optimized_dict,
        'baseline_parameters': baseline_dict,
        'optimization_results': {
            'baseline_metrics': baseline_metrics,
            'optimized_metrics': optimized_metrics,
            'improvement_percent': ((optimized_score - baseline_score) / baseline_score * 100) if baseline_score > 0 else 0,
        },
        'ga_config': ga_config.to_dict(),
        'timestamp': result.timestamp,
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"  Saved to: {output_file}")
    print(f"  File size: {os.path.getsize(output_file)} bytes")
    
    # Step 8: Recommendations
    print("\n📋 Step 8: Next steps and recommendations:")
    
    if optimized_score > baseline_score * 1.05:
        print("  ✅ Significant improvement achieved!")
        print("  Recommended actions:")
        print("    1. Deploy optimized parameters to staging environment")
        print("    2. Run A/B test comparing baseline vs optimized")
        print("    3. Monitor search quality metrics in production")
        print("    4. Re-optimize periodically as data evolves")
    elif optimized_score > baseline_score:
        print("  ✓ Modest improvement achieved")
        print("  Recommended actions:")
        print("    1. Collect more diverse test queries")
        print("    2. Try longer optimization (more generations)")
        print("    3. Consider multi-objective optimization")
    else:
        print("  ⚠ No improvement or degradation")
        print("  Recommended actions:")
        print("    1. Verify test queries are representative")
        print("    2. Check if baseline was already well-tuned")
        print("    3. Try different GA configuration")
    
    print("\n" + "=" * 70)
    print("Optimization Complete!")
    print("=" * 70 + "\n")
    
    return output_data


if __name__ == "__main__":
    try:
        result = main()
        
        print("✅ Example completed successfully!")
        print(f"\nYou can view the detailed results in:")
        print(f"  /tmp/optimized_search_params.json")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
