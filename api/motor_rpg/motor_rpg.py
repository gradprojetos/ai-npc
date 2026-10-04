import random
import logging
from typing import Any

from api.schemas.rpg import (
    HeroState,
    MonsterState,
)

logger = logging.getLogger(__name__)


class AttackResult(dict):
    """Resultado determinístico de combate (dicionário com acesso a atributos)."""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

# Catálogo oficial dos 5 Heróis de Hesiod
HERO_ARCHETYPES: dict[str, dict[str, Any]] = {
    "jorick": {
        "name": "Jorick",
        "class_name": "Guerreiro Humano",
        "ac": 13,
        "hp": 5,
        "max_hp": 5,
        "attack_bonus": 4,
        "attack_name": "Espada Larga",
        "special_power": "Investida (+2 no ataque ao começar longe do monstro)",
    },
    "raen": {
        "name": "Raen",
        "class_name": "Bárbara Anã",
        "ac": 9,
        "hp": 7,
        "max_hp": 7,
        "attack_bonus": 5,
        "attack_name": "Machado Pesado",
        "special_power": "Guerreira Feroz (Empurra o monstro 2 casas ao ser atingida)",
    },
    "bet": {
        "name": "Bet",
        "class_name": "Maga Elfa",
        "ac": 7,
        "hp": 4,
        "max_hp": 4,
        "attack_bonus": 7,
        "attack_name": "Bola de Fogo",
        "special_power": "Onda Explosiva (Dano em área atingindo criaturas adjacentes)",
    },
    "evindol": {
        "name": "Evindol",
        "class_name": "Ladino Humano",
        "ac": 11,
        "hp": 3,
        "max_hp": 3,
        "attack_bonus": 6,
        "attack_name": "Lâminas Giratórias",
        "special_power": "Ataque Furtivo (Causa dano dobrado - 2 - se flanquear)",
    },
    "yarrow": {
        "name": "Yarrow",
        "class_name": "Xamã Meio-Orc",
        "ac": 10,
        "hp": 6,
        "max_hp": 6,
        "attack_bonus": 3,
        "attack_name": "Espíritos Vingativos",
        "special_power": "Grilhões Espectrais (Prende o monstro ao solo se errar o ataque)",
    },
}

# Catálogo dos Monstros das 4 Jaulas
CAGE_MONSTERS: dict[int, dict[str, Any]] = {
    1: {
        "name": "Bullette Faminto",
        "cage_number": 1,
        "ac": 15,
        "hp": 8,
        "max_hp": 8,
        "attack_bonus": 4,
        "attack_name": "Escavar e Engolir",
        "abilities": [
            "Escava o solo e tenta engolir o herói",
            "Dano corrosivo de ácido estomacal",
        ],
    },
    2: {
        "name": "Beholder Ameaçador",
        "cage_number": 2,
        "ac": 12,
        "hp": 11,
        "max_hp": 11,
        "attack_bonus": 4,
        "attack_name": "Raios Oculares e Mordida",
        "abilities": [
            "Flutuação aérea constante",
            "Disparo de raios oculares múltiplos",
            "Mordida voraz",
        ],
    },
    3: {
        "name": "Dragão Vermelho Jovem",
        "cage_number": 3,
        "ac": 14,
        "hp": 10,
        "max_hp": 10,
        "attack_bonus": 5,
        "attack_name": "Sopro de Fogo",
        "abilities": [
            "Sopro de chamas em cone",
            "Mordida flamejante",
        ],
    },
    4: {
        "name": "Enxame de Pixies Ferais",
        "cage_number": 4,
        "ac": 10,
        "hp": 11,
        "max_hp": 11,
        "attack_bonus": 3,
        "attack_name": "Enxame Elétrico",
        "abilities": [
            "Diminutas e velozes",
            "Ataque em bando coordenado",
            "Descarga de estática mágica",
        ],
    },
}


def roll_dice(sides: int = 20) -> int:
    """Rola um dado de N faces."""
    return random.randint(1, sides)


def create_hero(archetype_or_name: str, player_id: str = "player_1") -> HeroState:
    """Cria uma instância de HeroState a partir de um arquétipo válido."""
    key = archetype_or_name.strip().lower()
    data = HERO_ARCHETYPES.get(key)
    if not data:
        # Busca parcial ou fallback para Jorick
        for arch_key, arch_data in HERO_ARCHETYPES.items():
            if key in arch_key or key in arch_data["class_name"].lower():
                data = arch_data
                break
    if not data:
        data = HERO_ARCHETYPES["jorick"]

    return HeroState(
        player_id=player_id,
        name=data["name"],
        class_name=data["class_name"],
        hp=data["hp"],
        max_hp=data["max_hp"],
        ac=data["ac"],
        attack_bonus=data["attack_bonus"],
        attack_name=data["attack_name"],
        special_power=data["special_power"],
    )


def get_cage_monster(cage_number: int) -> MonsterState:
    """Retorna uma nova instância do monstro correspondente à jaula informada (1 a 4)."""
    data = CAGE_MONSTERS.get(cage_number)
    if not data:
        raise ValueError(f"Jaula {cage_number} não existe. Válidas: 1 a 4.")
    return MonsterState(
        name=data["name"],
        hp=data["hp"],
        max_hp=data["max_hp"],
        ac=data["ac"],
        is_defeated=False,
        cage_number=cage_number,
        attack_bonus=data["attack_bonus"],
        attack_name=data["attack_name"],
        abilities=list(data["abilities"]),
    )


def resolve_hero_attack(
    hero: HeroState,
    monster: MonsterState,
    d20: int | None = None,
    forced_damage: int | None = None,
) -> AttackResult:
    """Executa a resolução simples e determinística do ataque do herói."""
    d20_roll = d20 if d20 is not None else roll_dice(20)
    bonus = hero.attack_bonus
    total_attack = d20_roll + bonus
    is_critical = (d20_roll == 20)
    is_hit = is_critical or (total_attack >= monster.ac)
    hp_before = monster.hp
    damage = 0

    if is_hit:
        damage = (forced_damage if forced_damage is not None else roll_dice(6)) if is_critical else 1
        monster.take_damage(damage)

    narrative = (
        f"{hero.name} atacou {monster.name} com {hero.attack_name} "
        f"(d20={d20_roll} + bônus={bonus} = {total_attack} vs CA {monster.ac}). "
        f"{'ACERTOU!' if is_hit else 'ERROU!'} "
        + (f"Dano: {damage} (HP: {hp_before} -> {monster.hp})." if is_hit else "")
    )

    return AttackResult(
        attacker_name=hero.name,
        defender_name=monster.name,
        d20_roll=d20_roll,
        attack_bonus=bonus,
        total_attack=total_attack,
        target_ac=monster.ac,
        is_hit=is_hit,
        is_critical=is_critical,
        damage_dealt=damage,
        defender_hp_before=hp_before,
        defender_hp_after=monster.hp,
        defender_defeated=monster.is_defeated,
        narrative_summary=narrative.strip(),
    )


def resolve_monster_attack(
    monster: MonsterState,
    hero: HeroState,
    d20: int | None = None,
    forced_damage: int | None = None,
) -> AttackResult:
    """Executa a resolução simples e determinística do ataque do monstro."""
    d20_roll = d20 if d20 is not None else roll_dice(20)
    bonus = monster.attack_bonus
    total_attack = d20_roll + bonus
    is_critical = (d20_roll == 20)
    is_hit = is_critical or (total_attack >= hero.ac)
    hp_before = hero.hp
    damage = 0

    if is_hit:
        damage = (forced_damage if forced_damage is not None else roll_dice(6)) if is_critical else 1
        hero.take_damage(damage)

    narrative = (
        f"{monster.name} atacou {hero.name} com {monster.attack_name} "
        f"(d20={d20_roll} + bônus={bonus} = {total_attack} vs CA {hero.ac}). "
        f"{'ACERTOU!' if is_hit else 'ERROU!'} "
        + (f"Dano: {damage} (HP: {hp_before} -> {hero.hp})." if is_hit else "")
    )

    return AttackResult(
        attacker_name=monster.name,
        defender_name=hero.name,
        d20_roll=d20_roll,
        attack_bonus=bonus,
        total_attack=total_attack,
        target_ac=hero.ac,
        is_hit=is_hit,
        is_critical=is_critical,
        damage_dealt=damage,
        defender_hp_before=hp_before,
        defender_hp_after=hero.hp,
        defender_defeated=hero.is_unconscious,
        hero_unconscious=hero.is_unconscious,
        narrative_summary=narrative.strip(),
    )
