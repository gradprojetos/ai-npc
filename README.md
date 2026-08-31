# Sistema de NPC conversacional para RPGs educacionais

## Roadmap (4 Meses)

### Equipe
- **Estudante 1 (Foco em IA, NLP e Dados):** Isaac
- **Estudante 2 (Foco em Backend, Integração e Infra):** Murillo

### Mês 1: Agosto (Fundamentação e Setup Base)
**Estudante 1:**
- Sobe o LLM Gateway (API do IC) e realiza testes básicos de chamadas de IA.

**Estudante 2:**
- Sobe o PostgreSQL, cria os esquemas das tabelas e configura o esqueleto da API Interna (FastAPI).

**Ambos:**
- Criação do repositório, configuração do Docker Compose e conexão inicial do Telegram Bot ecoando mensagens para a API Interna.

### Mês 2: Setembro (Lógica de Jogo e Memória)
**Estudante 1:**
- Implementa o fluxo básico do LangGraph (Estado RPGGraphState).

**Estudante 2:**
- Implementa as rotas de criação de sessão e o Motor de RPG (atualização de atributos e progressão).

**Ambos:**
- O Bot do Telegram já consegue conversar com o LLM através da API Interna, lendo o estado base do jogo.

### Mês 3: Outubro (Integração e Guardrails)
**Estudante 1:**
- Desenvolve e acopla o contêiner do Motor de Guardrails no fluxo, testando bloqueios semânticos e validações pedagógicas (Nvidia Guardrail).

**Estudante 2:**
- Finaliza a orquestração assíncrona na API Interna (roteamento completo: Telegram → FastAPI → Guardrail → LangGraph → Banco → LLM → Telegram).

**Ambos:**
- Testes de integração. O sistema deve barrar respostas erradas e atualizar o estado do jogo e o inventário automaticamente.

### Mês 4: Novembro (Validação e Relatório)
**Estudante 1:**
- Tuning de prompts e métricas de qualidade (avaliação de coerência do NPC e dos limites do guardrail), Langfuse.

**Estudante 2:**
- Testes de carga, tratamento de concorrência e logs de erro, Langfuse.

**Ambos:**
- Playtesting (sessões testes no Telegram com usuários), coleta de dados, correção de falhas e redação final do PFG.

---

## Estrutura do Projeto

### Organização por Serviços

Cada serviço tem sua própria pasta, seu próprio `Dockerfile` e seu próprio arquivo de dependências (`requirements.txt`, `pyproject.toml`, etc.). Se o Estudante 1 mexe no Guardrail e o Estudante 2 no Bot, eles nunca tocarão nos mesmos arquivos.

```
meu-projeto-rpg/
├── docker-compose.yml          # Propriedade compartilhada
├── /telegram-bot               # Domínio do E2
├── /motor-guardrails           # Domínio do E1
├── /llm-gateway                # Domínio do E1
├── /db-init                    # Scripts SQL (Domínio do E2)
└── /api-interna                # Área de Interseção (Atenção aqui)
```

### Tratando a Área de Interseção (/api-interna)

A `api-interna` é o único lugar onde os dois vão trabalhar juntos (E2 faz as rotas e regras do RPG, E1 faz o grafo do LangGraph). Para não dar conflito nessa pasta, separe a aplicação em módulos isolados:

```
/api-interna
├── /routers            # E2: Endpoints REST/WebSockets (entrada do Telegram)
├── /motor_rpg          # E2: Lógica de estado e consultas ao banco
├── /ia_core            # E1: Nós do LangGraph e integração com pgvector
├── /schemas            # Compartilhado: Modelos Pydantic (os contratos)
└── main.py             # E2: Apenas importa os routers
```

**Convenção de Trabalho:**
- **E1 (Isaac):** Trabalha em `/ia_core/` e garante que os nós do LangGraph recebem e retornam dados conforme os modelos Pydantic definidos em `/schemas/`.
- **E2 (Murillo):** Trabalha em `/routers/` e `/motor_rpg/`, garantindo que os endpoints chamam os nós de IA de forma correta.
- **Compartilhado:** `/schemas/` contém os contratos de dados. Qualquer mudança aqui é comunicada para o outro para evitar incompatibilidades.
