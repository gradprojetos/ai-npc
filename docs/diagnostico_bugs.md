# Diagnóstico de Problemas em Partida (Pós-Migração OpenRouter / Regressões de Estado)

Este documento registra a causa raiz exata das regressões observadas em partida após a introdução do modo de exploração e os commits recentes.

---

## 🚨 As 4 Causas Raízes Críticas (Por que os fixes anteriores não surtiram efeito)

### Causa Raiz A: Uso indevido de `state.location` como flag de jaula (e descarte pelo LangGraph)
* **Onde:** [`api/ai_core/turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L208-L211) e [`route_intent`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L514).
* **O que acontece:** `state.location` foi concebido apenas para descrever a cena (`"Clareira de Treino em Hesiod"`), nunca para guardar estado de jaula aberta. Porém, o `combat_node` tentou usar `state.location = "Arena de Hesiod — Jaula 1 Aberta"` como gambiarra para saber se a luta começou — e como nem sequer retornava `"location"` no dict do nó, essa string nunca persistia.
* **Efeito cascata devastador:**
  1. Em `route_intent`, a checagem `"Aberta" in state.location` dá sempre `False`.
  2. Qualquer mensagem sem dado no meio da luta (`.`, `vai se ferrar`, `😡😡😡`) cai em `exploration_node`!
  3. Como cai em `exploration_node`, ele injeta o `dialogue_history` cheio de mensagens antigas no prompt!
* **Como corrigir sem poluir `location`:** Manter `location` fixo como `"Clareira de Treino em Hesiod"` e verificar se o combate já iniciou pelo estado real da partida (ex: se algum monstro já sofreu dano, se há mais de 1 monstro, ou flag/histórico de abertura da jaula), sem adulterar `location`.

### Causa Raiz B: Monstro morto "ressuscita" do PostgreSQL no turno seguinte
* **Onde:** [`api/ai_core/turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L328) + [`api/motor_rpg/session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L331-L355).
* **O que acontece:** Quando o Bullette chega a `0/8 HP`, a linha 328 faz `state.monsters = [next_beast]`, substituindo a lista em memória apenas pelo Beholder. Quando `persist_session_state_to_db` roda, ele faz `for monster in state.monsters:` — ou seja, ele insere o Beholder no banco, mas **nunca atualiza o Bullette no banco para `hp=0, is_defeated=True`**.
* **Efeito no jogo:** Na mensagem seguinte (`get_or_create_session_state`), o `db.query(Monster).all()` carrega do banco o Bullette ainda com `HP: 5/8` e `is_defeated=False`! O Bullette ressuscita e volta a atacar junto com o Beholder.

### Causa Raiz C: LLM de 30B injetando tags HTML (`<font color="#8B4513">`) e rubricas que estouram os 60 tokens
* **Onde:** [`api/ai_core/prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py#L4-L8) e [`api/motor_rpg/session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L357-L373).
* **O que acontece (visto no log real do container):**
  ```text
  "<font color="#8B4513"><b>Loomis</b></font> <i>inclina a cabeça, olhos brilhando com o brilho de quem já viu muita batalha</i>
  "Vila de Hesiod? Ah, você está longe de casa"
  ```
  E também:
  ```text
  ""<b>Loomis:</b>"
  "<i>Sopro alto e agudo</i> "Guarde esse linguajar para os goblins da mata, recruta! Aqui treinamos com honra e disciplina!"
  Você declarou ataque, mas precisa escolher o alvo e"
  ```
  1. **Por que a mensagem foi cortada em 60 tokens:** 60 tokens é mais que suficiente para 2 frases curtas, **mas** como `BASE_FORMAT_RULES` diz *"Use tags HTML válidas"*, a IA de 30B inventou `<font color="#8B4513"><b>Loomis</b></font>` + rubricas em `<i>...</i>` (`<i>Sopro alto e agudo</i>`), gastando ~40 dos 60 tokens só com tags HTML e descrições de voz antes de responder!
  2. **Envenenamento do Histórico:** Como `persist_session_state_to_db` só salva `recent_messages[-1]` (a resposta do assistente com `<b>Loomis:</b>`), o histórico enviado para a IA tem 5 mensagens seguidas começando com `Loomis: <b>Loomis:</b>`. A IA imita esse padrão e cospe `""<b>Loomis:</b>"`.
* **Como corrigir:**
  - **Proibir HTML e Markdown na saída da LLM:** A LLM deve responder **apenas texto puro** (quem coloca `<b>Loomis:</b>` já é o Python no `turn_graph.py`).
  - Remover a menção a `"voz aguda/anasalada"` das regras de formato para a IA não ficar escrevendo `"Sopro alto e agudo"`.
  - Limpar tags HTML residuais ou prefixos `"Loomis:"` (mesmo entre aspas) no pós-processamento.
  - Salvar também a mensagem do `user` no banco em `persist_session_state_to_db`.

---

## 1. Reanúncio Indevido da Jaula e Falta de Validação de d20 (`ataco com 50` / `ataco com 40`)

* **Sintoma no Jogo:**
  Quando o jogador enviou `ataco com 50` ou `ataco com 40` no meio da luta (com o monstro já em 6/8 ou 1/8 de HP), o Dungeon Master respondeu:
  > *• A Jaula 1 foi aberta e Bullette Faminto entrou na arena [HP: 6/8 | CA: 15]!*
  > *• Raen, declare sua ação e o valor do seu d20 físico (ex: "ataco com 17")!*
  E o Loomis validou o número absurdo na narração (*"Uau, recruta! Um d20 de 50?!"*).

* **Causa Raiz:**
  Em [`api/ai_core/turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L28-L48), a função `extract_d20` filtra apenas inteiros de `1` a `20`. Quando o jogador digita `50`, ela retorna `None`.
  No [`combat_node`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L230-L243), qualquer entrada com `d20 is None` cai no mesmo bloco que anuncia a abertura inicial da jaula e ainda aciona o LLM no final.

* **Correção Proposta:**
  1. Detectar quando o jogador informou um número fora do intervalo `1–20` (ex: regex para números `> 20` ou `<= 0`).
  2. Se a jaula já estiver aberta, não repetir o texto *"A Jaula X foi aberta"*; exibir um aviso direto do Dungeon Master:
     `• Valor inválido! O d20 físico possui apenas valores de 1 a 20. Role novamente, {hero.name}!`
  3. Retornar essa mensagem imediatamente sem chamar o LLM para evitar alucinações sobre dados impossíveis.

---

## 2. Deriva de Idioma para Espanhol (`¡Muy bien!`, `¡Ay, mis pequeños guerreros!`)

* **Sintoma no Jogo:**
  O NPC Loomis começou a misturar expressões e pontuações em espanhol durante as respostas:
  > *"¡Muy bien, recruta!"*
  > *"¡Ay, mis pequeños guerreros!"*

* **Causa Raiz:**
  Modelos multilíngues como o `nvidia/nemotron-3.5-lightning:free` tendem a misturar espanhol e português quando interpretam personas vibrantes/exaltadas se não houver uma restrição explícita de idioma no System Prompt.

* **Correção Proposta:**
  Adicionar uma diretriz estrita em [`api/ai_core/prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py) (`EXPLORATION_PROMPT`, `COMBAT_PROMPT`, `TACTICAL_PROMPT`):
  > *"IDIOMA OBRIGATÓRIO: Responda ESTRITAMENTE em Português do Brasil (pt-BR). É terminantemente proibido utilizar palavras em espanhol (como 'muy bien', 'pequeños', 'ay') ou pontos de exclamação/interrogação invertidos (¡, ¿)."*

---

## 3. Alucinação de Regras e Travas de Diálogo Inexistentes (*"Diga 'SIM, TREINADOR!'"*)

* **Sintoma no Jogo:**
  O Loomis inventou uma condição para prosseguir a batalha:
  > *"Prontos para a próxima rodada? Diga 'SIM, TREINADOR!' ou eu vou ter que chamar o ogro da floresta para ensinar!"*
  Quando o jogador respondeu `sim, treinador`, o motor não avançou o combate (pois não havia rolagem de d20), gerando um loop de diálogo no nó de conselho tático.

* **Causa Raiz:**
  Falta de *negative constraint* no prompt impedindo o NPC de exigir senhas verbais ou confirmações fora de hora quando a jaula já está aberta.

* **Correção Proposta:**
  Incluir nos prompts de Combate e Conselho Tático:
  > *"NUNCA invente comandos ou peça para os jogadores dizerem frases específicas (como 'Sim, treinador!'). Quando a luta já começou, instrua-os apenas a declararem seu ataque junto com o resultado do d20 (de 1 a 20)."*

---

## 4. Troca de Identidade do Atacante na Fala do Loomis

* **Sintoma no Jogo:**
  O jogador **Isaac 2** (controlando **Yarrow**) enviou `ataco com 20`. Porém, na narração de fim de rodada, Loomis deu bronca na **Raen**:
  > *"RAEN! NÃO É 'ATACO COM 20'! É 'USO MEU MACHADO PESADO...'"*

* **Causa Raiz:**
  Em [`api/ai_core/turn_graph.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/turn_graph.py#L457-L460), o contexto enviado ao LLM no `npc_node` contém apenas `Mensagem do jogador: ataco com 20`, sem explicitar qual herói enviou aquela última mensagem. Como a rodada tem múltiplos heróis, o LLM atribuiu a fala ao personagem errado.

* **Correção Proposta:**
  Identificar o herói remetente da última mensagem no `npc_node` e formatar:
  ` Última mensagem enviada por {hero_name}: "{last_user_message}"`

---

## 5. Loomis Contradizendo a Instrução do Dungeon Master

* **Sintoma no Jogo:**
  O Dungeon Master orienta explicitamente: `declare sua ação e o valor do seu d20 físico (ex: "ataco com 17")`.
  Quando o jogador envia `ataco com 10` ou `ataco com 20`, Loomis repreende o jogador dizendo:
  > *"Não é 'ataco com 10', é 'usar nome da habilidade contra o monstro'. Aqui não se brinca com as regras!"*

* **Causa Raiz:**
  O prompt atual do Loomis incentiva cobrança excessiva de roleplay descritivo, entrando em atrito com o comando prático ensinado pelo próprio bot.

* **Correção Proposta:**
  Ajustar o [`COMBAT_PROMPT`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py) para que Loomis **elogie ou comente o resultado mecânico do golpe** (narrando a ação da arma/magia por conta própria com base no resumo do DM), **jamais** repreendendo o jogador por usar o comando curto `ataco com X`.

---

## 6. Entradas de Ruído (`.`) e Ausência de Guardrail Pré-Grafo para Ofensas

* **Sintoma no Jogo:**
  1. A mensagem `.` acionou chamada completa ao LLM via `tactical_advice_node`.
  2. A mensagem `vai se ferrar` não foi barrada antes do grafo: na 1ª vez caiu em `combat_node` (reabrindo o anúncio da Jaula 1) e na 2ª vez acionou geração de texto no `tactical_advice_node`.

* **Correção Proposta:**
  1. **Filtro de ruído/vazio:** Ignorar ou responder estaticamente mensagens com menos de 2 caracteres alfanuméricos (como `.`, `?`, `!`) sem gastar chamadas de LLM.
  2. **Guardrail determinístico de entrada:** Interceptar palavrões/ofensas por regex logo na entrada (antes de classificar intenção ou rodar nós mecânicos), retornando uma repreensão curta e padronizada do treinador Loomis sem alterar o estado da arena nem reexibir abertura de jaula.

---

## 7. Verbosidade Excessiva no Onboarding (`/start`, `/reset`, `/select`) e Inconsistência na Ficha

* **Sintoma no Jogo:**
  1. **Flood no chat no `/reset` e `/start`:** O `/reset` dispara duas mensagens seguidas (aviso de reset + lista gigante de 15 linhas detalhando todos os status e poderes das 5 cartas).
  2. **Repetição verbosa a cada `/select`:** Quando cada jogador escolhe sua carta (ex: `/select 4`), o bot responde um bloco de 6 linhas repetindo todos os atributos que já apareceram no menu inicial, poluindo a tela do grupo no Telegram.
  3. **Divergência no poder do Yarrow (#4):** No menu do [`telegram_service.py`](file:///home/isaac/Documents/mc030/ai-npc/telegram_bot/telegram_service.py#L166-L167), o poder de Yarrow está descrito como *"Espírito da Floresta (cura ou suporte)"*, mas na ficha real em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L104-L111) / `motor_rpg.py` aparece como *"Grilhões Espectrais (Prende o monstro ao solo se errar o ataque)"* — o que inclusive fez o LLM alucinar que Yarrow tinha poder de cura!

* **Correção Proposta:**
  1. **Enxugar o menu `/start` e unificar o `/reset`:** Exibir uma lista limpa de 1 linha por herói (ex: `• /select 1 — Evindol (Ladino | HP 3 | CA 11 | Atq +6)`) e enviar apenas **uma** mensagem consolidada no `/reset`.
  2. **Compactar a confirmação do `/select` em [`session_service.py`](file:///home/isaac/Documents/mc030/ai-npc/api/motor_rpg/session_service.py#L104-L111):** Reduzir de 6 linhas para uma confirmação enxuta de 1–2 linhas:
     `✅ <b>Isaac 2</b> escolheu <b>#4 Yarrow</b> (Xamã | HP 6/6 | CA 10 | Atq +3). Quando todos escolherem, usem /done!`
  3. **Sincronizar os poderes das cartas:** Garantir que o menu do Telegram consuma diretamente os dados de `HERO_ARCHETYPES` do `motor_rpg.py` (Single Source of Truth) para nunca divergir.

---

## Checklist de Execução

- [ ] **1.** Tratar números de d20 fora do intervalo `1–20` no `combat_node` sem reanunciar abertura de jaula e sem chamar LLM.
- [ ] **2.** Separar a mensagem de *"Jaula X foi aberta"* (apenas na transição real de fechada -> aberta) da mensagem de *"Faltou informar o valor do d20 (1 a 20)"*.
- [ ] **3.** Atualizar [`api/ai_core/prompts.py`](file:///home/isaac/Documents/mc030/ai-npc/api/ai_core/prompts.py) com trava estrita de Português (pt-BR), proibição de comandos inventados (*"Diga SIM, TREINADOR"*) e aceitação de comandos curtos (`ataco com X`).
- [ ] **4.** Incluir o nome do herói autor da última mensagem no prompt do `npc_node`.
- [ ] **5.** Adicionar filtro inicial para mensagens de pontuação isolada (`.`) e guardrail determinístico para ofensas antes do roteamento do grafo.
- [ ] **6.** Enxugar mensagens de `/start`, `/reset` e `/select` e unificar a descrição dos poderes com `HERO_ARCHETYPES`.
