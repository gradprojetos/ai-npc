import logging
from langgraph.graph import StateGraph, START, END
from api.schemas import GameState, Message
from llm_gateway.client import LLMClient

logger = logging.getLogger(__name__)
llm_client = LLMClient()

NPC_SYSTEM_PROMPT = """
Você é Loomis, o lendário e dedicado treinador da vila de Hesiod.
Você tem traços de sangue de ogro, é forte e intimidador, mas tem uma voz estranhamente aguda e anasalada.
Sua personalidade: pragmático, enérgico, exigente, mas muito protetor e encorajador com seus recrutas.
Você nunca deixa nenhum aluno morrer na arena de treino.
Fale sempre em primeira pessoa, de forma concisa e direta, reagindo às ações do herói ou dando conselhos táticos breves sobre os monstros nas jaulas.
Nunca quebre o personagem.

"""


def classify_intent_node(state: GameState) -> dict:
    """Nó para pré-processar ou registrar a intenção do turno atual."""
    last_msg = state.messages[-1].content if state.messages else ""
    logger.info(f"Classificando mensagem no grafo: '{last_msg}'")
    return {}


def combat_node(state: GameState) -> dict:
    """Nó para resolução de combate e rolagem de dados."""
    logger.info("Executando nó de combate...")
    # A integração completa com o motor RPG será conectada aqui
    return {}


def tactical_advice_node(state: GameState) -> dict:
    """Nó para preparar contexto de conselho ou dica tática sobre o monstro atual."""
    logger.info("Executando nó de conselho tático...")
    # adicionar dicionario de dicas táticas ou contexto do monstro atual
    return {}


async def npc_node(state: GameState) -> dict:
    """Nó principal de narração e diálogo do NPC Loomis em primeira pessoa."""
    last_user_message = ""
    for msg in reversed(state.messages):
        if msg.role == "user":
            last_user_message = msg.content
            break

    # Contexto básico do monstro ativo se houver
    monster_context = ""
    if state.monsters:
        active_monster = state.monsters[0]
        monster_context = f" [Monstro atual na arena: {active_monster.name}, HP: {active_monster.hp}/{active_monster.max_hp}]"

    prompt_context = f"{last_user_message}{monster_context}" if monster_context else last_user_message

    logger.info(f"Gerando resposta do NPC via LLM para: '{prompt_context}'")
    resposta_texto = await llm_client.generate_reply(
        message=prompt_context,
        system_prompt=NPC_SYSTEM_PROMPT,
    )

    npc_message = Message(
        sender="Loomis",
        content=resposta_texto,
        role="assistant",
    )

    return {"messages": state.messages + [npc_message]}


def route_intent(state: GameState) -> str:
    """Bifurca o fluxo entre combate e diálogo/dica tática."""
    if not state.messages:
        return "tactical_advice"

    last_content = state.messages[-1].content.lower()
    combat_keywords = ["atacar", "ataque", "golpe", "bater", "espada", "magia", "flecha", "lutar", "investida"] # pode ser falho

    if any(keyword in last_content for keyword in combat_keywords):
        return "combat"
    return "tactical_advice"


def build_turn_graph():
    """Compila e retorna o fluxo do LangGraph para o ciclo de turno."""
    workflow = StateGraph(GameState)

    # Registro dos nós
    workflow.add_node("classify", classify_intent_node)
    workflow.add_node("combat", combat_node)
    workflow.add_node("tactical_advice", tactical_advice_node)
    workflow.add_node("npc", npc_node)

    # Definição das arestas e bifurcação condicional
    workflow.add_edge(START, "classify")
    workflow.add_conditional_edges(
        "classify",
        route_intent,
        {
            "combat": "combat",
            "tactical_advice": "tactical_advice",
        },
    )
    workflow.add_edge("combat", "npc")
    workflow.add_edge("tactical_advice", "npc")
    workflow.add_edge("npc", END)

    return workflow.compile()


turn_graph = build_turn_graph()