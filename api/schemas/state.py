from datetime import datetime
from pydantic import BaseModel
from uuid import UUID as uuid
from typing import Literal

class Message(BaseModel):
    sender: str # "Jorrick", "Loomis", "System"         
    content: str                                     
    timestamp: datetime | None = None
    role: Literal["user", "assistant", "system"] = "user"  

class NPCState(BaseModel):
    name: str = "Loomis"
    role: str = "Treinador de Hesiod"

class HeroState(BaseModel):
    player_id: uuid
    name: str
    class_name: str
    hp: int
    max_hp: int
    ac: int

class MonsterState(BaseModel):
    name: str
    description: str
    hp: int
    max_hp: int
    ac: int
    is_defeated: bool

class GameState(BaseModel):
    session_id: uuid
    location: str
    players: list[HeroState]
    # game_mode: Literal["combat", "dialogue"] - player's current intent
    messages: list[Message]
    current_turn: int
    npcs: list[NPCState]
    monsters: list[MonsterState]
