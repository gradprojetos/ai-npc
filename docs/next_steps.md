# Roadmap de Refinamento de Jogabilidade e UX (next_steps.md)

Este documento detalha o plano de execução focado na **experiência de jogo real (gameplay, clareza mecânica, formatação no Telegram e onboarding multiplayer final)**, resolvendo os problemas identificados nos testes em grupo.

---

## 1. Diagnóstico dos Problemas de Jogabilidade

| Prioridade | Item | Sintoma Atual | Causa Raiz | Solução Planejada |
| :---: | :--- | :--- | :--- | :--- |
| **P1** | **1. Roteamento de Combate** | *"ataco com 19"*, *"atacou com 20"* caem em Dica Tática em vez de Combate. | Regex estática não entende linguagem natural livre de RPG. | Nó classificador de decisão inteligente (via Clef-Flash ou LLM tradicional com JSON estruturado). |
| **P1** | **2. Alucinação de Morte** | LLM disse que o monstro morreu, mas no motor ele estava com 7/8 de vida. | Ausência do Dungeon Master explícito e falta de trava anti-alucinação no prompt do NPC. | Trava rígida no prompt proibindo declarar morte e inclusão do bloco mecânico inquestionável do Dungeon Master. |
| **P1** | **3. Mensagens no Grupo** | Bot responde a conversas paralelas e replies entre humanos. | Falta de filtro de direcionamento no handler. | Ignorar se dirigida a outro humano (via reply ou @), mas aceitar comandos universalmente e falas abertas de jogo. |
| **P1** | **4. Formatação Telegram** | Asteriscos literais `**` vazam no chat sem negrito real. | Telegram API trata Markdown de forma estrita ou requer `parse_mode="HTML"`. | Migrar a saída para `parse_mode="HTML"` (`<b>`, `<code>`, `<i>`). |
| **P2** | **5. HUD e Separação de Vozes** | Jogador não sabe HP/CA do monstro e não distingue regra de roleplay. | Mecânica determinística misturada com texto de IA em um bloco único. | Formatar em **Dungeon Master:** (dados/HP) e **Loomis:** (fala em 1ª pessoa). |
| **P2** | **6. Turno Canônico do Monstro** | Contra-ataque da criatura não é reportado com clareza. | Combate parece unilateral se a fera não revidar imediatamente. | Executar e reportar deterministicamente a reação da fera contra o herói com maior HP conforme `game_rules.md`. |
| **P3** | **7. Roleplay do Loomis** | O LLM gera rubricas narrativas em 3ª pessoa (*loomis se abaixa...*). | Falta de restrição de persona no prompt e falta de sanitização de saída. | Prompt estrito de 1ª pessoa e filtro de expurgo de rubricas entre asteriscos/parênteses. |
| **P4** | **8. Onboarding Multiplayer** | Jogadores compartilham a mesma ficha genérica (Jorick). | Falta de escolha individual de fichas no grupo. | Fluxo com as cartas #1 a #5 e ordenação de iniciativa canônica. |

---

## 2. Especificação Detalhada das Tarefas

### Tarefa 1: Classificador de Intenção Inteligente (Clef-Flash ou LLM Tradicional)
* **Problema:** Regex estática falha miseravelmente em RPG textual porque jogadores usam linguagem natural criativa (*"dou um pulo na parede e ataco ele por cima com 19 de dano"*, *"me esquivo e atacou com 20"*). O sistema interpretou esses ataques como simples conversas táticas e nunca rodou o combate.
* **Solução Arquitetural:**
  * Substituir o roteador de regex por um **nó de decisão inteligente** (`classify_intent_node`) que retorna um schema tipado estrito:
    ```json
    {
      "intent": "combat" | "tactical_advice",
      "d20_roll": 19 | null,
      "power_used": "investida" | "flanquear" | null
    }
    ```
  * **Opção A (LLM Tradicional com Structured Output):** Chamada rápida ao LLM Gateway com `temperature=0`, `max_tokens=40` e prompt estrito de juiz retornando exclusivamente o JSON estruturado acima.
  * O `route_intent` do LangGraph consome diretamente a chave `"intent"` decidida pelo modelo, garantindo 100% de precisão sem desvios acidentais.

---

### Tarefa 2: Trava Anti-Alucinação e Separação "Dungeon Master" vs "Loomis"
* **Dungeon Master (Árbitro Supremo da Verdade):**
  * O bloco do Dungeon Master é gerado pelo código determinístico (não pela LLM).
  * Exibe rolagens, se acertou/errou, dano real infligido, contra-ataque da fera e a ficha da arena.
* **Loomis (Roleplay em 1ª Pessoa):**
  * O system prompt de Loomis ganha regra de segurança inquebrável:
    > *"Você é apenas o treinador Loomis. Você NUNCA decide se um monstro morreu ou sofreu dano. Toda a verdade mecânica pertence exclusivamente ao Dungeon Master. Você só comemora a derrota de uma fera se o contexto contiver expressamente '[MONSTRO DERROTADO]'. Se a fera tiver HP > 0, reaja a ela ainda viva e ameaçadora!"*
  * Remover qualquer rubrica narrativa em 3ª pessoa (*loomis cospe no chão*, *solta um guincho*).

---

### Tarefa 3: Filtro Rígido de Interação em Grupos (`telegram_service.py`)
* **Regra 1: Comandos são Universais (Sempre Processados):**
  * Qualquer comando de jogo (mensagens iniciando com `/`, ex: `/reset`, `/escolher`, `/ajuda`) deve ser recebido e processado obrigatoriamente pelo chatbot, **independente de a quem foi dirigida a mensagem ou se foi enviada em reply a outro usuário**.
  * *Nota de Design:* O comando `/start` **não existe** no jogo canônico de Hesiod (apenas `/reset`, `/escolher`, `/ajuda`, etc.).
* **Regra 2: Mensagens Dirigidas a Outros Humanos NÃO são Respondidas pela IA:**
  * Em grupos (`chat.type in ["group", "supergroup"]`), uma mensagem de texto (não-comando) **NUNCA** pode ser respondida pela IA se for dirigida a outra pessoa:
    1. **Se for Reply a outro usuário humano** (`message.reply_to_message.from_user.id != bot.id`); **OU**
    2. **Se contiver menção `@` a outro usuário** que não seja o bot (`@pfg_npc_bot`).
* **Regra 3: Falas Abertas do Jogo:**
  * Mensagens normais de RPG enviadas no chat em grupo (ex: *"ataco com 19"*, *"o que vemos na jaula?"*) que **não** foram dirigidas a outra pessoa com reply ou menção continuam sendo recebidas e processadas pela IA/DM normalmente.

---

### Tarefa 4: Formatação HTML e HUD de Combate no Telegram (`telegram_service.py` / `turn_graph.py`)
* Migrar o envio para `parse_mode="HTML"`.
* Template estruturado padrão de combate:

```html
🎲 <b>Dungeon Master:</b>
• <b>Jorick</b> atacou <b>Bullette Faminto</b> com Espada Larga!
• Rolagem: d20 [19] + 4 = 23 vs CA 15 (ACERTOU!)
• Dano: 1 ponto.

⚔️ <b>Contra-ataque da Fera:</b>
• <b>Bullette Faminto</b> atacou <b>Jorick</b> com Escavar e Engolir!
• Rolagem: d20 [12] + 4 = 16 vs CA 13 (ACERTOU!)
• Dano sofrido: 1 ponto.

📊 <b>Arena de Hesiod:</b>
• Monstro: <b>Bullette Faminto</b> (Jaula 1) [HP: 6/8 | CA: 15]
• Heróis: <b>Jorick</b> [HP: 4/5]
• Status: <i>Fera ferida e furiosa na arena!</i>

🗣️ <b>Loomis:</b>
"Bom golpe, garoto! Mas não baixe a guarda, essa carapaça de pedra ainda tem muita luta pela frente!"
```

---

### Tarefa 5: Turno Canônico do Monstro (Conforme Seção 4.1 do `docs/game_rules.md`)
* Se a fera sobreviver ao golpe do herói (`not monster.is_defeated`):
  1. Monstro escolhe como alvo o herói consciente com o **maior HP atual** (evitando repetir o mesmo alvo se houver alternativa).
  2. Rola deterministamente `1d20 + attack_bonus` vs CA do herói.
  3. Dano normal: 1 ponto (crítico: `1d6`).
  4. Se o herói cair a 0 HP: fica inconsciente. Loomis aguarda a vitória contra a fera para medicar quem tem $\le 2$ HP.

---

### Tarefa 6 (Final): Onboarding Multiplayer no Grupo
* Ao iniciar ou via `/recrutar`: Loomis apresenta as 5 cartas canônicas (#1 Evindol, #2 Raen, #3 Jorick, #4 Yarrow, #5 Bet).
* Cada jogador usa `/escolher <1-5>` no grupo.
* Associa o `telegram_id` e nome do jogador ao herói (fichas únicas por grupo).
* Fila de turnos (`state.players`) ordenada canonicamente pelo número da carta.

---

## 3. Ordem de Execução Recomendada

1. **Passo 1 (Classificador de Intenção Inteligente):** Implementar o nó de decisão (`classify_intent_node`) com modelo estruturado (JSON schema com `intent`, `d20_roll`) via Clef-Flash ou LLM tradicional com `temperature=0`.
2. **Passo 2 (UX Telegram & Grupo):** Filtro de replies no grupo + envio com `parse_mode="HTML"`.
3. **Passo 3 (Dungeon Master & HUD):** Template fixo com rolagem, dano, contra-ataque do monstro e HP/CA da arena.
4. **Passo 4 (Trava de Persona de Loomis):** Prompt rígido proibindo declarar mortes ou gerar rubricas em 3ª pessoa.
5. **Passo 5 (Onboarding Multiplayer Final):** Escolha de cartas #1 a #5 e ordenação de iniciativa.
