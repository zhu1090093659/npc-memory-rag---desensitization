"""
Pydantic schemas for API request/response models
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class MemoryTypeEnum(str, Enum):
    """Memory type enumeration"""
    dialogue = "dialogue"
    quest = "quest"
    trade = "trade"
    gift = "gift"
    combat = "combat"
    emotion = "emotion"


class MemoryCreateRequest(BaseModel):
    """Request model for creating a new memory"""
    player_id: str = Field(..., min_length=1, description="Player ID")
    npc_id: str = Field(..., min_length=1, description="NPC ID")
    memory_type: MemoryTypeEnum = Field(..., description="Type of memory")
    content: str = Field(..., min_length=1, max_length=2000, description="Memory content")
    importance: float = Field(0.5, ge=0, le=1, description="Importance score [0, 1]")
    emotion_tags: List[str] = Field(default_factory=list, description="Emotion tags")
    game_context: Dict[str, Any] = Field(default_factory=dict, description="Game context metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "player_id": "player_123",
                "npc_id": "blacksmith_01",
                "memory_type": "quest",
                "content": "玩家帮助铁匠找回了被盗的祖传锤子",
                "importance": 0.8,
                "emotion_tags": ["感谢", "信任"],
                "game_context": {"location": "village_01", "quest_id": "find_hammer"}
            }
        }


class MemoryCreateResponse(BaseModel):
    """Response model for memory creation"""
    task_id: str = Field(..., description="Task ID (correlation ID)")
    memory_id: str = Field(..., description="Indexed memory ID")
    status: str = Field("completed", description="Processing status")
    message: str = Field("Memory indexed", description="Status message")


class MemoryResponse(BaseModel):
    """Response model for a single memory"""
    id: str
    player_id: str
    npc_id: str
    memory_type: str
    content: str
    importance: float
    emotion_tags: List[str]
    timestamp: Optional[datetime]
    game_context: Dict[str, Any]


class SearchResponse(BaseModel):
    """Response model for search results"""
    memories: List[MemoryResponse]
    total: int
    query_time_ms: float

    class Config:
        json_schema_extra = {
            "example": {
                "memories": [
                    {
                        "id": "mem_001",
                        "player_id": "player_123",
                        "npc_id": "blacksmith_01",
                        "memory_type": "quest",
                        "content": "玩家帮助铁匠找回了祖传锤子",
                        "importance": 0.72,
                        "emotion_tags": ["感谢", "信任"],
                        "timestamp": "2024-01-15T10:30:00",
                        "game_context": {"location": "village_01"}
                    }
                ],
                "total": 1,
                "query_time_ms": 45.2
            }
        }


class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str


class ContextResponse(BaseModel):
    """Response model for LLM context preparation"""
    memories: List[MemoryResponse]
    summary: str
    total_interactions: int
    last_interaction: Optional[datetime]
    relationship_score: float


class SearchParametersSchema(BaseModel):
    """Schema for search parameters that can be optimized"""
    rrf_k: float = Field(60.0, description="RRF fusion k parameter")
    decay_lambda: float = Field(0.01, description="Memory decay rate")
    importance_floor: float = Field(0.2, description="Minimum importance weight")
    type_mismatch_penalty: float = Field(0.35, description="Penalty for type mismatch")
    bm25_weight: float = Field(0.5, description="BM25 contribution weight")
    vector_weight: float = Field(0.5, description="Vector contribution weight")

    class Config:
        json_schema_extra = {
            "example": {
                "rrf_k": 60.0,
                "decay_lambda": 0.01,
                "importance_floor": 0.2,
                "type_mismatch_penalty": 0.35,
                "bm25_weight": 0.5,
                "vector_weight": 0.5
            }
        }


class GAConfigSchema(BaseModel):
    """Schema for genetic algorithm configuration"""
    population_size: int = Field(20, ge=5, le=100, description="Population size")
    generations: int = Field(10, ge=1, le=100, description="Number of generations")
    mutation_rate: float = Field(0.1, ge=0.0, le=1.0, description="Mutation probability")
    mutation_strength: float = Field(0.2, ge=0.0, le=1.0, description="Mutation strength")
    crossover_rate: float = Field(0.7, ge=0.0, le=1.0, description="Crossover probability")
    elitism_count: int = Field(2, ge=0, le=10, description="Elite individuals to preserve")
    tournament_size: int = Field(3, ge=2, le=10, description="Tournament selection size")

    class Config:
        json_schema_extra = {
            "example": {
                "population_size": 20,
                "generations": 10,
                "mutation_rate": 0.1,
                "mutation_strength": 0.2,
                "crossover_rate": 0.7,
                "elitism_count": 2,
                "tournament_size": 3
            }
        }


class OptimizationRequest(BaseModel):
    """Request model for GA optimization"""
    test_queries: List[Dict[str, Any]] = Field(
        ..., 
        description="Test queries with player_id, npc_id, query fields"
    )
    ground_truth: List[List[str]] = Field(
        ..., 
        description="Expected memory IDs for each test query"
    )
    ga_config: Optional[GAConfigSchema] = Field(
        None, 
        description="GA configuration (uses defaults if not provided)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "test_queries": [
                    {"player_id": "p1", "npc_id": "n1", "query": "找回丢失的剑"},
                    {"player_id": "p1", "npc_id": "n1", "query": "昨天的对话"}
                ],
                "ground_truth": [
                    ["mem1", "mem2", "mem3"],
                    ["mem4", "mem5"]
                ],
                "ga_config": {
                    "population_size": 15,
                    "generations": 8
                }
            }
        }


class OptimizationResponse(BaseModel):
    """Response model for GA optimization"""
    best_parameters: SearchParametersSchema
    best_fitness: float
    generations_run: int
    fitness_history: List[Tuple[float, float, float]] = Field(
        ..., 
        description="Fitness history per generation: [(best, avg, worst), ...]"
    )
    timestamp: str

    class Config:
        json_schema_extra = {
            "example": {
                "best_parameters": {
                    "rrf_k": 55.3,
                    "decay_lambda": 0.012,
                    "importance_floor": 0.18,
                    "type_mismatch_penalty": 0.32,
                    "bm25_weight": 0.52,
                    "vector_weight": 0.48
                },
                "best_fitness": 0.85,
                "generations_run": 10,
                "fitness_history": [(0.65, 0.45, 0.25), (0.75, 0.55, 0.35)],
                "timestamp": "2026-01-07T15:00:00"
            }
        }
