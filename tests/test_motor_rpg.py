import pytest
from api.motor_rpg.motor_rpg import (
    create_hero,
    get_cage_monster,
    resolve_hero_attack,
    resolve_monster_attack,
    HERO_ARCHETYPES,
    CAGE_MONSTERS,
)


def test_hero_creation():
    # Testa os 5 heróis
    jorick = create_hero("jorick")
    assert jorick.name == "Jorick"
    assert jorick.ac == 13
    assert jorick.hp == 5
    assert jorick.attack_bonus == 4

    raen = create_hero("raen")
    assert raen.name == "Raen"
    assert raen.ac == 9
    assert raen.hp == 7
    assert raen.attack_bonus == 5

    bet = create_hero("bet")
    assert bet.name == "Bet"
    assert bet.ac == 7
    assert bet.hp == 4
    assert bet.attack_bonus == 7

    evindol = create_hero("evindol")
    assert evindol.name == "Evindol"
    assert evindol.ac == 11
    assert evindol.hp == 3
    assert evindol.attack_bonus == 6

    yarrow = create_hero("yarrow")
    assert yarrow.name == "Yarrow"
    assert yarrow.ac == 10
    assert yarrow.hp == 6
    assert yarrow.attack_bonus == 3


def test_monster_creation():
    # Testa os 4 monstros das jaulas
    bullette = get_cage_monster(1)
    assert bullette.name == "Bullette Faminto"
    assert bullette.ac == 15
    assert bullette.hp == 8
    assert bullette.cage_number == 1

    beholder = get_cage_monster(2)
    assert beholder.name == "Beholder Ameaçador"
    assert beholder.ac == 12
    assert beholder.hp == 11

    dragon = get_cage_monster(3)
    assert dragon.name == "Dragão Vermelho Jovem"
    assert dragon.ac == 14
    assert dragon.hp == 10

    pixies = get_cage_monster(4)
    assert pixies.name == "Enxame de Pixies Ferais"
    assert pixies.ac == 10
    assert pixies.hp == 11


def test_normal_hit_and_miss():
    jorick = create_hero("jorick")
    bullette = get_cage_monster(1)  # CA 15

    # Erro: d20 = 5 + bonus 4 = 9 < 15
    res_miss = resolve_hero_attack(jorick, bullette, forced_d20=5)
    assert not res_miss.is_hit
    assert res_miss.damage_dealt == 0
    assert bullette.hp == 8

    # Acerto normal: d20 = 11 + bonus 4 = 15 == CA 15
    res_hit = resolve_hero_attack(jorick, bullette, forced_d20=11)
    assert res_hit.is_hit
    assert not res_hit.is_critical
    assert res_hit.damage_dealt == 1
    assert bullette.hp == 7


def test_critical_hit():
    jorick = create_hero("jorick")
    bullette = get_cage_monster(1)  # HP 8

    # 20 natural no d20 -> causa 1d6 de dano (forçamos 5)
    res = resolve_hero_attack(jorick, bullette, forced_d20=20, forced_damage=5)
    assert res.is_hit
    assert res.is_critical
    assert res.damage_dealt == 5
    assert bullette.hp == 3


def test_jorick_investida():
    jorick = create_hero("jorick")
    bullette = get_cage_monster(1)  # CA 15

    # Com investida (is_far=True), bonus vira 4 + 2 = 6.
    # d20 = 9 + 6 = 15 >= CA 15 -> Acerta!
    res = resolve_hero_attack(jorick, bullette, is_far=True, forced_d20=9)
    assert res.is_hit
    assert "Investida" in res.special_effect_applied


def test_evindol_sneak_attack():
    evindol = create_hero("evindol")
    beholder = get_cage_monster(2)  # CA 12, HP 11

    # Ataque furtivo flanqueando: dano dobrado (2)
    res = resolve_hero_attack(evindol, beholder, is_flanking=True, forced_d20=10)
    assert res.is_hit
    assert res.damage_dealt == 2
    assert beholder.hp == 9
    assert "Ataque Furtivo" in res.special_effect_applied


def test_bet_onda_explosiva():
    bet = create_hero("bet")
    main_target = get_cage_monster(4)
    adj_1 = get_cage_monster(4)
    adj_2 = get_cage_monster(4)

    res = resolve_hero_attack(
        bet,
        main_target,
        adjacent_monsters=[adj_1, adj_2],
        forced_d20=10,
    )
    assert res.is_hit
    assert main_target.hp == 10
    assert adj_1.hp == 10
    assert adj_2.hp == 10
    assert "Onda Explosiva" in res.special_effect_applied


def test_yarrow_grilhoes_espectrais():
    yarrow = create_hero("yarrow")
    bullette = get_cage_monster(1)  # CA 15, Yarrow attack bonus = 3

    # Erro: d20 = 5 + 3 = 8 < 15
    res = resolve_hero_attack(yarrow, bullette, forced_d20=5)
    assert not res.is_hit
    assert bullette.is_bound is True
    assert "Grilhões Espectrais" in res.special_effect_applied


def test_raen_guerreira_feroz():
    raen = create_hero("raen")  # CA 9, HP 7
    bullette = get_cage_monster(1)

    # Monstro acerta Raen: d20 = 10 + 4 = 14 >= 9
    res = resolve_monster_attack(bullette, raen, forced_d20=10)
    assert res.is_hit
    assert raen.hp == 6
    assert bullette.distance == 2
    assert "Guerreira Feroz" in res.special_effect_applied


def test_loomis_trigger_50_percent_hp_cage_unlock():
    jorick = create_hero("jorick")
    bullette = get_cage_monster(1)  # HP 8. 50% é 4.
    bullette.hp = 5

    # Reduz de 5 para 4 (atinge 50%)
    res = resolve_hero_attack(jorick, bullette, active_monsters_count=1, forced_d20=15)
    assert res.is_hit
    assert bullette.hp == 4
    assert res.loomis_cage_unlocked == 2
    assert "Gatilho Loomis" in res.special_effect_applied


def test_loomis_trigger_hero_zero_hp_potion():
    jorick = create_hero("jorick")  # max_hp = 5
    jorick.hp = 1
    bullette = get_cage_monster(1)

    # Monstro acerta e causa 1 de dano, zerando a vida do Jorick
    res = resolve_monster_attack(bullette, jorick, forced_d20=15)
    assert res.is_hit
    assert res.loomis_potion_used is True
    # Vida do herói deve ter sido restaurada para o máximo (5)
    assert jorick.hp == 5
    assert not jorick.is_unconscious
    assert "Poção de Menta e Limão" in res.special_effect_applied


def test_loomis_trigger_victory_all_cages():
    bet = create_hero("bet")
    pixies = get_cage_monster(4)  # Jaula 4
    pixies.hp = 1

    # Derrota a criatura da jaula 4
    res = resolve_hero_attack(bet, pixies, forced_d20=15)
    assert res.is_hit
    assert pixies.hp == 0
    assert pixies.is_defeated is True
    assert res.is_victory is True
    assert "Insígnia Herói de Hesiod" in res.special_effect_applied
