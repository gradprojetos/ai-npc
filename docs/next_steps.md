# Próximos Passos: Correções de Fluxo e Imersão

Este documento consolida os 6 fixes prioritários identificados nas sessões de teste manual na arena:

---

## 1. Trava de Tática na Exploração (Anti-Spoil de Combate)
* **Problema:** Perguntas sobre itens ou poções na clareira dispararam `tactical_advice`, fazendo Loomis citar o Bullette e fraquezas de combate com as jaulas trancadas.
* **Correção:** Em `route_intent`, enquanto o combate não estiver ativo (`not beast_in_arena`), redirecionar qualquer classificação `tactical_advice` para `exploration`.

---

## 2. Ampliação do Limite e Janela de Histórico na Exploração
* **Problema:** O gatilho de impaciência ativava com apenas 4 mensagens e a janela de contexto enviava apenas 5 mensagens anteriores (`[-6:-1]`).
* **Correção:** Aumentar o limite de exploração livre (impaciência apenas após 10 mensagens, abertura forçada após 15), ampliar o histórico enviado à LLM para 10 mensagens (`[-11:-1]`) e reconhecer confirmações curtas (*"vamos abrir a jaula"*, *"vamos"*) como prontidão.

---

## 3. Alinhamento Estrito de Armas e Poderes no Nó Tático
* **Problema:** `tactical_advice_node` passava apenas `hero.special_power` e omitia `hero.attack_name`, levando Loomis a alucinar *"golpe de espada"* para a bárbara Raen (que usa Machado Pesado) e trocar poderes entre classes.
* **Correção:** Injetar explicitamente `hero.attack_name` e `hero.special_power` no contexto do nó tático, proibindo citar armas ou poderes de outros heróis.

---

## 4. Aliança dos Monstros e Fim do Fogo Amigo Alucinado
* **Problema:** Loomis narrou que o Dragão Vermelho *"lançou raios no Beholder, deixando ambos feridos"*, criando dano entre monstros aliados.
* **Correção:** Blindar `COMBAT_PROMPT` deixando explícito que todas as feras na arena lutam juntas contra os recrutas e nunca atacam umas às outras.

---

## 5. Tratamento de "Defender" e "Poção" no `TACTICAL_PROMPT`
* **Problema:** Quando o jogador tentava se defender ou beber poção com vida durante a luta, Loomis inventava mecânicas complexas inexistentes.
* **Correção:** Manter esses casos no `tactical_advice_node`, mas instruir Loomis a rebater no estilo treinador: *"Poção? Defender? Na minha arena a melhor defesa é o ataque! Eu só jogo poção para quem desmaia na areia. Use seu [ataque] e seu poder [poder especial] e parta para cima!"*

---

## 6. Memória de Curto Prazo no Conselho Tático
* **Problema:** O nó tático não recebia o histórico recente da conversa, deixando Loomis sem contexto das mensagens anteriores do turno.
* **Correção:** Incluir as últimas mensagens do diálogo também na montagem do prompt do `tactical_advice_node`.
