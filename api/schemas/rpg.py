from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class HeroArchetype(str, Enum):
    JORICK = "Jorick"
    RAEN = "Raen"
    BET = "Bet"
    EVINDOL = "Evindol"
    YARROW = "Yarrow"


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
    is_unconscious: bool = False


class MonsterState(BaseModel):
    name: str
    hp: int
    max_hp: int
    ac: int
    is_defeated: bool = False
    cage_number: int = 1
    attack_bonus: int = 4
    attack_name: str = "Ataque da Criatura"
    abilities: list[str] = Field(default_factory=list)
    is_bound: bool = False
    distance: int = 0


class ActionType(str, Enum):
    ATTACK = "atacar"
    SPECIAL = "usar_poder"
    DEFEND = "defender"
    TALK = "conversar"


class ActionResult(BaseModel):
    attacker_name: str
    defender_name: str
    action_type: str
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
    role: str
    content: str
    timestamp: str | None = None


class RPGGraphState(BaseModel):
    session_id: str
    players: list[HeroState] = Field(default_factory=list)
    current_turn: str = "monster"
    current_monster: MonsterState
    active_monsters: list[MonsterState] = Field(default_factory=list)
    cage_number: int = 1
    round_number: int = 1
    history: list[Message] = Field(default_factory=list)
    current_intent: str = "conversar"
    loomis_response: str = ""
    is_victory: bool = False
