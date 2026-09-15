# Arquitetura do Sistema: AI-NPC (The Heroes of Hesiod)

Este documento detalha a arquitetura de ponta a ponta, a modelagem de estado e o ciclo de vida dos fluxos do sistema de NPC Conversacional integrado com Telegram e IA.

---

## 1. Arquitetura de Ponta a Ponta

O diagrama a seguir detalha a interação entre os jogadores no Telegram, o túnel de rede, a aplicação FastAPI, o motor determinístico de RPG, o núcleo de IA (LangGraph) e o banco de dados:

```mermaid
flowchart TD
    subgraph CamadaCliente["1. Camada de Cliente"]
        User["Jogador(es) (Usuário do Telegram)"]
    end

    subgraph CamadaIngress["2. Entrada & Rede"]
        Cloudflare["Cloudflare Tunnel (Webhook Público)"]
    end

    subgraph CamadaBackend["3. Backend (FastAPI)"]
        direction TB
        Main["Entrada FastAPI (api/main.py)"]
        BotService["Serviço do Telegram (telegram_bot/)"]
        
        subgraph MotorRPG["Motor RPG (api/motor_rpg/) - Murillo"]
            Session["Gerenciador de Sessões & Grupos"]
            Rules["Regras de Jogo & Motor de Dados (d20 vs CA)"]
        end

        subgraph AICore["Núcleo de IA (api/ai_core/) - Isaac"]
            GraphState["RPGGraphState (Schemas Compartilhados)"]
            LangGraph["Fluxo do LangGraph"]
            LoomisNode["Nó do Loomis (Prompt / Diálogo em 1ª Pessoa)"]
        end
    end

    subgraph ServicosExternos["4. Serviços Externos & Persistência"]
        DB[(PostgreSQL + pgvector)]
        Gateway["LLM Gateway (llm_gateway/)"]
        LLM["Provedores LLM (OpenAI / Gemini)"]
    end

    %% Conexões
    User <-->|Mensagem / Comando| Cloudflare
    Cloudflare -->|POST /webhook| Main
    Main --> BotService
    BotService <--> Session
    Session <--> Rules
    Session <--> DB

    %% Ciclo de IA
    BotService -->|process_npc_turn| LangGraph
    LangGraph <--> GraphState
    LangGraph <--> Rules
    LangGraph --> LoomisNode
    LoomisNode --> Gateway
    Gateway <--> LLM
    Gateway -->|Diálogo Gerado| BotService
```

---

## 2. Modelagem de Estado (`RPGGraphState`)

A estrutura de dados a seguir suporta tanto partidas individuais (*single-player*) quanto sessões cooperativas (*multiplayer*):

```mermaid
classDiagram
    class RPGGraphState {
        +str session_id
        +list~HeroState~ players
        +str current_turn
        +MonsterState current_monster
        +int cage_number
        +list~Message~ history
        +str current_intent
        +str loomis_response
    }

    class HeroState {
        +str player_id
        +str name
        +str class_name
        +int hp
        +int max_hp
        +int ac
    }

    class MonsterState {
        +str name
        +int hp
        +int max_hp
        +int ac
        +bool is_defeated
    }

    RPGGraphState "1" *-- "1..*" HeroState : rastreia
    RPGGraphState "1" *-- "1" MonsterState : enfrenta
```

### Dinâmica de Turnos e Rodadas (*Turns vs. Rounds*)
* **`current_turn`:** Identifica quem possui a vez de agir (o `player_id` do herói da vez ou `"monster"`).
* **Turno (*Turn*) vs. Rodada (*Round*):**
  * **Turno:** A janela de ação individual de um participante (o golpe de um jogador ou a investida do monstro). Loomis reage e narra imediatamente a cada turno no Telegram para garantir retorno instantâneo.
  * **Rodada:** O ciclo completo após **todos** os participantes (todos os heróis ativos do grupo + a criatura da jaula) terem executado seus turnos.

---

## 3. Ciclo de Vida e Transições no LangGraph

O fluxo de execução de uma requisição pelo grafo cognitivo do Loomis:

```mermaid
stateDiagram-v2
    [*] --> Ocioso : Jogador envia mensagem
    Ocioso --> ClassificarIntencao : Extrai intenção
    
    state checagem_intencao <<choice>>
    ClassificarIntencao --> checagem_intencao
    
    checagem_intencao --> MotorCombate : intencao == 'atacar'
    checagem_intencao --> DicaTatica : intencao == 'conversar'
    
    MotorCombate --> NarracaoLoomis : Rolagem de dados resolvida
    DicaTatica --> NarracaoLoomis : Dica tática pronta
    
    NarracaoLoomis --> TurnoConcluido : Fala do NPC gerada
    TurnoConcluido --> [*]
```
