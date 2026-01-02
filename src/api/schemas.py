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
    task_id: str = Field(..., description="Async task ID for tracking")
    status: str = Field("queued", description="Task status")
    message: str = Field("Memory queued for indexing", description="Status message")


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
