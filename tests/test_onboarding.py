import pytest
from unittest.mock import AsyncMock, MagicMock
from api.motor_rpg.motor_rpg import create_hero, get_hero_card_number, HERO_CARDS
from api.motor_rpg.session_service import select_hero_for_player, get_memory_session, clear_memory_session
from telegram_bot.telegram_service import TelegramService


def test_create_hero_by_card_number():
    """Garante que create_hero aceita número de carta (#1 a #5) e inclui o nome do jogador."""
    hero_1 = create_hero("1", player_id="u1", player_name="Isaac")
    assert hero_1.name == "Evindol (Isaac)"
    assert hero_1.class_name == "Ladino Humano"
    assert hero_1.attack_bonus == 6

    hero_2 = create_hero(2, player_id="u2", player_name="Pedro")
    assert hero_2.name == "Raen (Pedro)"
    assert hero_2.class_name == "Bárbara Anã"

    hero_5 = create_hero(5, player_id="u5")
    assert hero_5.name == "Bet"
    assert hero_5.class_name == "Maga Elfa"


def test_get_hero_card_number():
    """Garante ordenação correta das cartas canônicas."""
    assert get_hero_card_number("Evindol (Isaac)") == 1
    assert get_hero_card_number("Raen (Pedro)") == 2
    assert get_hero_card_number("Jorick") == 3
    assert get_hero_card_number("Yarrow") == 4
    assert get_hero_card_number("Bet") == 5


def test_select_hero_for_player_and_initiative_order():
    """Garante que a seleção adiciona os heróis e os ordena canonicamente (#1 a #5)."""
    session_id = "test_onboarding_session"
    clear_memory_session(session_id)

    # 1. Pedro escolhe a carta #3 (Jorick)
    ok, msg, state = select_hero_for_player(session_id, player_id="u1", player_name="Pedro", choice="3")
    assert ok is True
    assert "Jorick" in msg
    assert len(state.players) == 1
    assert state.players[0].name == "Jorick (Pedro)"

    # 2. Isaac escolhe a carta #1 (Evindol)
    ok, msg, state = select_hero_for_player(session_id, player_id="u2", player_name="Isaac", choice="1")
    assert ok is True
    assert "Evindol" in msg
    assert len(state.players) == 2
    # Evindol (#1) deve ficar na frente de Jorick (#3) na ordem de iniciativa
    assert state.players[0].name == "Evindol (Isaac)"
    assert state.players[1].name == "Jorick (Pedro)"

    # 3. Terceiro jogador tenta escolher a mesma carta #1 (Evindol) -> Deve rejeitar
    ok, err_msg, state = select_hero_for_player(session_id, player_id="u3", player_name="Lucas", choice="1")
    assert ok is False
    assert "já foi escolhida" in err_msg
    assert len(state.players) == 2


@pytest.mark.asyncio
async def test_telegram_handlers_start_and_select():
    """Verifica respostas dos handlers de onboarding /start e /select no TelegramService."""
    service = TelegramService()

    # Mock do update do telegram
    mock_message = AsyncMock()
    mock_update = MagicMock()
    mock_update.message = mock_message
    mock_update.effective_chat.id = 12345
    mock_update.effective_user.id = 999
    mock_update.effective_user.first_name = "Isaac"

    # Testa /start
    mock_context = MagicMock()
    await service._start_handler(mock_update, mock_context)
    mock_message.reply_text.assert_called_once()
    start_reply = mock_message.reply_text.call_args[0][0]
    assert "Arena de Treinamento de Hesiod" in start_reply
    assert "/select 1" in start_reply
    assert "Evindol" in start_reply

    # Testa /select com callback
    mock_message.reset_mock()
    mock_context.args = ["2"]

    async def mock_on_select(session_id, player_id, player_name, choice):
        return True, f"Recruta Alistado: {player_name} com carta {choice}", None

    service.on_select_callback = mock_on_select
    await service._select_handler(mock_update, mock_context)
    mock_message.reply_text.assert_called_once()
    select_reply = mock_message.reply_text.call_args[0][0]
    assert "Recruta Alistado: Isaac com carta 2" in select_reply
