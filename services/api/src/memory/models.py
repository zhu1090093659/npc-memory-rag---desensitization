"""
Memory data models
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any
from enum import Enum


class MemoryType(Enum):
    """Memory type enum"""
    DIALOGUE = "dialogue"
    QUEST = "quest"
    TRADE = "trade"
    GIFT = "gift"
    COMBAT = "combat"
    EMOTION = "emotion"


@dataclass
class Memory:
    """Single memory record"""
    id: str
    player_id: str
    npc_id: str
    memory_type: MemoryType
    content: str
    content_vector: List[float] = field(default_factory=list)
    emotion_tags: List[str] = field(default_factory=list)
    importance: float = 0.5
    timestamp: datetime = field(default_factory=datetime.now)
    game_context: Dict[str, Any] = field(default_factory=dict)

    def to_es_doc(self) -> dict:
        """Convert to ES document format"""
        return {
            "_id": self.id,
            "_routing": self.npc_id,
            "player_id": self.player_id,
            "npc_id": self.npc_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "content_vector": self.content_vector,
            "emotion_tags": self.emotion_tags,
            "importance": self.importance,
            "timestamp": self.timestamp.isoformat(),
            "game_context": self.game_context
        }


@dataclass
class MemoryContext:
    """Memory context for LLM"""
    memories: List[Memory]
    summary: str
    total_interactions: int
    last_interaction: datetime = None
    relationship_score: float = 0.0
