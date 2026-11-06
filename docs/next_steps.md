# Plano de Clean Up Final & Remoção de AI Slop (`refactor/final-cleanup`)

Este documento mapeia todos os *code smells*, *AI slop*, redundâncias, problemas de fronteira arquitetural e bugs ocultos identificados na varredura completa do repositório, estruturando o plano de limpeza final antes da revisão manual de código.

---

## 0. O Que Já Foi Consolidado Nesta Branch

Antes desta etapa, a branch já incorporou duas melhorias estruturais importantes que **devem ser preservadas**:
1. **Prompts Modulares por Nó ([`api/ai_core/prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py)):** Separação clara entre `EXPLORATION_PROMPT`, `COMBAT_PROMPT` e `TACTICAL_PROMPT`, compartilhando `BASE_FORMAT_RULES` e `GUARDRAILS` sem depender de leitura de prompt monolítico no banco.
2. **Consolidação das Migrations ([`db/migrations/0001_initial.py`](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py)):** Unificação do histórico fragmentado de migrations (`0001` a `0005`) em um único schema inicial limpo.

---

## 1. Seção A — Clean Up Cirúrgico (Baixo Risco / Alto Impacto — Recomendado)

Foco pragmático: corrigir apenas os **bugs reais de 1 linha** e remover **pegadas cosméticas óbvias de IA** sem alterar o schema do PostgreSQL, sem mexer na estrutura do LangGraph e sem quebrar os testes existentes.

### A.1. Correção de Bugs Pontuais de Estado e Banco (Sem alterar arquitetura)
1. **Não usar `state.location` como flag de jaula em [`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py):** Manter `location` estritamente como descrição do cenário (`"Clareira de Treino em Hesiod"`) e corrigir a detecção de combate ativo em `route_intent` sem depender de `"Aberta" in state.location`.
2. **Chave estrangeira uniforme e preservação de monstros derrotados em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L332) e [`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L328):** Trocar `session_uuid` por `session_record.session_id` ao fazer upsert de `Monster` e usar `state.monsters.append(next_beast)` (em vez de `state.monsters = [next_beast]`) para que o monstro derrotado seja salvo com `hp=0, is_defeated=True` no banco e não "ressuscite" no turno seguinte.
3. **Salvar mensagens do jogador em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L357-L373):** Salvar todas as mensagens novas do turno (`user` e `assistant`), e não apenas `state.recent_messages[-1]`.

### A.2. Limpeza Cosmética e Código Morto Óbvio (Risco Zero)
1. **Remover imports e funções mortas sem impacto:**
   * Remover import não utilizado `NPC` em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L21).
   * Remover função [`get_db()`](file:///home/isaac/Documents/mc030/ai-npc/db/session.py#L20-L26) não utilizada e importar `DATABASE_URL` de `db/session.py` em [`db/env.py`](file:///home/isaac/Documents/mc030/ai-npc/db/env.py#L14-L22).
   * Remover método morto [`NPCState.heal`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py#L66-L68), método morto [`GameState.rotate_players`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py#L84-L89) (e sua chamada em [`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L279)), parâmetro ignorado `player_name` em [`create_hero`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L152) e alias `reset_player_session` em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L409).
2. **Alinhar texto do `/start` no [`telegram_service.py`](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L166-L167):** Corrigir a descrição do poder especial de Yarrow (*"Grilhões Espectrais"*) para bater com [`HERO_ARCHETYPES`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L65).
3. **Limpar comentários óbvios de IA e `logger.debug` silencioso:** Remover comentários redundantes que apenas repetem o código e trocar `logger.debug` por `logger.warning` nas exceções de banco em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L262).
4. **Manter avaliação por IA no [`classify_intent`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L41) e determinismo restrito a comandos/onboarding:** Toda mensagem aberta de jogo deve passar pelo julgamento da IA em `classify_intent` (já que frases como *"se eu disser ataco com 18..."* podem ser dúvidas táticas; regex permanece exclusivamente como fallback se a API falhar). Apenas comandos explícitos (`/start`, `/select`, `/done`, `/help`, `/reset`) e o fluxo de onboarding são 100% determinísticos sem envolver IA.

---

## 2. Seção B — Refatoração Estrutural Pesada (Alto Impacto Arquitetural / Opcional)

Mudanças profundas de modelagem de banco, ORM e redistribuição de responsabilidades entre módulos (maior risco de regressão, exigiriam recriar schema do banco e reescrever testes):

### Lote 1: Espelhamento 1:1 (`GameState` ↔ PostgreSQL), Persistência e Bugs de Banco
*(Arquivos: [`api/schemas/rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py), [`db/models.py`](file:///home/isaac/Documents/mc030/ai-npc/db/models.py), [`db/migrations/0001_initial.py`](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py), [`db/session.py`](file:///home/isaac/Documents/mc030/ai-npc/db/session.py), [`db/env.py`](file:///home/isaac/Documents/mc030/ai-npc/db/env.py), [`api/motor_rpg/session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py), [`api/ai_core/orchestrator.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/orchestrator.py))*

* **Fix 1.1 — Espelhamento 1:1 (`GameState` ↔ `Session`) e Fim do Estado Global Volátil**
  * **Problema:**
    1. [`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L14-L16) guarda estado crítico da sessão (`_round_buffers`, `_exploration_counters`, `_last_monster_targets`) em dicionários globais mutáveis em RAM porque esses campos não existiam no banco nem no `GameState`.
    2. [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L248) deduz `is_recruiting = len(db_messages) == 0` por falta da coluna na tabela `sessions`.
  * **Solução:**
    * Adicionar `is_recruiting` (`Boolean`), `round_actions` (`JSONB`), `exploration_turns` (`Integer`) e `last_monster_target` (`String`) na tabela `sessions` ([`db/models.py`](file:///home/isaac/Documents/mc030/ai-npc/db/models.py) e [`0001_initial.py`](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py)) e no [`GameState`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py).
    * Deletar `_round_buffers`, `_exploration_counters` e `_last_monster_targets` de `turn_graph.py` e atualizar [`tests/test_e2e_coop_game.py`](file:///home/isaac/Documents/mc030/ai-npc/tests/test_e2e_coop_game.py) para não importar mais essas variáveis privadas.

* **Fix 1.2 — Bug Crítico: Salvar todas as mensagens do turno no PostgreSQL**
  * **Problema:** Em [`orchestrator.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/orchestrator.py#L43-L57), a mensagem do usuário (`role="user"`) e a resposta de Loomis (`role="assistant"`) são adicionadas ao `state.recent_messages` antes de chamar `persist_session_state_to_db`. Porém, [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L358) inspeciona apenas `state.recent_messages[-1]`, descartando todas as mensagens dos jogadores.
  * **Solução:** Persistir todas as mensagens novas do turno (tanto `user` quanto `assistant`) na tabela `messages`.

* **Fix 1.3 — Bug: Unificar chave estrangeira (`session_record.session_id`) e Eliminar N+1 Queries / Boilerplate**
  * **Problema:**
    1. Em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L305), o upsert de `Hero` usa `session_record.session_id`, mas o upsert de `Monster` ([L332](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L332)) usa `session_uuid`.
    2. [`get_or_create_session_state`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L187-L234) faz 4 `SELECT`s separados ignorando os `relationship()` de [`Session`](file:///home/isaac/Documents/mc030/ai-npc/db/models.py#L44-L58), e [`persist_session_state_to_db`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L304-L355) faz `SELECT` em loop `for` para cada herói e monstro, com ~100 linhas de cópia manual de atributos e `except Exception` silenciosos em `logger.debug`.
  * **Solução:** Carregar `Session` com `selectinload(Session.heroes, Session.monsters)`, converter com `ConfigDict(from_attributes=True)` / `model_validate()`, atualizar entidades via relacionamentos usando sempre `session_record.session_id`, remover `try...except: pass` cegos e trocar `logger.debug` por `logger.warning`.

* **Fix 1.4 — Limpeza de Código Morto na Camada de Banco (`db/`)**
  * **Problema:** Com os prompts modulares em [`prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py), o modelo `NPC` ([`db/models.py`](file:///home/isaac/Documents/mc030/ai-npc/db/models.py#L149-L160)), a tabela `npcs` em [`0001_initial.py`](file:///home/isaac/Documents/mc030/ai-npc/db/migrations/0001_initial.py#L121-L150) e o import `NPC` em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L21) ficaram sem uso. Além disso, [`get_db()`](file:///home/isaac/Documents/mc030/ai-npc/db/session.py#L20-L26) nunca é chamado e `DATABASE_URL` está duplicada entre [`db/session.py`](file:///home/isaac/Documents/mc030/ai-npc/db/session.py#L6-L14) e [`db/env.py`](file:///home/isaac/Documents/mc030/ai-npc/db/env.py#L14-L22).
  * **Solução:** Remover o modelo/tabela morta `NPC`, remover `get_db()`, e importar `DATABASE_URL` diretamente de `db/session.py` em `db/env.py` (mantendo o `pgvector` intacto na imagem e no `pyproject.toml` para não invalidar o `uv.lock`).

---

### Lote 2: Eliminação de AI Slop no Grafo e Separação com o Motor RPG
*(Arquivos: [`api/ai_core/turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py), [`api/motor_rpg/motor_rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py), [`api/schemas/rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py))*

* **Fix 2.1 — Bug & Slop: Retorno consistente de estado nos nós do LangGraph**
  * **Problema:** Os nós do grafo mutam `state` in-place e retornam dicionários parciais. No [`exploration_node`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L138), ao atingir 7 mensagens, `state.location` é atualizado para abrir a Jaula 1, mas `"location"` não é retornado no `dict` da [L160](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L160), fazendo a mutação se perder.
  * **Solução:** Garantir que todos os campos modificados em cada nó (`location`, `last_context`, `npcs`, `players`, `monsters`, `is_victory`, `recent_messages`, `round_actions`, `exploration_turns`, `last_monster_target`) sejam retornados de forma consistente.

* **Fix 2.2 — Eliminar Acoplamento por Substring em HTML ("Stringly-Typed State")**
  * **Problema:** O fluxo toma decisões procurando trechos de texto dentro de strings formatadas:
    * `"HP: 0/" in (state.last_context or "")` ([L359](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L359))
    * `[a for a in round_actions if "atacou" in a]` ([L283](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L283))
    * `"Roleplay e Exploração" in (state.last_context or "")` ([L363](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L363))
    * `"Dungeon Master:" in state.last_context` ([L399](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L399))
  * **Solução:** Substituir checagens de substring em HTML por estado explícito e verificações diretas nas entidades do domínio (`monster.is_defeated`, contagem de ações da rodada em `state.round_actions`).

* **Fix 2.3 — Devolver Regras de Combate para [`motor_rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py) e Corrigir Lista de Monstros / Cura**
  * **Problema:**
    1. [`resolve_hero_attack`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L203-L235) e [`resolve_monster_attack`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L238-L271) têm código duplicado e retornam dicionários de 12 chaves sem uso, enquanto as regras reais (escolha de alvo do monstro, gatilho de 50% de HP, cura do Loomis e progressão das 4 jaulas) estão em `combat_node`.
    2. Na troca de jaula ([`turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L275)), `state.monsters = [next_beast]` sobrescreve a lista em RAM apagando os monstros derrotados, divergindo do banco.
    3. Se todos os heróis caírem a `0 HP` no contra-ataque do monstro, ninguém consegue atacar para matar o monstro e acionar a cura, causando *soft-lock*.
  * **Solução:** Unificar a resolução de ataque em `motor_rpg.py`, mover as funções de domínio de combate para lá, usar `state.monsters.append(next_beast)` sem apagar monstros derrotados e garantir que Loomis cure com poção caso o grupo inteiro caia inconsciente (conforme [`docs/game_rules.md`](file:///home/isaac/Documents/mc030/ai-npc/docs/game_rules.md#L82)).

* **Fix 2.4 — Remover Injeção de Dados "Fantasmas", `dummy_ids` e `rotate_players()` Morto**
  * **Problema:**
    1. [`combat_node`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L177-L180) injeta um `"jorick"` silencioso se `state.players` estiver vazio, e [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L88-L96) usa `dummy_ids = {"default", "player_1", "", str(session_id)}`.
    2. [`state.rotate_players()`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py#L84-L89) gira a lista em RAM na [L279 de turn_graph.py](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L279), mas [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L208) reordena `players.sort()` pelo número da carta a cada leitura, tornando `rotate_players()` inútil (já que o atacante é identificado pelo `sender`).
  * **Solução:** Remover a injeção de herói fantasma, o set `dummy_ids` e o método morto `rotate_players()`.

* **Fix 2.5 — Simplificar `extract_d20` e Unificar Trava Anti-Dispersão (Mantendo IA no `classify_intent`)**
  * **Problema:**
    1. [`extract_d20`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L34-L36) captura qualquer número de 1 a 20 solto na frase e ignora validação de números fora do intervalo (como `50` ou `40`).
    2. Checagens anti-dispersão estão espalhadas em 3 lugares (`classify_intent`, `route_intent` e `tactical_advice_node`).
  * **Solução:** Manter `classify_intent` avaliando cada mensagem livre via IA (com regex apenas como fallback de erro de rede), garantir que comandos (`/help`, `/start`, `/select`, `/done`, `/reset`) e onboarding sejam 100% determinísticos sem IA, e centralizar a trava de combate ativo em `route_intent`.

---

### Lote 3: Redundâncias, Tipagem e Clientes de Borda
*(Arquivos: [`telegram_bot/telegram_service.py`](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py), [`llm_gateway/client.py`](file:///home/isaac/Documents/mc030/ai-npc/llm_gateway/client.py), [`api/schemas/rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py), [`api/motor_rpg/motor_rpg.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py), [`api/main.py`](file:///home/isaac/Documents/mc030/ai-npc/api/main.py))*

* **Fix 3.1 — Fonte Única para o Catálogo de Heróis (`/start` vs `HERO_ARCHETYPES`)**
  * **Problema:** O texto de `/start` em [`telegram_service.py`](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L156-L171) reescreve manualmente os status dos 5 heróis e diverge de [`HERO_ARCHETYPES`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L57-L66) (ex: Yarrow descrito com *"Espírito da Floresta"* no bot vs *"Grilhões Espectrais"* no motor).
  * **Solução:** Sincronizar a listagem de cartas a partir do catálogo canônico de `motor_rpg.py`.

* **Fix 3.2 — Remoção de Parâmetros, Métodos e Aliases Mortos**
  * **Problema:**
    * Parâmetro `player_name` em [`create_hero`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/motor_rpg.py#L152) é recebido e ignorado.
    * Método [`NPCState.heal`](file:///home/isaac/Documents/mc030/ai-npc/api/schemas/rpg.py#L66-L68) nunca é chamado.
    * Alias `reset_player_session = reset_game_session` em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L409) é desnecessário.
  * **Solução:** Remover os elementos mortos e importar `reset_game_session` diretamente em [`api/main.py`](file:///home/isaac/Documents/mc030/ai-npc/api/main.py#L11).

* **Fix 3.3 — Limpeza do [`LLMClient`](file:///home/isaac/Documents/mc030/ai-npc/llm_gateway/client.py) e Envio HTML no Telegram**
  * **Problema:** Triplo `try/except` aninhado e repetido em cada handler de [`telegram_service.py`](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L343-L355) para envio de mensagens HTML com fallback texto puro.
  * **Solução:** Extrair um único método auxiliar `_safe_reply(message, text)` no `TelegramService` e limpar comentários óbvios no `LLMClient`.

* **Fix 3.4 — Ajustes de Partida Real e Prompts (Detalhado em [`docs/diagnostico_bugs.md`](file:///home/isaac/Documents/mc030/ai-npc/docs/diagnostico_bugs.md))**
  * **Proibir HTML na saída da LLM (`prompts.py`):** Exigir texto puro (evitando `<font color="#8B4513">` e rubricas `<i>Sopro alto e agudo</i>` que consomem os 60 tokens), adicionar trava estrita de Português (pt-BR) e proibir invenção de senhas verbais (*"Diga SIM, TREINADOR"*).
  * **Validação de d20 fora de 1–20 (`turn_graph.py`):** Tratar rolagens inválidas (ex: `ataco com 50`) com aviso direto do DM, sem reanunciar abertura de jaula e sem acionar a LLM.
  * **Preservar `state.location`:** Manter `location` apenas como descrição de cena (`"Clareira de Treino em Hesiod"`), sem sobrescrevê-lo com status de jaula.
  * **Enxugar verbosidade do Onboarding:** Reduzir a confirmação do `/select` para 1–2 linhas e unificar a mensagem do `/reset`.

---

## 3. Gateway Multi-Provedor LLM (Strategy + Adapter Pattern)

Desacoplar as particularidades de cada provedor em [`llm_gateway/`](file:///home/isaac/Documents/mc030/ai-npc/llm_gateway/client.py) mantendo a fachada `LLMClient` 100% retrocompatível:

- [ ] **3.1.** Criar a interface abstrata `LLMProvider` (Strategy) em `llm_gateway/providers/base.py`.
- [ ] **3.2.** Implementar `OpenRouterProvider`, `ICUnicampProvider` e `NvidiaBuildProvider`.
- [ ] **3.3.** Implementar `LLMProviderFactory` em `llm_gateway/factory.py` selecionando via `LLM_PROVIDER` no `.env`.

---

## 4. Atualização da Documentação de Arquitetura ([`docs/architecture.md`](file:///home/isaac/Documents/mc030/ai-npc/docs/architecture.md))

Pontos do documento de arquitetura que estão defasados em relação ao código atual e precisam ser alinhados:

- [ ] **4.1. Ciclo Cognitivo no LangGraph (Seção 5):** Atualizar o diagrama de estados para incluir as 3 rotas reais (`exploration_node`, `tactical_advice_node`, `combat_node`), os prompts modulares de [`api/ai_core/prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py) e o retorno imediato do DM no meio da rodada (`is_mid_round_turn`).
- [ ] **4.2. Persistência vs. Memória (Seção 3):** Atualizar o diagrama de sequência para remover o antigo `SessionManager (Memória)` como fonte primária e refletir o PostgreSQL como *Single Source of Truth*.
- [ ] **4.3. Dinâmica de Rodada Fechada vs. "Monsters First" (Seção 4.2):** Alinhar a descrição das regras com a implementação atual de rodada fechada por iniciativa e com o prólogo de exploração pós-`/done`.
- [ ] **4.4. Status do Langfuse (Seções 1 e 3):** Sinalizar o Langfuse como integração planejada/futura (atualmente pausada no código).

---

## 5. Roteiro de Execução e Validação (4 Etapas)

- [ ] **Etapa 1 — Execução (Seção A ou A+B):** Aplicar os ajustes cirúrgicos da **Seção A** + **Fix 3.4** (e opcionalmente itens escolhidos da **Seção B**).
- [ ] **Etapa 2 — Bateria de Testes E2E:** Rodar [`tests/test_e2e_coop_game.py`](file:///home/isaac/Documents/mc030/ai-npc/tests/test_e2e_coop_game.py) garantindo 100% de aprovação.
- [ ] **Etapa 3 — Nova Auditoria Cega por Subagente:** Invocar novamente o subagente de auditoria (`research`) sobre a base limpa para confirmar que nenhum *AI slop*, código morto ou inconsistência restou.
- [ ] **Etapa 4 — Revisão Humana Final:** Leitura manual completa de todos os arquivos antes do merge para a `main`.
