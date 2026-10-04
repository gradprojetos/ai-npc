from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class HeroArchetype(str, Enum):
    JORICK = "Jorick"
    RAEN = "Raen"
    BET = "Bet"
    EVINDOL = "Evindol"
    YARROW = "Yarrow"


class ActionResult(BaseModel):
    attacker_name: str
    defender_name: str
    action_type: str = "atacar"
    d20_roll: int
    attack_bonus: int
    total_attack: int
    target_ac: int
    is_hit: bool
    is_critical: bool
    damage_dealt: int
    defender_hp_before: int
    defender_hp_after: int
    defender_defeated: bool = False
    special_effect_applied: str | None = None
    loomis_cage_unlocked: int | None = None
    loomis_potion_used: bool = False
    is_victory: bool = False
    narrative_summary: str = ""


class Message(BaseModel):
    sender: str
    content: str
    role: Literal["user", "assistant", "system"]
    timestamp: str | None = None


class HeroState(BaseModel):
    player_id: str
    name: str
    class_name: str
    hp: int
    max_hp: int
    ac: int
    attack_bonus: int = 4
    attack_name: str = "Ataque Básico"
    special_power: str = ""


class MonsterState(BaseModel):
    name: str
    cage_number: int = 1
    hp: int
    max_hp: int
    ac: int
    attack_bonus: int = 4
    attack_name: str = "Ataque da Criatura"
    abilities: list[str] = Field(default_factory=list)
    is_defeated: bool = False


class NPCState(BaseModel):
    name: str = "Loomis"
    system_prompt: str = ""


class GameState(BaseModel):
    session_id: str
    location: str = "Clareira de Treino em Hesiod"

    players: list[HeroState] = Field(default_factory=list)
    monsters: list[MonsterState] = Field(default_factory=list)
    npcs: list[NPCState] = Field(default_factory=lambda: [NPCState()])

    last_context: str | None = None
    recent_messages: list[Message] = Field(default_factory=list)
    is_victory: bool = False

    @property
    def messages(self) -> list[Message]:
        return self.recent_messages

    @messages.setter
    def messages(self, val: list[Message]) -> None:
        self.recent_messages = val


RPGGraphState = GameState
