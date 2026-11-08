# Plano de Clean Up Final & Próximos Passos (`refactor/final-cleanup`)

Roteiro consolidado de implementação **Bottom-Up** validado contra a codebase para corrigir regressões de partida, remover código morto / *AI slop* e manter 100% dos testes E2E verdes sem retrabalho de arquivos.

---

## 0. O Que Já Foi Consolidado Nesta Branch

1. **Prompts Modulares por Nó ([`api/ai_core/prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py)):** Separação clara entre `EXPLORATION_PROMPT`, `COMBAT_PROMPT` e `TACTICAL_PROMPT`, compartilhando `BASE_FORMAT_RULES` e `GUARDRAILS` sem depender de leitura de prompt monolítico no banco.
2. **Consolidação das Migrations ([`db/migrations/0001_initial.py`](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py)):** Unificação do histórico fragmentado de migrations (`0001` a `0005`) em um único schema inicial limpo.

---

## 1. Roteiro de Implementação — Clean Up Cirúrgico (Bottom-Up)

Sequência estruturada em **6 Fases (Fundação $\rightarrow$ Persistência $\rightarrow$ Prompts $\rightarrow$ Grafo $\rightarrow$ Borda Telegram $\rightarrow$ Testes)** para editar cada arquivo em uma única passagem sem quebrar importadores intermediários:

### Fase 1: Camada de Dados, Schemas e Motor RPG (Fundação)
- [x] **1.1. [`db/session.py`](file:///home/isaac/Documents/mc030/ai-npc/db/session.py#L20-L26) e [`db/env.py`](file:///home/isaac/Documents/mc030/ai-npc/db/env.py#L14-L22):**
  - Remover função morta `get_db()` de `db/session.py`.
  - Importar `DATABASE_URL` diretamente de `db.session` em `db/env.py` (eliminando a duplicação de `os.getenv`).
- [x] **1.2. [`api/schemas/rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py):**
  - Remover métodos mortos [`NPCState.heal()` (L66-L68)](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py#L66-L68) e [`GameState.rotate_players()` (L84-L89)](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py#L84-L89).
- [x] **1.3. [`api/motor_rpg/motor_rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L152):**
  - Remover parâmetro morto `player_name: str | None = None` da assinatura de `create_hero()`.

### Fase 2: Serviço de Sessão, Persistência e Rotas (`session_service.py`, `__init__.py`, `main.py`)
- [x] **2.1. Limpeza de imports, chamadas e aliases em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py), [`api/motor_rpg/__init__.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/__init__.py) e [`api/main.py`](file:///home/isaac/Documents/mc030/ai-npc/api/main.py):**
  - Remover `NPC` do import em [`session_service.py` (L21)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L21).
  - Remover argumento `player_name=player_name` na chamada de `create_hero()` em [`session_service.py` (L80)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L80).
  - Remover alias `reset_player_session = reset_game_session` em [`session_service.py` (L415)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L415) e atualizar **ambos os importadores** para usarem `reset_game_session`: [`api/main.py` (L11 e L31)](file:///home/isaac/Documents/mc030/ai-npc/api/main.py#L11) e [`api/motor_rpg/__init__.py` (L14 e L28)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/__init__.py#L14).
  - Trocar `logger.debug` por `logger.warning` nas **duas** exceções de banco em [`session_service.py` (L262 e L377)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L262).
- [x] **2.2. Correção de Persistência no PostgreSQL ([`session_service.py` L331-L373](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L331-L373)):**
  - **Upsert uniforme de `Monster` ([L332 e L335](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L332-L335)):** Usar `session_record.session_id` em vez de `session_uuid` (como já é feito em `Hero` na L305) para garantir que monstros derrotados sejam atualizados com `hp=0, is_defeated=True` e não "ressuscitem" no turno seguinte.
  - **Persistência completa do diálogo ([L357-L373](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L357-L373)):** Salvar no banco tanto a mensagem `user` quanto a resposta `assistant` do turno (e não apenas `state.recent_messages[-1]`), evitando envenenar o histórico com apenas falas de Loomis.
- [x] **2.3. Compactação do `/select` ([`session_service.py` L104-L111](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L104-L111)):**
  - Reduzir o retorno de `select_hero_for_player` de 6 linhas para uma confirmação enxuta de 1–2 linhas (mantendo o nome do herói para compatibilidade com [`test_e2e_coop_game.py` L186](file:///home/isaac/Documents/mc030/ai-npc/tests/test_e2e_coop_game.py#L186)).

### Fase 3: Prompts e Regras da LLM (`api/ai_core/prompts.py`)
- [x] **3.1. Blindagem de [`prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py):**
  - Em `BASE_FORMAT_RULES`:
    - Exigir resposta em **texto puro** (proibindo tags HTML/Markdown como `<font>` ou `<i>...</i>` que estouravam os 60 tokens).
    - Remover a menção a `"voz aguda/anasalada"` para evitar rubricas sonoras (`"Sopro alto e agudo"`).
    - Adicionar trava estrita de idioma: *"IDIOMA OBRIGATÓRIO: Responda ESTRITAMENTE em Português do Brasil (pt-BR). Jamais use palavras em espanhol ou pontuação invertida (¡, ¿)."*
  - Em `COMBAT_PROMPT` e `TACTICAL_PROMPT`:
    - Proibir invenção de comandos/senhas verbais (*"NUNCA peça para os jogadores dizerem frases específicas como 'Sim, treinador!'"*).
    - Instruir Loomis a aceitar declarações curtas (`ataco com X`), narrando a ação pela arma/magia da ficha sem repreender a sintaxe do jogador.

### Fase 4: Grafo de Turnos e Orquestrador (`turn_graph.py` e `orchestrator.py`)
- [x] **4.1. Filtro Pré-Grafo de Ruído e Ofensas ([`orchestrator.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/orchestrator.py) / [`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py)):**
  - Interceptar antes do grafo mensagens de pontuação isolada (`.`, `?`, `!`, `< 2` caracteres alfanuméricos, liberando rolagens numéricas de 1–2 dígitos) e ofensas explícitas (regex determinístico), respondendo estaticamente sem chamar a LLM e sem alterar o estado da arena.
  - Manter `classify_intent` ([L50](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L50)) avaliando toda mensagem livre legítima via IA (regex apenas como fallback de erro de rede).
- [x] **4.2. Ciclo de Combate, Estado de Jaula e Validação de d20 ([`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py)):**
  - Remover chamada morta `state.rotate_players()` ([L332](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L332)).
  - **Preservação de monstros derrotados ([L328](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L328)):** Trocar `state.monsters = [next_beast]` por `state.monsters.append(next_beast)` para que monstros com `0 HP` sejam salvos no banco como derrotados.
  - **Preservação de `state.location` e separação de abertura da jaula vs. validação de d20:**
    - Remover as mutações `state.location = "Arena de Hesiod — Jaula X Aberta"` em `exploration_node` ([L147](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L147)) e `combat_node` ([L208-L210](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L208-L210)), mantendo `state.location` fixo como `"Clareira de Treino em Hesiod"`.
    - Rastrear o início do combate de forma explícita e separar os 3 cenários em `combat_node` ([L230-L243](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L230-L243)):
      1. **Abertura inicial da Jaula 1** (ex: `"estamos prontos"` quando a luta ainda não começou): anuncia `"• A Jaula 1 foi aberta..."` e aciona Loomis (preservando [`test_e2e_coop_game.py` L109](file:///home/isaac/Documents/mc030/ai-npc/tests/test_e2e_coop_game.py#L109)).
      2. **Valor de d20 inválido fora de `1–20`** (ex: `ataco com 50`): retorna aviso determinístico imediato do DM (`"• Valor inválido! O d20 físico possui apenas valores de 1 a 20..."`) sem reanunciar abertura de jaula e sem chamar LLM.
      3. **Ataque no meio da luta sem informar número do d20**: pede apenas o valor de 1 a 20 sem repetir que a jaula foi aberta.
    - Atualizar `route_intent` ([L513](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L513)) para detectar combate ativo sem usar `"Aberta" in state.location`.
- [x] **4.3. Identificação do Herói e Sanitização HTML no `npc_node` ([`turn_graph.py` L448-L484](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L448-L484)):**
  - Identificar o herói correspondente ao `sender` da última mensagem e formatar `Última mensagem enviada por {hero_name}: "{last_user_message}"` nas L455 e L458 (evitando que Loomis dê bronca no herói errado).
  - No pós-processamento ([L479-L484](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L479-L484)), remover tags HTML residuais (`re.sub(r"<[^>]+>", "", speech)`), prefixos `Loomis:` e aspas duplicadas antes de envelopar em `<b>Loomis:</b>\n"{speech}"`.

### Fase 5: Borda Telegram (`telegram_bot/telegram_service.py`)
- [x] **5.1. Onboarding Conciso e Single Source of Truth ([`telegram_service.py`](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py)):**
  - Em `_start_handler` ([L156-L171](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L156-L171)), consumir `HERO_CARDS` e `HERO_ARCHETYPES` diretamente de [`motor_rpg.py` (L57-L66)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L57-L66) (corrigindo automaticamente o poder de Yarrow para *"Grilhões Espectrais"*) em formato compacto (1 linha por herói).
  - Em `_reset_handler` ([L276-L281](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L276-L281)), unificar o aviso de sessão reiniciada + catálogo em uma única mensagem (eliminando o envio duplo).

### Fase 6: Validação E2E e Auditoria Final
- [x] **6.1.** Rodar `pytest tests/test_e2e_coop_game.py` garantindo 100% de aprovação.
- [x] **6.2.** Invocar subagente de auditoria (`research`) sobre a base modificada para confirmar ausência de regressões ou *AI slop*.

---

## 2. Backlog Opcional — Refatoração Estrutural Pesada (Seção B)

Mudanças profundas de modelagem de banco, ORM e arquitetura (maior risco de regressão; exigem alterar schema/migrations e testes):

### Lote 1: Espelhamento 1:1 (`GameState` ↔ PostgreSQL) e Remoção de Estado Global em RAM
* **Fix 1.1 — Eliminar os 4 dicionários globais voláteis de [`turn_graph.py` (L14-L17)](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L14-L17):**
  * Mover `_round_buffers`, `_acted_heroes`, `_exploration_counters` e `_last_monster_targets` (além de `is_recruiting` deduzido em [`session_service.py` L248](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L248)) para colunas explícitas na tabela `sessions` ([`db/models.py`](file:///home/isaac/Documents/mc030/ai-npc/db/models.py), [`0001_initial.py`](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py)) e no [`GameState`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py), atualizando [`test_e2e_coop_game.py` (L6)](file:///home/isaac/Documents/mc030/ai-npc/tests/test_e2e_coop_game.py#L6).
* **Fix 1.2 — Eliminar N+1 Queries em [`session_service.py` (L187-L234 e L304-L355)](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L187-L234):**
  * Usar `selectinload(Session.heroes, Session.monsters)` e `ConfigDict(from_attributes=True)` / `model_validate()`.
* **Fix 1.3 — Remover modelo `NPC` ([`db/models.py` L149-L160](file:///home/isaac/Documents/mc030/ai-npc/db/models.py#L149-L160)) e tabela `npcs` ([`0001_initial.py` L121-L150](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py#L121-L150)).**

### Lote 2: Desacoplamento de Substrings HTML e Separação Grafo ↔ Motor RPG
* **Fix 2.1 — Eliminar acoplamento por substring em [`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py):**
  * Substituir checagens de texto em `state.last_context` ([L419-L423](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L419-L423), [L443](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L443), [L447](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L447), [L474](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L474), [L486](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L486)) por flags/estado explícito.
* **Fix 2.2 — Devolver regras de combate para [`motor_rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py) e evitar *soft-lock* de party wipe.**
* **Fix 2.3 — Remover injeção de `"jorick"` fantasma ([`turn_graph.py` L186-L187](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L186-L187)) e `dummy_ids` ([`session_service.py` L88-L96](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L88-L96)).**
* **Fix 2.4 — Extrair helper `_safe_reply` em [`telegram_service.py` (L343-L355)](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L343-L355).**

---

## 3. Evoluções Futuras (Gateway Multi-Provedor & Documentação)

### 3.1. Gateway Multi-Provedor LLM (Strategy + Adapter Pattern em [`llm_gateway/`](file:///home/isaac/Documents/mc030/ai-npc/llm_gateway/client.py))
- [ ] Criar interface `LLMProvider` em `llm_gateway/providers/base.py`.
- [ ] Implementar `OpenRouterProvider`, `ICUnicampProvider` e `NvidiaBuildProvider`.
- [ ] Implementar `LLMProviderFactory` em `llm_gateway/factory.py` via `LLM_PROVIDER` no `.env`.

### 3.2. Atualização da Documentação de Arquitetura ([`docs/architecture.md`](file:///home/isaac/Documents/mc030/ai-npc/docs/architecture.md))
- [ ] **Seção 5 (LangGraph):** Atualizar diagrama com as 3 rotas (`exploration_node`, `tactical_advice_node`, `combat_node`), prompts modulares e `is_mid_round_turn`.
- [ ] **Seção 3 (Persistência):** Refletir o PostgreSQL como *Single Source of Truth* (sem `SessionManager` em memória).
- [ ] **Seção 4.2 (Dinâmica de Rodada):** Alinhar com rodada fechada por iniciativa e prólogo de exploração pós-`/done`.
- [ ] **Seções 1 e 3 (Langfuse):** Sinalizar Langfuse como integração planejada/futura.
