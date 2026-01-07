"""
Genetic Algorithm Optimizer for NPC Memory RAG System

This module implements genetic algorithms to optimize search parameters
such as RRF fusion weights, memory decay rates, and importance thresholds.
"""

import random
from typing import List, Tuple, Dict, Any, Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SearchParameters:
    """Search parameters that can be optimized by genetic algorithm"""
    rrf_k: float = 60.0  # RRF fusion k parameter
    decay_lambda: float = 0.01  # Memory decay rate
    importance_floor: float = 0.2  # Minimum importance weight
    type_mismatch_penalty: float = 0.35  # Penalty for type mismatch
    bm25_weight: float = 0.5  # BM25 contribution weight
    vector_weight: float = 0.5  # Vector contribution weight
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary"""
        return {
            'rrf_k': self.rrf_k,
            'decay_lambda': self.decay_lambda,
            'importance_floor': self.importance_floor,
            'type_mismatch_penalty': self.type_mismatch_penalty,
            'bm25_weight': self.bm25_weight,
            'vector_weight': self.vector_weight,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> 'SearchParameters':
        """Create from dictionary"""
        return cls(
            rrf_k=data.get('rrf_k', 60.0),
            decay_lambda=data.get('decay_lambda', 0.01),
            importance_floor=data.get('importance_floor', 0.2),
            type_mismatch_penalty=data.get('type_mismatch_penalty', 0.35),
            bm25_weight=data.get('bm25_weight', 0.5),
            vector_weight=data.get('vector_weight', 0.5),
        )
    
    def mutate(self, mutation_rate: float = 0.1, mutation_strength: float = 0.2) -> 'SearchParameters':
        """
        Apply mutation to parameters
        
        Args:
            mutation_rate: Probability of mutating each parameter
            mutation_strength: Maximum relative change (0.2 = ±20%)
        
        Returns:
            Mutated parameters
        """
        def mutate_value(value: float, min_val: float, max_val: float) -> float:
            if random.random() < mutation_rate:
                delta = random.uniform(-mutation_strength, mutation_strength) * value
                return max(min_val, min(max_val, value + delta))
            return value
        
        return SearchParameters(
            rrf_k=mutate_value(self.rrf_k, 1.0, 200.0),
            decay_lambda=mutate_value(self.decay_lambda, 0.001, 0.1),
            importance_floor=mutate_value(self.importance_floor, 0.0, 0.5),
            type_mismatch_penalty=mutate_value(self.type_mismatch_penalty, 0.1, 0.9),
            bm25_weight=mutate_value(self.bm25_weight, 0.0, 1.0),
            vector_weight=mutate_value(self.vector_weight, 0.0, 1.0),
        )
    
    @staticmethod
    def crossover(parent1: 'SearchParameters', parent2: 'SearchParameters') -> 'SearchParameters':
        """
        Perform uniform crossover between two parameter sets
        
        Args:
            parent1: First parent parameters
            parent2: Second parent parameters
        
        Returns:
            Offspring parameters
        """
        return SearchParameters(
            rrf_k=random.choice([parent1.rrf_k, parent2.rrf_k]),
            decay_lambda=random.choice([parent1.decay_lambda, parent2.decay_lambda]),
            importance_floor=random.choice([parent1.importance_floor, parent2.importance_floor]),
            type_mismatch_penalty=random.choice([parent1.type_mismatch_penalty, parent2.type_mismatch_penalty]),
            bm25_weight=random.choice([parent1.bm25_weight, parent2.bm25_weight]),
            vector_weight=random.choice([parent1.vector_weight, parent2.vector_weight]),
        )


@dataclass
class Individual:
    """Individual in genetic algorithm population"""
    parameters: SearchParameters
    fitness: float = 0.0
    generation: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'parameters': self.parameters.to_dict(),
            'fitness': self.fitness,
            'generation': self.generation,
        }


@dataclass
class GAConfig:
    """Genetic algorithm configuration"""
    population_size: int = 20
    generations: int = 10
    mutation_rate: float = 0.1
    mutation_strength: float = 0.2
    crossover_rate: float = 0.7
    elitism_count: int = 2  # Number of top individuals to preserve
    tournament_size: int = 3  # For tournament selection
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'population_size': self.population_size,
            'generations': self.generations,
            'mutation_rate': self.mutation_rate,
            'mutation_strength': self.mutation_strength,
            'crossover_rate': self.crossover_rate,
            'elitism_count': self.elitism_count,
            'tournament_size': self.tournament_size,
        }


@dataclass
class OptimizationResult:
    """Result of genetic algorithm optimization"""
    best_parameters: SearchParameters
    best_fitness: float
    generations_run: int
    population_history: List[List[Individual]] = field(default_factory=list)
    fitness_history: List[Tuple[float, float, float]] = field(default_factory=list)  # (best, avg, worst)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (without full history to keep size small)"""
        return {
            'best_parameters': self.best_parameters.to_dict(),
            'best_fitness': self.best_fitness,
            'generations_run': self.generations_run,
            'fitness_history': self.fitness_history,
            'timestamp': self.timestamp,
        }


class GeneticOptimizer:
    """
    Genetic Algorithm optimizer for search parameters
    
    Uses genetic algorithm to optimize search parameters by evaluating
    search quality against a fitness function.
    """
    
    def __init__(self, config: GAConfig = None):
        """
        Initialize genetic optimizer
        
        Args:
            config: GA configuration (uses defaults if None)
        """
        self.config = config or GAConfig()
        self.population: List[Individual] = []
        self.generation = 0
        
    def initialize_population(self) -> None:
        """Initialize random population"""
        self.population = []
        for _ in range(self.config.population_size):
            # Create random parameters within reasonable bounds
            params = SearchParameters(
                rrf_k=random.uniform(20.0, 100.0),
                decay_lambda=random.uniform(0.005, 0.05),
                importance_floor=random.uniform(0.1, 0.4),
                type_mismatch_penalty=random.uniform(0.2, 0.6),
                bm25_weight=random.uniform(0.3, 0.7),
                vector_weight=random.uniform(0.3, 0.7),
            )
            self.population.append(Individual(parameters=params, generation=0))
    
    def evaluate_population(self, fitness_func: Callable[[SearchParameters], float]) -> None:
        """
        Evaluate fitness for all individuals in population
        
        Args:
            fitness_func: Function that takes SearchParameters and returns fitness score
        """
        for individual in self.population:
            individual.fitness = fitness_func(individual.parameters)
    
    def tournament_selection(self) -> Individual:
        """
        Select individual using tournament selection
        
        Returns:
            Selected individual
        """
        tournament = random.sample(self.population, self.config.tournament_size)
        return max(tournament, key=lambda ind: ind.fitness)
    
    def crossover(self, parent1: Individual, parent2: Individual) -> Individual:
        """
        Perform crossover between two parents
        
        Args:
            parent1: First parent
            parent2: Second parent
        
        Returns:
            Offspring individual
        """
        if random.random() < self.config.crossover_rate:
            offspring_params = SearchParameters.crossover(parent1.parameters, parent2.parameters)
        else:
            # No crossover, clone one parent
            offspring_params = parent1.parameters
        
        return Individual(parameters=offspring_params, generation=self.generation)
    
    def mutate(self, individual: Individual) -> Individual:
        """
        Apply mutation to individual
        
        Args:
            individual: Individual to mutate
        
        Returns:
            Mutated individual
        """
        mutated_params = individual.parameters.mutate(
            self.config.mutation_rate,
            self.config.mutation_strength
        )
        return Individual(parameters=mutated_params, generation=self.generation)
    
    def evolve_generation(self) -> None:
        """Evolve population by one generation"""
        # Sort by fitness (descending)
        self.population.sort(key=lambda ind: ind.fitness, reverse=True)
        
        # Preserve elite individuals
        new_population = self.population[:self.config.elitism_count]
        
        # Generate offspring to fill remaining population
        while len(new_population) < self.config.population_size:
            # Select parents
            parent1 = self.tournament_selection()
            parent2 = self.tournament_selection()
            
            # Create offspring
            offspring = self.crossover(parent1, parent2)
            offspring = self.mutate(offspring)
            
            new_population.append(offspring)
        
        self.population = new_population
        self.generation += 1
    
    def optimize(
        self,
        fitness_func: Callable[[SearchParameters], float],
        generations: int = None,
        initial_population: List[SearchParameters] = None
    ) -> OptimizationResult:
        """
        Run genetic algorithm optimization
        
        Args:
            fitness_func: Function that evaluates search parameters
            generations: Number of generations (uses config if None)
            initial_population: Optional initial population
        
        Returns:
            Optimization result with best parameters
        """
        generations = generations or self.config.generations
        
        # Initialize population
        if initial_population:
            self.population = [
                Individual(parameters=params, generation=0)
                for params in initial_population
            ]
            # Fill remaining slots if initial population is smaller than config
            while len(self.population) < self.config.population_size:
                params = SearchParameters(
                    rrf_k=random.uniform(20.0, 100.0),
                    decay_lambda=random.uniform(0.005, 0.05),
                    importance_floor=random.uniform(0.1, 0.4),
                    type_mismatch_penalty=random.uniform(0.2, 0.6),
                    bm25_weight=random.uniform(0.3, 0.7),
                    vector_weight=random.uniform(0.3, 0.7),
                )
                self.population.append(Individual(parameters=params, generation=0))
        else:
            self.initialize_population()
        
        self.generation = 0
        
        # Track history
        population_history = []
        fitness_history = []
        
        # Run evolution
        for gen in range(generations):
            # Evaluate fitness
            self.evaluate_population(fitness_func)
            
            # Record statistics
            fitnesses = [ind.fitness for ind in self.population]
            best_fitness = max(fitnesses)
            avg_fitness = sum(fitnesses) / len(fitnesses)
            worst_fitness = min(fitnesses)
            
            fitness_history.append((best_fitness, avg_fitness, worst_fitness))
            population_history.append([Individual(
                parameters=ind.parameters,
                fitness=ind.fitness,
                generation=ind.generation
            ) for ind in self.population])
            
            # Evolve to next generation (except for last generation)
            if gen < generations - 1:
                self.evolve_generation()
        
        # Final evaluation
        self.evaluate_population(fitness_func)
        self.population.sort(key=lambda ind: ind.fitness, reverse=True)
        
        best_individual = self.population[0]
        
        return OptimizationResult(
            best_parameters=best_individual.parameters,
            best_fitness=best_individual.fitness,
            generations_run=generations,
            population_history=population_history,
            fitness_history=fitness_history,
        )
    
    def get_population_stats(self) -> Dict[str, Any]:
        """Get current population statistics"""
        if not self.population:
            return {}
        
        fitnesses = [ind.fitness for ind in self.population]
        return {
            'generation': self.generation,
            'population_size': len(self.population),
            'best_fitness': max(fitnesses),
            'avg_fitness': sum(fitnesses) / len(fitnesses),
            'worst_fitness': min(fitnesses),
            'best_parameters': max(self.population, key=lambda ind: ind.fitness).parameters.to_dict(),
        }


def create_fitness_function(
    test_queries: List[Dict[str, Any]],
    ground_truth: List[List[str]],
    search_func: Callable[[str, str, str, SearchParameters], List[str]]
) -> Callable[[SearchParameters], float]:
    """
    Create a fitness function for evaluating search parameters
    
    Args:
        test_queries: List of test queries with 'player_id', 'npc_id', 'query'
        ground_truth: List of expected memory IDs for each query
        search_func: Function that performs search with given parameters
    
    Returns:
        Fitness function that returns score between 0 and 1
    """
    def fitness(params: SearchParameters) -> float:
        """Evaluate search parameters using precision@k"""
        if not test_queries:
            return 0.0
        
        total_precision = 0.0
        for i, query in enumerate(test_queries):
            # Perform search with these parameters
            results = search_func(
                query['player_id'],
                query['npc_id'],
                query['query'],
                params
            )
            
            # Calculate precision@k
            if i < len(ground_truth):
                expected = set(ground_truth[i])
                if expected and results:
                    k = min(len(results), len(expected))
                    relevant_found = len(set(results[:k]) & expected)
                    precision = relevant_found / k if k > 0 else 0.0
                    total_precision += precision
        
        return total_precision / len(test_queries)
    
    return fitness
