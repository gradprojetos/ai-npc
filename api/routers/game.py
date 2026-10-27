from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.ai_core.orchestrator import process_npc_turn
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    get_or_create_session_state,
    reset_game_session,
    select_hero_for_player,
)
from api.schemas.rpg import GameState

router = APIRouter()


class SelectHeroRequest(BaseModel):
    session_id: str
    player_id: str
    player_name: str
    choice: str | int


class ActionRequest(BaseModel):
    session_id: str


class PlayerMessageRequest(BaseModel):
    session_id: str
    player_id: str
    player_name: str = "Jogador"
    message: str


@router.post("/select")
def select_hero(req: SelectHeroRequest):
    """Vincula um jogador a um dos 5 heróis canônicos."""
    success, message, state = select_hero_for_player(
        session_id=req.session_id,
        player_id=req.player_id,
        player_name=req.player_name,
        choice=req.choice,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": success, "message": message, "state": state}


@router.post("/done")
def finish_recruiting(req: ActionRequest):
    """Finaliza o recrutamento (/done) e abre a fase de exploração/preparação."""
    success, message, state = finish_recruiting_for_session(req.session_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": success, "message": message, "state": state}


@router.post("/message")
async def send_message(req: PlayerMessageRequest):
    """Envia uma mensagem de jogador (roleplay, conselho ou combate) e obtém resposta."""
    user_info = {
        "session_id": req.session_id,
        "telegram_id": req.player_id,
        "first_name": req.player_name,
    }
    reply = await process_npc_turn(user_message=req.message, user_info=user_info)
    return {"reply": reply}


@router.get("/state/{session_id}", response_model=GameState)
def get_state(session_id: str):
    """Recupera o estado atual do jogo da sessão."""
    return get_or_create_session_state(session_id)


@router.post("/reset")
def reset_session(req: ActionRequest):
    """Reinicia completamente a sessão de jogo."""
    reset_game_session(req.session_id)
    return {"success": True, "message": "Sessão reiniciada com sucesso."}
