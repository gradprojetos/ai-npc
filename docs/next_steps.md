# Roadmap de Refinamento de Jogabilidade e UX (next_steps.md)

Este documento detalha o plano de execução focado na **experiência de jogo real (gameplay, clareza mecânica, formatação no Telegram e onboarding multiplayer final)**, resolvendo os problemas identificados nos testes em grupo.

---

## 1. Diagnóstico dos Problemas de Jogabilidade

| Prioridade | Item | Sintoma Atual | Impacto na Experiência | Solução Planejada |
| :---: | :--- | :--- | :--- | :--- |
| **P1** | **1. Mensagens no Grupo** | Bot responde a replies entre jogadores humanos. | Polui a conversa paralela do grupo e gera respostas fora de contexto. | Responder no grupo **apenas** se o bot for mencionado (`@bot`) ou se for reply a uma mensagem do próprio bot. |
| **P1** | **2. Formatação Telegram** | Asteriscos literais `**` vazam no chat sem ficar em negrito. | Mensagem fica poluída e difícil de escanear visualmente. | Migrar a saída para `parse_mode="HTML"` (`<b>`, `<code>`) no Telegram. |
| **P2** | **3. HUD e Vida do Monstro** | Jogador não sabe o HP/CA atual da fera nem dos heróis. | O jogador fica cego taticamente, sem saber se a fera está quase caindo. | Incluir sempre um bloco mecânico claro com a ficha resumida do combate atual. |
| **P2** | **3.5. Separação de Vozes** | Mistura de mecânica determinística com fala do NPC no mesmo texto. | Falta de clareza do que é regra/dado e o que é interpretação do personagem. | Separar visualmente em **Dungeon Master:** (mecânica) e **Loomis:** (fala em 1ª pessoa). |
| **P2** | **4. Turno do Monstro** | Contra-ataque da criatura não fica evidente ou não é reportado. | Combate fica unilateral; herói bate sem sofrer perigo de dano. | Resolver e exibir deterministamente a reação da fera contra o herói com maior HP conforme `game_rules.md`. |
| **P3** | **5. Roleplay do Loomis** | O LLM gera rubricas narrativas em 3ª pessoa (*loomis se abaixa...*). | Confunde narração de mestre com fala do NPC. Loomis deve apenas falar. | Ajustar o prompt para **1ª pessoa estrita**, sem ações cênicas entre asteriscos/parênteses. |
| **P4** | **6. Multiplayer & Onboarding** | Todos os membros do grupo compartilham o mesmo herói genérico (Jorick). | Amigos no mesmo grupo não têm fichas próprias nem alternância de turnos. | Fluxo de Onboarding no grupo onde cada jogador escolhe seu herói (#1 a #5) e a iniciativa é ordenada canonicamente. |

---

## 2. Especificação Detalhada das Tarefas

### Tarefa 1: Filtro Rígido de Interação em Grupos (`telegram_service.py`)
* Em chats privados (`chat.type == "private"`): processa todas as mensagens normalmente.
* Em grupos (`chat.type in ["group", "supergroup"]`):
  * **Ignorar** conversas paralelas e replies entre outros usuários humanos.
  * **Aceitar** somente se:
    1. A mensagem contiver menção explícita ao bot (`@pfg_npc_bot`), limpando a tag antes de processar; **OU**
    2. A mensagem for um **Reply direto** a uma mensagem enviada pelo próprio bot (`message.reply_to_message.from_user.id == bot.id`); **OU**
    3. For um comando de jogo (`/escolher`, `/reset`, `/ajuda`).

---

### Tarefa 2: Formatação HTML Robusta para o Telegram (`telegram_service.py`)
* Configurar o envio no Telegram com `parse_mode="HTML"`.
* Padronizar as tags:
  * `<b>Texto em Negrito</b>`
  * `<code>d20 [15]</code>` para números de dados e valores mecânicos.
  * `<i>Falas ou citações</i>`.
* Fallback gracioso: se a mensagem falhar por erro de tag HTML, reenviar em texto simples sem quebrar a conversa.

---

### Tarefa 3 e 3.5: Separação "Dungeon Master" vs "Loomis" com HUD de Combate
Toda resposta de turno de combate deve ser padronizada no seguinte formato estruturado:

```html
🎲 <b>Dungeon Master:</b>
• <b>Jorick (Isaac)</b> atacou <b>Bullette Faminto</b> com Espada Larga!
• Rolagem: d20 [14] + 4 = 18 vs CA 15 (ACERTOU!)
• Dano: 1 ponto.

⚔️ <b>Contra-ataque da Fera:</b>
• <b>Bullette Faminto</b> atacou <b>Raen (Pedro)</b> com Escavar e Engolir!
• Rolagem: d20 [12] + 4 = 16 vs CA 9 (ACERTOU!)
• Dano sofrido: 1 ponto.

📊 <b>Arena de Hesiod:</b>
• Monstro: Bullette Faminto (Jaula 1) [HP: 6/8 | CA: 15]
• Heróis: Jorick [HP: 5/5] | Raen [HP: 6/7]
• Vez do próximo herói: <b>Raen (Pedro)</b>

🗣️ <b>Loomis:</b>
"Firme o pé, garoto! Não deixe a fera te empurrar contra a grade da jaula!"
```

---

### Tarefa 4: Turno Canônico do Monstro (Conforme Seção 4.1 do `docs/game_rules.md`)
* **Regras Oficiais do Monstro:**
  1. **Alvo com Maior HP:** Monstros buscam desafio e sempre atacam o herói consciente com o **maior HP atual** (ignoram heróis com pouco HP por acharem menos desafiadores).
  2. **Alternância de Alvo:** Quase nunca atacam o mesmo herói duas vezes seguidas se houver outro herói consciente na arena.
  3. **Resolução Mecânica:** Rolagem determinística `1d20 + monster.attack_bonus` vs CA do herói. Acerto causa 1 ponto de dano; 20 natural causa `1d6`.
  4. **Herói a 0 HP:** Herói cai inconsciente. Loomis **espera os heróis vencerem a fera** antes de administrar a poção restauradora (para quem tem $\le 2$ HP).
* **Integração no Fluxo:** O contra-ataque ocorre logo após a ação do herói se a criatura sobreviver, e é exibido na seção do Dungeon Master.

---

### Tarefa 5: Prompt Enxuto de 1ª Pessoa para Loomis (`db/models.py` / migration)
* O modelo não deve gerar ações de cena em 3ª pessoa (ex.: `*Loomis limpa o suor da testa e cospe no chão*`).
* Loomis fala **exclusivamente com sua voz** (em 1ª pessoa: *"Eu quero ver mais força nessa investida!"*).
* A descrição do ambiente e ações físicas de combate é responsabilidade exclusiva do **Dungeon Master**.
* Aplicar filtro no pós-processamento para expurgar rubricas entre asteriscos se o modelo as gerar.

---

### Tarefa 6 (Final): Onboarding Multiplayer no Grupo (`session_service.py` e `telegram_service.py`)
1. **Apresentação dos Heróis de Hesiod:**
   * Ao iniciar o bot ou via `/recrutar`: Loomis apresenta as 5 cartas canônicas numeradas:
     * 🗡️ **#1 Evindol** (Ladino Humano | CA 11 | HP 3 | +6 ataque)
     * 🪓 **#2 Raen** (Bárbara Anã | CA 9 | HP 7 | +5 ataque)
     * ⚔️ **#3 Jorick** (Guerreiro Humano | CA 13 | HP 5 | +4 ataque)
     * 🔮 **#4 Yarrow** (Xamã Meio-Orc | CA 10 | HP 6 | +3 ataque)
     * 🔥 **#5 Bet** (Maga Elfa | CA 7 | HP 4 | +7 ataque)
2. **Escolha de Personagem (`/escolher <1-5>` ou `/escolher <nome>`):**
   * O jogador escolhe seu arquétipo no grupo.
   * Associa o Telegram ID (`user.id`) e o nome do jogador (`user.first_name`) à ficha escolhida.
   * Cada herói só pode ser escolhido por 1 jogador na mesma sessão de grupo.
3. **Iniciativa Automática Canônica (#1 a #5):**
   * A lista `state.players` é mantida automaticamente ordenada pelo número da carta do herói.
   * Quem escolheu o #1 (Evindol) age antes do #2 (Raen), que age antes do #3 (Jorick), etc.
4. **Fallback:** Se uma mensagem de ataque for enviada em grupo sem onboarding prévio, mantém o herói inicial (Jorick) para permitir jogar solo sem atrito.

---

## 3. Ordem de Execução

1. **Passo 1:** Filtro de mensagens no grupo (ignora replies humanos) + Envio com `parse_mode="HTML"`.
2. **Passo 2:** Separação visual com **Dungeon Master**, status da arena (HP/CA do monstro e heróis) e **Loomis**.
3. **Passo 3:** Turno canônico do monstro (contra-ataque na fera viva) e resolução mecânica.
4. **Passo 4:** Prompt de 1ª pessoa estrita de Loomis (higienização de rubricas de cena).
5. **Passo 5:** Onboarding multiplayer no grupo (escolha de heróis e ordenação por carta #1 a #5).
