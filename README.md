# Sistema de NPC Conversacional para RPGs Educacionais

Sistema de NPCs com IA conversacional para jogos educacionais, integrado com Telegram e LLMs. Desenvolvimento em paralelo com separação clara de responsabilidades.

---

## 👥 Equipe

| Função | Responsável |
|--------|------------|
| **IA, NLP e Dados** | Isaac |
| **Backend, Integração e Infra** | Murillo |

---

## 📅 Roadmap (4 Meses)

| Mês | Foco | Isaac | Murillo | Entrega |
|-----|------|-------|---------|---------|
| **Ago** | Setup | LLM Gateway + testes | PostgreSQL + FastAPI | Bot ecoando mensagens |
| **Set** | Lógica | LangGraph (RPGGraphState) | Motor RPG + rotas | Bot conversando com IA |
| **Out** | Integração | Motor Guardrails (Nvidia) | Orquestração assíncrona | Sistema com validações |
| **Nov** | Validação | Tuning + métricas (Langfuse) | Testes de carga (Langfuse) | Playtesting + PFG |

---

## 🏗️ Arquitetura

### Estrutura de Pastas

```
projeto-rpg/
├── docker-compose.yml          # Compartilhado
├── /telegram-bot               # E2
├── /motor-guardrails           # E1
├── /llm-gateway                # E1
├── /db-init                    # E2
└── /api-interna                # Ambos (módulos isolados)
```

### Módulos da API Interna

```
/api-interna
├── /routers            # E2: Endpoints REST/WebSockets
├── /motor_rpg          # E2: Lógica de estado e banco
├── /ia_core            # E1: LangGraph + pgvector
├── /schemas            # Ambos: Modelos Pydantic
└── main.py             # E2: Orquestra tudo
```

**Regra de Ouro:** Cada estudante trabalha em seu domínio sem mexer no do outro. Apenas `/schemas/` é compartilhado (comunicar mudanças!).

---

## 🚀 Começar

```bash
# Clonar e configurar
git clone https://github.com/gradprojetos/ai-npc.git
cd ai-npc

# Docker
docker-compose up

# Testes
pytest
```

---

## 📦 Stack Técnico

- **LLM:** LangGraph, LLM Gateway (IC)
- **Backend:** FastAPI, PostgreSQL, pgvector
- **Telegram:** python-telegram-bot
- **Guardrails:** Nvidia Guardrail
- **Observabilidade:** Langfuse
- **Deploy:** Docker, Docker Compose
