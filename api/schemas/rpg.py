from typing import Literal
from pydantic import BaseModel, Field


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

    def restore_full_hp(self) -> None:
        """Restaura os pontos de vida do herói ao valor máximo."""
        self.hp = self.max_hp

    def take_damage(self, amount: int) -> int:
        """Aplica dano ao herói. Se o HP chegar a zero, o herói cai inconsciente."""
        self.hp = max(0, self.hp - amount)
        return amount

    @property
    def is_unconscious(self) -> bool:
        """Indica se o herói caiu inconsciente (HP == 0)."""
        return self.hp == 0


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

    def take_damage(self, amount: int) -> int:
        """Aplica dano ao monstro e atualiza is_defeated se a vida zerar."""
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.is_defeated = True
        return amount

    @property
    def is_half_hp_or_less(self) -> bool:
        """Verifica se o monstro atingiu 50% de HP ou menos (gatilho de Loomis)."""
        return 0 < self.hp <= (self.max_hp / 2.0)


class NPCState(BaseModel):
    name: str = "Loomis"
    system_prompt: str = ""

    def heal(self, target: HeroState) -> None:
        """NPC administra poção ou cura um herói, restaurando seu HP máximo."""
        target.restore_full_hp()


class GameState(BaseModel):
    session_id: str
    location: str = "Clareira de Treino em Hesiod"

    players: list[HeroState] = Field(default_factory=list)
    monsters: list[MonsterState] = Field(default_factory=list)
    npcs: list[NPCState] = Field(default_factory=lambda: [NPCState()])

    last_context: str | None = None
    recent_messages: list[Message] = Field(default_factory=list)
    is_victory: bool = False

    def rotate_players(self) -> HeroState | None:
        """Rotaciona a fila de iniciativa: o jogador ativo vai para o fim da fila."""
        if self.players:
            self.players.append(self.players.pop(0))
            return self.players[0]
        return None
