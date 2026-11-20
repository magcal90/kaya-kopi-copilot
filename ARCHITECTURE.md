# Kaya Kopi Ops Copilot Architecture

This diagram describes the architecture currently implemented in the project.

```mermaid
flowchart LR
    User[Operations User]

    subgraph Sources[Client Data Sources]
        POS[POS MySQL Dump]
        CSV[Outlet CSVs]
        XLSX[Staff Roster XLSX]
        IMG[Invoice Images]
        DOC[Email and WhatsApp]
    end

    subgraph Pipeline[Ingestion Pipeline]
        Parsers[Python Parsers]
        OCR[PaddleOCR]
        Loader[Idempotent MySQL Loader]
    end

    subgraph Storage[Data Storage]
        MySQL[(MySQL 8<br/>Business Data and Evidence)]
        SQLite[(SQLite<br/>LangGraph Chat Checkpoints)]
    end

    subgraph Copilot[Kaya Kopi Ops Copilot]
        UI[Streamlit UI]
        Graph[LangGraph Chat Workflow]
        LLM[OpenAI Chat Model]
        Tools[Read-only Business Tools]
        Repo[MySQL Repository]
    end

    POS --> MySQL
    CSV --> Parsers
    XLSX --> Parsers
    DOC --> Parsers
    IMG --> OCR
    OCR --> Parsers
    Parsers --> Loader
    Loader --> MySQL

    User <--> UI
    UI <--> Graph
    Graph <--> LLM
    Graph <--> Tools
    Tools --> Repo
    Repo --> MySQL
    MySQL -->|Grounded results and citations| Repo
    Graph <--> SQLite
```

MySQL stores operational data and citable evidence. SQLite is used only by LangGraph to persist chat messages and workflow checkpoints by conversation thread. The copilot accesses business data through read-only tools and does not modify client records.
