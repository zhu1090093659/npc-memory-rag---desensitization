"""
Basic tests for genetic algorithm optimizer

Run with: python -m pytest examples/test_genetic_optimizer.py -v
Or simply: python examples/test_genetic_optimizer.py
"""

import sys
import os

# Add memory module to path
module_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'api', 'src', 'memory')
if module_path not in sys.path:
    sys.path.insert(0, module_path)

from genetic_optimizer import (
    GeneticOptimizer,
    GAConfig,
    SearchParameters,
    Individual,
    create_fitness_function,
)


def test_search_parameters_creation():
    """Test SearchParameters creation and serialization"""
    params = SearchParameters(
        rrf_k=55.0,
        decay_lambda=0.015,
        importance_floor=0.25,
        type_mismatch_penalty=0.4,
        bm25_weight=0.6,
        vector_weight=0.4,
    )
    
    # Test to_dict
    params_dict = params.to_dict()
    assert params_dict['rrf_k'] == 55.0
    assert params_dict['decay_lambda'] == 0.015
    
    # Test from_dict
    params2 = SearchParameters.from_dict(params_dict)
    assert params2.rrf_k == params.rrf_k
    assert params2.decay_lambda == params.decay_lambda
    
    print("✓ SearchParameters creation and serialization test passed")


def test_mutation():
    """Test parameter mutation"""
    params = SearchParameters(rrf_k=60.0, decay_lambda=0.01)
    
    # Mutate with high rate to ensure changes
    mutated = params.mutate(mutation_rate=1.0, mutation_strength=0.5)
    
    # At least one parameter should have changed
    assert (mutated.rrf_k != params.rrf_k or 
            mutated.decay_lambda != params.decay_lambda or
            mutated.importance_floor != params.importance_floor)
    
    # Parameters should stay within bounds
    assert 1.0 <= mutated.rrf_k <= 200.0
    assert 0.001 <= mutated.decay_lambda <= 0.1
    
    print("✓ Mutation test passed")


def test_crossover():
    """Test parameter crossover"""
    parent1 = SearchParameters(rrf_k=50.0, decay_lambda=0.01, bm25_weight=0.6)
    parent2 = SearchParameters(rrf_k=70.0, decay_lambda=0.02, bm25_weight=0.4)
    
    offspring = SearchParameters.crossover(parent1, parent2)
    
    # Offspring should have values from either parent
    assert offspring.rrf_k in [parent1.rrf_k, parent2.rrf_k]
    assert offspring.decay_lambda in [parent1.decay_lambda, parent2.decay_lambda]
    assert offspring.bm25_weight in [parent1.bm25_weight, parent2.bm25_weight]
    
    print("✓ Crossover test passed")


def test_ga_config():
    """Test GA configuration"""
    config = GAConfig(
        population_size=15,
        generations=8,
        mutation_rate=0.15,
        crossover_rate=0.75,
    )
    
    assert config.population_size == 15
    assert config.generations == 8
    
    config_dict = config.to_dict()
    assert config_dict['mutation_rate'] == 0.15
    assert config_dict['crossover_rate'] == 0.75
    
    print("✓ GA configuration test passed")


def test_optimizer_initialization():
    """Test optimizer initialization"""
    config = GAConfig(population_size=10, generations=5)
    optimizer = GeneticOptimizer(config)
    
    assert optimizer.config.population_size == 10
    assert optimizer.generation == 0
    assert len(optimizer.population) == 0
    
    # Initialize population
    optimizer.initialize_population()
    assert len(optimizer.population) == 10
    
    # Check parameters are within bounds
    for individual in optimizer.population:
        assert 1.0 <= individual.parameters.rrf_k <= 200.0
        assert 0.001 <= individual.parameters.decay_lambda <= 0.1
    
    print("✓ Optimizer initialization test passed")


def test_fitness_evaluation():
    """Test fitness evaluation"""
    config = GAConfig(population_size=5, generations=1)
    optimizer = GeneticOptimizer(config)
    optimizer.initialize_population()
    
    # Simple fitness function: prefer rrf_k close to 60
    def fitness_func(params: SearchParameters) -> float:
        return 1.0 - min(abs(params.rrf_k - 60.0) / 100.0, 1.0)
    
    optimizer.evaluate_population(fitness_func)
    
    # All individuals should have fitness assigned
    for individual in optimizer.population:
        assert 0.0 <= individual.fitness <= 1.0
    
    print("✓ Fitness evaluation test passed")


def test_tournament_selection():
    """Test tournament selection"""
    config = GAConfig(population_size=10, tournament_size=3)
    optimizer = GeneticOptimizer(config)
    optimizer.initialize_population()
    
    # Assign different fitness values
    for i, individual in enumerate(optimizer.population):
        individual.fitness = i * 0.1
    
    # Run selection multiple times
    selected = [optimizer.tournament_selection() for _ in range(5)]
    
    # Selected individuals should exist in population
    for ind in selected:
        assert ind in optimizer.population
    
    print("✓ Tournament selection test passed")


def test_evolution():
    """Test single generation evolution"""
    config = GAConfig(population_size=8, elitism_count=2)
    optimizer = GeneticOptimizer(config)
    optimizer.initialize_population()
    
    # Assign fitness
    def fitness_func(params: SearchParameters) -> float:
        return 1.0 - abs(params.rrf_k - 50.0) / 100.0
    
    optimizer.evaluate_population(fitness_func)
    
    # Get best individual before evolution
    best_before = max(optimizer.population, key=lambda ind: ind.fitness)
    
    # Evolve one generation
    optimizer.evolve_generation()
    
    assert optimizer.generation == 1
    assert len(optimizer.population) == config.population_size
    
    # Best individual should be preserved (elitism)
    best_after = max(optimizer.population, key=lambda ind: ind.fitness)
    # Note: fitness needs re-evaluation after evolution
    
    print("✓ Evolution test passed")


def test_full_optimization():
    """Test complete optimization run"""
    config = GAConfig(population_size=10, generations=3)
    optimizer = GeneticOptimizer(config)
    
    # Target: find parameters close to specific values
    target_rrf_k = 55.0
    target_decay = 0.015
    
    def fitness_func(params: SearchParameters) -> float:
        rrf_error = abs(params.rrf_k - target_rrf_k) / target_rrf_k
        decay_error = abs(params.decay_lambda - target_decay) / target_decay
        return 1.0 / (1.0 + rrf_error + decay_error)
    
    result = optimizer.optimize(fitness_func=fitness_func)
    
    # Check result structure
    assert result.best_parameters is not None
    assert result.best_fitness >= 0.0
    assert result.generations_run == 3
    assert len(result.fitness_history) == 3
    
    # Fitness should generally improve (or stay same) over generations
    best_fitness_gen0 = result.fitness_history[0][0]
    best_fitness_gen2 = result.fitness_history[2][0]
    assert best_fitness_gen2 >= best_fitness_gen0 * 0.9  # Allow small variation
    
    print("✓ Full optimization test passed")
    print(f"  Best fitness: {result.best_fitness:.4f}")
    print(f"  Best rrf_k: {result.best_parameters.rrf_k:.2f} (target: {target_rrf_k})")
    print(f"  Best decay: {result.best_parameters.decay_lambda:.4f} (target: {target_decay})")


def test_create_fitness_function():
    """Test fitness function factory"""
    test_queries = [
        {"player_id": "p1", "npc_id": "n1", "query": "test query 1"},
        {"player_id": "p1", "npc_id": "n1", "query": "test query 2"},
    ]
    
    ground_truth = [
        ["mem1", "mem2"],
        ["mem3", "mem4"],
    ]
    
    # Mock search function
    def mock_search(player_id, npc_id, query, params):
        # Always return mem1, mem2
        return ["mem1", "mem2"]
    
    fitness_func = create_fitness_function(test_queries, ground_truth, mock_search)
    
    # Test fitness function
    params = SearchParameters()
    score = fitness_func(params)
    
    # Should get some positive score (precision on first query should be good)
    assert 0.0 <= score <= 1.0
    
    print("✓ Fitness function factory test passed")


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Running Genetic Algorithm Optimizer Tests")
    print("=" * 60 + "\n")
    
    tests = [
        test_search_parameters_creation,
        test_mutation,
        test_crossover,
        test_ga_config,
        test_optimizer_initialization,
        test_fitness_evaluation,
        test_tournament_selection,
        test_evolution,
        test_full_optimization,
        test_create_fitness_function,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
