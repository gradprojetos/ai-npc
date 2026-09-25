import random
import logging
from typing import Any

from api.schemas.rpg import (
    HeroArchetype,
    HeroState,
    MonsterState,
    ActionResult,
    ActionType,
)

logger = logging.getLogger(__name__)

# Catálogo oficial dos 5 Heróis de Hesiod
HERO_ARCHETYPES: dict[str, dict[str, Any]] = {
    HeroArchetype.JORICK.value.lower(): {
        "name": "Jorick",
        "class_name": "Guerreiro Humano",
        "ac": 13,
        "hp": 5,
        "max_hp": 5,
        "attack_bonus": 4,
        "attack_name": "Espada Larga",
        "special_power": "Investida (+2 no ataque ao começar longe do monstro)",
    },
    HeroArchetype.RAEN.value.lower(): {
        "name": "Raen",
        "class_name": "Bárbara Anã",
        "ac": 9,
        "hp": 7,
        "max_hp": 7,
        "attack_bonus": 5,
        "attack_name": "Machado Pesado",
        "special_power": "Guerreira Feroz (Empurra o monstro 2 casas ao ser atingida)",
    },
    HeroArchetype.BET.value.lower(): {
        "name": "Bet",
        "class_name": "Maga Elfa",
        "ac": 7,
        "hp": 4,
        "max_hp": 4,
        "attack_bonus": 7,
        "attack_name": "Bola de Fogo",
        "special_power": "Onda Explosiva (Dano em área atingindo criaturas adjacentes)",
    },
    HeroArchetype.EVINDOL.value.lower(): {
        "name": "Evindol",
        "class_name": "Ladino Humano",
        "ac": 11,
        "hp": 3,
        "max_hp": 3,
        "attack_bonus": 6,
        "attack_name": "Lâminas Giratórias",
        "special_power": "Ataque Furtivo (Causa dano dobrado - 2 - se flanquear)",
    },
    HeroArchetype.YARROW.value.lower(): {
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
        data = HERO_ARCHETYPES[HeroArchetype.JORICK.value.lower()]

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
        is_unconscious=False,
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
        is_bound=False,
        distance=0,
    )


def resolve_hero_attack(
    hero: HeroState,
    monster: MonsterState,
    active_monsters_count: int = 1,
    is_far: bool = False,
    is_flanking: bool = False,
    adjacent_monsters: list[MonsterState] | None = None,
    forced_d20: int | None = None,
    forced_damage: int | None = None,
) -> ActionResult:
    """Executa a resolução determinística do ataque de um herói contra um monstro."""
    d20 = forced_d20 if forced_d20 is not None else roll_dice(20)
    bonus = hero.attack_bonus
    special_effects: list[str] = []

    # Poder Especial: Jorick (Investida)
    if hero.name == "Jorick" and (is_far or monster.distance > 0):
        bonus += 2
        monster.distance = 0
        special_effects.append("Investida (+2 no ataque por começar distante)")

    total_attack = d20 + bonus
    is_critical = d20 == 20
    is_hit = is_critical or (total_attack >= monster.ac)
    hp_before = monster.hp
    damage = 0

    if is_hit:
        if is_critical:
            crit_roll = forced_damage if forced_damage is not None else roll_dice(6)
            damage = crit_roll
            special_effects.append(f"Acerto Crítico (20 natural! Dano 1d6: {crit_roll})")
        else:
            damage = 1
            # Poder Especial: Evindol (Ataque Furtivo)
            if hero.name == "Evindol" and is_flanking:
                damage = 2
                special_effects.append("Ataque Furtivo (Dano dobrado por flanqueamento: 2)")

        # Poder Especial: Bet (Onda Explosiva)
        if hero.name == "Bet" and adjacent_monsters:
            for adj in adjacent_monsters:
                if not adj.is_defeated and adj.hp > 0:
                    adj.hp = max(0, adj.hp - 1)
                    if adj.hp == 0:
                        adj.is_defeated = True
            special_effects.append("Onda Explosiva (Monstros adjacentes sofreram 1 ponto de dano)")

        monster.hp = max(0, monster.hp - damage)
        if monster.hp == 0:
            monster.is_defeated = True
    else:
        # Poder Especial: Yarrow (Grilhões Espectrais ao errar o ataque)
        if hero.name == "Yarrow":
            monster.is_bound = True
            special_effects.append("Grilhões Espectrais (Ataque errou, mas espíritos prenderam o monstro ao solo!)")

    # Gatilhos do Loomis
    loomis_cage_unlocked: int | None = None
    is_victory = False

    # Gatilho 1: Monstro em 50% de HP ou menos (se for a única criatura na clareira)
    if (
        monster.hp > 0
        and monster.hp <= (monster.max_hp / 2.0)
        and active_monsters_count == 1
        and monster.cage_number < 4
    ):
        loomis_cage_unlocked = monster.cage_number + 1
        special_effects.append(
            f"Gatilho Loomis (Monstro com 50% ou menos de HP! Loomis destranca a Jaula {loomis_cage_unlocked})"
        )

    # Gatilho 3: Todas as jaulas superadas (monstro da jaula 4 derrotado)
    if monster.cage_number == 4 and monster.is_defeated:
        is_victory = True
        special_effects.append("Gatilho Loomis (Todas as 4 jaulas superadas! Insígnia Herói de Hesiod conquistada!)")

    narrative_parts = [
        f"{hero.name} atacou {monster.name} com {hero.attack_name}.",
        f"Rolagem: d20={d20} + bônus={bonus} = {total_attack} (vs CA {monster.ac}).",
        f"Resultado: {'ACERTOU!' if is_hit else 'ERROU!'}",
    ]
    if is_hit:
        narrative_parts.append(f"Dano causado: {damage}. HP do alvo: {hp_before} -> {monster.hp}.")
    if special_effects:
        narrative_parts.append("Efeitos: " + " | ".join(special_effects))

    return ActionResult(
        attacker_name=hero.name,
        defender_name=monster.name,
        action_type=ActionType.ATTACK.value,
        d20_roll=d20,
        attack_bonus=bonus,
        total_attack=total_attack,
        target_ac=monster.ac,
        is_hit=is_hit,
        is_critical=is_critical,
        damage_dealt=damage,
        defender_hp_before=hp_before,
        defender_hp_after=monster.hp,
        defender_defeated=monster.is_defeated,
        special_effect_applied=" | ".join(special_effects) if special_effects else None,
        loomis_cage_unlocked=loomis_cage_unlocked,
        loomis_potion_used=False,
        is_victory=is_victory,
        narrative_summary=" ".join(narrative_parts),
    )


def resolve_monster_attack(
    monster: MonsterState,
    hero: HeroState,
    forced_d20: int | None = None,
    forced_damage: int | None = None,
) -> ActionResult:
    """Executa a resolução determinística do ataque do monstro contra um herói."""
    special_effects: list[str] = []

    # Monstro preso por Grilhões Espectrais
    if monster.is_bound:
        monster.is_bound = False
        special_effects.append("Monstro estava preso pelos Grilhões Espectrais e perdeu a mobilidade neste turno!")

    d20 = forced_d20 if forced_d20 is not None else roll_dice(20)
    bonus = monster.attack_bonus
    total_attack = d20 + bonus
    is_critical = d20 == 20
    is_hit = is_critical or (total_attack >= hero.ac)
    hp_before = hero.hp
    damage = 0
    loomis_potion_used = False

    if is_hit:
        if is_critical:
            crit_roll = forced_damage if forced_damage is not None else roll_dice(6)
            damage = crit_roll
            special_effects.append(f"Acerto Crítico da criatura! (20 natural! Dano 1d6: {crit_roll})")
        else:
            damage = 1

        # Poder Especial: Raen (Guerreira Feroz - empurra o monstro 2 casas ao ser atingida)
        if hero.name == "Raen":
            monster.distance += 2
            special_effects.append("Guerreira Feroz (Raen foi atingida e empurrou o monstro 2 casas para trás!)")

        hero.hp = max(0, hero.hp - damage)

        # Gatilho 2 do Loomis: Herói com 0 HP
        if hero.hp == 0:
            hero.is_unconscious = False  # Revivido imediatamente pelo Loomis
            hero.hp = hero.max_hp
            loomis_potion_used = True
            special_effects.append(
                f"Gatilho Loomis (Herói caiu a 0 HP! Loomis arremessou a Poção de Menta e Limão e restaurou HP para {hero.max_hp}!)"
            )

    narrative_parts = [
        f"{monster.name} atacou {hero.name} com {monster.attack_name}.",
        f"Rolagem: d20={d20} + bônus={bonus} = {total_attack} (vs CA {hero.ac}).",
        f"Resultado: {'ACERTOU!' if is_hit else 'ERROU!'}",
    ]
    if is_hit:
        narrative_parts.append(f"Dano sofrido: {damage}. HP do herói: {hp_before} -> {hero.hp}.")
    if special_effects:
        narrative_parts.append("Efeitos: " + " | ".join(special_effects))

    return ActionResult(
        attacker_name=monster.name,
        defender_name=hero.name,
        action_type=ActionType.ATTACK.value,
        d20_roll=d20,
        attack_bonus=bonus,
        total_attack=total_attack,
        target_ac=hero.ac,
        is_hit=is_hit,
        is_critical=is_critical,
        damage_dealt=damage,
        defender_hp_before=hp_before,
        defender_hp_after=hero.hp,
        defender_defeated=False,
        special_effect_applied=" | ".join(special_effects) if special_effects else None,
        loomis_cage_unlocked=None,
        loomis_potion_used=loomis_potion_used,
        is_victory=False,
        narrative_summary=" ".join(narrative_parts),
    )
