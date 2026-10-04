# Plano de Integracao: Fechamento de Setembro vs. Backlog de Outubro (next_steps.md)

Este documento estabelece a linha divisória nítida entre o que deve ser entregue **AGORA** para encerrar o Mês de Setembro (fechamento dos PRs, consolidação de schemas e merge na branch `main`) e o que fica como backlog para o Mês de Outubro (Guardrails, Onboarding interativo e observabilidade avançada).

---

## 1. Onde Traçar a Linha de Escopo?

De acordo com o Roadmap e os alinhamentos de arquitetura:

| Setembro (Mês 2 - Meta Imediata) | Outubro (Mês 3 - Próxima Etapa) |
| :--- | :--- |
| **Foco:** Lógica de jogo base, regras oficiais e conversa com IA. | **Foco:** Integração profunda, Guardrails e Observabilidade. |
| Unir as branches em `feat/integration-september`. | Implementar Onboarding interativo com botões no Telegram. |
| Consolidar schemas enxutos em `api/schemas/rpg.py` (`GameState` sem `TurnRecord`). | Motor de Guardrails da Nvidia (NeMo) para validação pedagógica. |
| Bot do Telegram respondendo via LangGraph (`turn_graph`) com d20 físico e dicas táticas. | Rastreamento e telemetria profunda de combate via **Langfuse**. |
| Persistência relacional explícita (`sessions`, `heroes`, `monsters`, `messages`, `npcs`). | Tratamento avançado de concorrência e testes de carga. |
| **Critério de Entrega:** Merge aprovado na `main` com bot jogável. | **Critério de Entrega:** Pipeline completo com Guardrails e Langfuse. |

---

## 2. PARTE A: O Roteiro de Fechamento de Setembro (Escopo Mínimo Viável)

Esta é a lista de tarefas exata para abrir o PR conjunto e consolidar a `main`.

### Passo 1: Criação da Branch de Integração
```bash
git checkout main
git pull origin main
git checkout -b feat/integration-september
git merge origin/feat/motor_rpg_and_session_service --no-commit
git merge origin/feature/graph-state --no-commit
```

### Passo 2: Consolidação dos Schemas (`api/schemas/rpg.py`)
Unificar os modelos eliminando redundâncias (`current_turn`, `active_player_id`, `TurnRecord`):

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
    attack_name: str = "Ataque Básico"
    special_power: str = ""              # Regra posicional auto-contida (ex.: Ataque Furtivo)

class MonsterState(BaseModel):
    name: str
    cage_number: int
    hp: int
    max_hp: int
    ac: int
    attack_bonus: int = 4
    attack_name: str = "Ataque da Criatura"
    abilities: list[str] = []            # Habilidades do livro (ex.: Engolir, múltiplos raios)
    is_defeated: bool = False

class NPCState(BaseModel):
    name: str = "Loomis"
    system_prompt: str = ""

class GameState(BaseModel):
    session_id: str
    location: str = "Clareira de Treino em Hesiod"

    players: list[HeroState]             # Fila de iniciativa: players[0] é sempre a vez
    monsters: list[MonsterState]         # monsters[0] é a criatura ativa enfrentada
    npcs: list[NPCState]

    last_context: str | None = None      # Resumo mecânico efêmero injetado no prompt da LLM
    recent_messages: list[Message] = []  # Buffer recente para contexto conversacional
    is_victory: bool = False
```
* Apagar `api/schemas/state.py`.
* Reexportar tudo no `api/schemas/__init__.py`.

### Passo 2.1: Modelagem Relacional Literal das Tabelas (`db/models.py`)
Mapear os estados do Pydantic campo a campo em tabelas relacionais explícitas (1:1), eliminando `usuario`, `estado_sessao` e colunas JSONB opacas:
1. **`sessions`:** `session_id (UUID, PK)`, `chat_id (BigInteger, UK)`, `location`, `is_victory`, `created_at`.
2. **`heroes`:** `id (UUID, PK)`, `session_id (UUID, FK)`, `player_id`, `name`, `class_name`, `hp`, `max_hp`, `ac`, `attack_bonus`, `attack_name`, `special_power`.
3. **`monsters`:** `id (UUID, PK)`, `session_id (UUID, FK)`, `name`, `cage_number`, `hp`, `max_hp`, `ac`, `attack_bonus`, `attack_name`, `abilities`, `is_defeated`.
4. **`messages`:** `id (UUID, PK)`, `session_id (UUID, FK)`, `sender`, `role`, `content`, `timestamp`.
5. **`npcs`:** `id (UUID, PK)`, `name`, `system_prompt`.
6. **Atualização do `session_service.py`:** Buscar e atualizar heróis e monstros diretamente por `filter_by(session_id=session_id)`.

### Passo 3: Conexão do LangGraph (`api/ai_core/turn_graph.py`)
* Atualizar o grafo para operar sobre `StateGraph(GameState)`.
* No nó `classify_intent_node`:
  * Detecta se a mensagem é diálogo/dica ou ataque.
  * Extrai o valor do d20 físico declarado (se for ataque).
* No nó `tactical_advice_node`:
  * Prepara conselho pedagógico com base em `state.players[0].special_power` e `state.monsters[0].abilities`.
  * **Ação Livre:** Não altera nem rotaciona a lista `players`.
* No nó `combat_node`:
  * Se o d20 não foi informado: sinaliza para Loomis solicitar a rolagem física.
  * Com o d20: resolve o golpe contra `state.monsters[0].ac`, atualiza HP e processa contra-ataque da fera.
  * Preenche `state.last_context` com o resumo da jogada.
  * Roda a fila de heróis: `state.players.append(state.players.pop(0))`.
* No nó `npc_node`:
  * Loomis lê `state.last_context` (ou a dica tática) e responde em 1ª pessoa via `LLMClient`.
  * Anexa a fala em `state.recent_messages`.

### Passo 4: Conexão do Orquestrador (`api/ai_core/orchestrator.py`)
Atualizar `process_npc_turn(user_message, user_info)`:
```python
async def process_npc_turn(user_message: str, user_info: dict | None = None) -> str:
    session_id = str(user_info.get("chat_id") or "default_session")
    
    # 1. Recupera ou cria estado básico (Jaula 1 ativa com Jorick)
    state = get_or_create_session_state(session_id, user_info)
    
    # 2. Registra a mensagem do usuário no buffer
    state.recent_messages.append(Message(sender="Jogador", content=user_message, role="user"))
    
    # 3. Executa o LangGraph
    final_state = await turn_graph.ainvoke(state)
    
    # 4. Salva no banco (atualiza monsters.hp e heroes.hp via SQLAlchemy db.commit)
    persist_session_state_to_db(final_state)
    
    # 5. Retorna a fala do Loomis para o Telegram
    return final_state["recent_messages"][-1].content
```

### Passo 5: Validação e Merge na `main`
1. Rodar os testes de regressão: `pytest tests/`.
2. Fazer um teste manual via Telegram enviando uma mensagem de dica e uma de ataque com d20.
3. Abrir o PR da `feat/integration-september` para a `main`.
4. Fechar as branches antigas (`feature/graph-state` e `feat/motor_rpg_and_session_service`).
5. **Setembro concluído com sucesso!**

---

## 3. PARTE B: Backlog de Outubro (O Que Vem Depois)

As funcionalidades a seguir pertencem ao escopo do Mês 3 e serão desenvolvidas após o merge na `main`:

1. **Onboarding Interativo no Telegram:**
   * Fluxo de boas-vindas com menus de botões inline para escolha de classes.
   * Sistema de `/join` para suportar 4 jogadores escolhendo heróis distintos antes do combate.
2. **Observabilidade e Tracing com Langfuse:**
   * Rastreamento dos prompts de Loomis, latências, custos de tokens e metadados de rolagens de d20.
   * Elimina a necessidade de tabelas relacionais de telemetria manual no banco.
3. **Turno Encadeado Avançado do Monstro ("Monsters First"):**
   * Abertura de combate com ataque inicial automático da fera na primeira mensagem.
   * Abertura da próxima jaula quando o monstro cair para 50% de HP.
4. **Integração com Motor de Guardrails (Nvidia NeMo Guardrails):**
   * Subir o container de Guardrail.
   * Filtrar entradas de usuários para evitar jailbreaks e saídas do NPC para garantir alinhamento pedagógico.
5. **Refinamento de Persistência e Multiplayer Simultâneo:**
   * Locks assíncronos para evitar race conditions em mensagens simultâneas no grupo.
   * Avaliação de métricas de engajamento pedagógico.
