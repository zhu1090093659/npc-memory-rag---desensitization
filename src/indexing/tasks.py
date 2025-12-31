"""
Index task definition and serialization
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Any, Optional
import json
import uuid


@dataclass
class IndexTask:
    """
    Index task for async processing
    Contains dialogue/event log to be indexed
    """
    task_id: str
    player_id: str
    npc_id: str
    content: str
    memory_type: str
    timestamp: str
    importance: float = 0.5
    emotion_tags: list = None
    game_context: dict = None

    def __post_init__(self):
        """Initialize default values"""
        if self.emotion_tags is None:
            self.emotion_tags = []
        if self.game_context is None:
            self.game_context = {}

    @classmethod
    def create(
        cls,
        player_id: str,
        npc_id: str,
        content: str,
        memory_type: str,
        importance: float = 0.5,
        emotion_tags: list = None,
        game_context: dict = None,
        timestamp: datetime = None
    ) -> "IndexTask":
        """
        Factory method to create index task with auto-generated ID
        """
        task_id = str(uuid.uuid4())
        timestamp_str = (timestamp or datetime.now()).isoformat()

        return cls(
            task_id=task_id,
            player_id=player_id,
            npc_id=npc_id,
            content=content,
            memory_type=memory_type,
            timestamp=timestamp_str,
            importance=importance,
            emotion_tags=emotion_tags or [],
            game_context=game_context or {}
        )

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "IndexTask":
        """Deserialize from JSON string"""
        data = json.loads(json_str)
        return cls(**data)

    def to_memory_dict(self) -> Dict[str, Any]:
        """
        Convert to Memory-compatible dict for ES indexing
        (without vector, worker will generate it)
        """
        return {
            "id": self.task_id,
            "player_id": self.player_id,
            "npc_id": self.npc_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "importance": self.importance,
            "emotion_tags": self.emotion_tags,
            "timestamp": self.timestamp,
            "game_context": self.game_context
        }
