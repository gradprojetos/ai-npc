# Plano de Integracao: Fechamento de Setembro vs. Backlog de Outubro (integration_september.md)

Este documento estabelece uma linha divisoria nitida entre o que deve ser entregue **AGORA** para encerrar o Mes de Setembro (fechamento dos PRs e merge na branch `main`) e o que fica como backlog para o Mes de Outubro (Guardrails, Onboarding interativo e refinamento do motor).

---

## 1. Onde Tracar a Linha de Escopo?

De acordo com o Roadmap original do projeto:

| Setembro (Mes 2 - Meta Imediata) | Outubro (Mes 3 - Proxima Etapa) |
| :--- | :--- |
| **Foco:** Logica de jogo base e conversa com IA. | **Foco:** Integracao profunda e Guardrails. |
| Unir as branches de Isaac e Murillo em `feat/integration-september`. | Implementar Onboarding interativo com selecao por botoes no Telegram. |
| Consolidar os Schemas em `api/schemas/rpg.py` (`GameState`, `TurnRecord`). | Motor de Guardrails da Nvidia para barrar respostas e validacao pedagogica. |
| Bot do Telegram respondendo via LangGraph (`turn_graph`) ciente da Jaula 1 e do heroi. | Encadeamento complexo de 4 herois cooperativos no grupo. |
| Persistencia basica de sessao no PostgreSQL. | Tratamento avancado de concorrência e testes de carga. |
| **Criterio de Entrega:** Merge aprovado na `main` com bot jogavel. | **Criterio de Entrega:** Pipeline completo com Guardrails. |

---

## 2. PARTE A: O Roteiro de Fechamento de Setembro (Escopo Minimo Viavel)

Esta e a lista de tarefas exata para abrir o PR conjunto e consolidar a `main`.

### Passo 1: Criacao da Branch de Integracao
```bash
git checkout main
git pull origin main
git checkout -b feat/integration-september
git merge origin/feat/motor_rpg_and_session_service --no-commit
git merge origin/feature/graph-state --no-commit
```

### Passo 2: Consolidacao dos Schemas (`api/schemas/rpg.py`)
Unificar os modelos evitando duplicidades:
```python
from pydantic import BaseModel
from typing import Literal

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
    is_unconscious: bool = False

class MonsterState(BaseModel):
    name: str
    cage_number: int
    hp: int
    max_hp: int
    ac: int
    attack_bonus: int = 4
    is_defeated: bool = False

class NPCState(BaseModel):
    name: str = "Loomis"
    role: str = "Treinador de Hesiod"

class TurnRecord(BaseModel):
    turn_number: int
    actor_name: str
    action_type: str
    d20_roll: int | None = None
    damage: int = 0
    target_name: str | None = None
    loomis_reaction: str = ""
    loomis_potion_used: bool = False

class GameState(BaseModel):
    session_id: str
    location: str = "Clareira de Treino em Hesiod"
    phase: str = "combat"
    current_turn_number: int = 1
    active_turn_actor: str = "player"
    cage_number: int = 1
    players: list[HeroState]
    npcs: list[NPCState] = [NPCState()]
    monsters_queue: list[MonsterState]
    turns_history: list[TurnRecord] = []
    recent_messages: list[Message] = []
    is_active: bool = True
    is_victory: bool = False
```
* Apagar `api/schemas/state.py`.
* Reexportar tudo no `api/schemas/__init__.py`.

### Passo 3: Conexao do LangGraph (`api/ai_core/turn_graph.py`)
* Atualizar o grafo para operar sobre `StateGraph(GameState)`.
* No nó `combat_node`:
  * Invocar `resolve_hero_attack(state.players[0], state.monsters_queue[0])`.
  * Adicionar o `TurnRecord` resultante em `state.turns_history`.
* No nó `npc_node`:
  * Loomis lê o evento do turno e responde em 1a pessoa via `LLMClient`.
  * Anexa a fala em `state.recent_messages` e `TurnRecord.loomis_reaction`.

### Passo 4: Conexao do Orquestrador (`api/ai_core/orchestrator.py`)
Atualizar `process_npc_turn(user_message, user_info)`:
```python
async def process_npc_turn(user_message: str, user_info: dict | None = None) -> str:
    session_id = str(user_info.get("chat_id") or "default_session")
    
    # 1. Recupera ou cria estado basico (Jaula 1 ativa com Jorick)
    state = get_or_create_session_state(session_id, user_info)
    
    # 2. Executa o LangGraph
    final_state = await turn_graph.ainvoke(state)
    
    # 3. Salva no banco (grava o GameState com turns_history em estado_sessao.variaveis_jogo)
    persist_session_state_to_db(final_state)
    
    # 4. Retorna a fala do Loomis para o Telegram
    return final_state["recent_messages"][-1].content
```


### Passo 5: Validacao e Merge na `main`
1. Rodar os testes de regressao: `pytest tests/`.
2. Fazer um teste manual via Telegram enviando uma mensagem de combate e uma de conversa.
3. Abrir o PR da `feat/integration-september` para a `main`.
4. Fechar as branches antigas (`feature/graph-state` e `feat/motor_rpg_and_session_service`).
5. **Setembro concluido com sucesso!**

---

## 3. PARTE B: Backlog de Outubro (O Que Vem Depois)

As funcionalidades a seguir pertencem ao escopo do Mes 3 e serao desenvolvidas apos o merge na `main`:

1. **Onboarding Interativo no Telegram:**
   * Fluxo de boas-vindas com menus de botoes inline para escolha de classes.
   * Sistema de `/join` para suportar 4 jogadores escolhendo herois distintos antes do combate.
2. **Turno Encadeado do Monstro:**
   * Logica automatica de contra-ataque da criatura imediatamente apos a acao do jogador.
   * Mecanica de abertura da proxima jaula quando o monstro cair para 50% de HP.
3. **Integracao com Motor de Guardrails (Nvidia NeMo Guardrails):**
   * Desenvolver e subir o container do Guardrail.
   * Filtrar entradas de usuarios para evitar jailbreaks e saidas do NPC para garantir alinhamento pedagogico.
4. **Refinamento de Persistencia e Multiplayer:**
   * Locks assincronos para evitar race conditions em mensagens simultaneas no grupo.
   * Logs de eventos pedagogicos para avaliacao de aprendizagem.
5. **Evolucao do Banco de Dados (Tabela Relacional de Turnos):**
   * Quebrar o historico de turnos em uma tabela relacional propria via Alembic migration (`historico_turno`), 
   * Permitira queries analiticas diretas em SQL para avaliacao e replay de metricas pedagogicas, enquanto em Setembro o `turns_history` permanece preservado de forma estavel dentro do JSONB `variaveis_jogo` da tabela `estado_sessao`.

