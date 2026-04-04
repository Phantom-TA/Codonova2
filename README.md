# Codonova 🤖

**Autonomous Software Development System** powered by deep AI agents, a Neo4j knowledge graph, ChromaDB memory, and a real-time React dashboard.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-blue?logo=react)](https://reactjs.org)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-green?logo=neo4j)](https://neo4j.com)

## What It Does

Codonova autonomously:
1. **Plans** — Analyzes requirements, extracts features, decomposes into tasks with dependencies
2. **Develops** — Generates production-quality Python code using Gemini 2.5 Flash
3. **Tests** — Auto-generates and runs pytest test suites using Groq Llama 4 Scout
4. **Debugs** — Performs root-cause analysis and applies fixes using Gemini
5. **Evaluates** — Scores output 0-10 on correctness, quality, completeness
6. **Self-corrects** — Retries failing code up to 3 times with critique-augmented prompts
7. **Learns** — Stores successful patterns in ChromaDB for future context injection

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  React Dashboard                     │
│  [Task Graph] [Agent Feed] [Code] [Scores] [Insights]│
└──────────────────────┬──────────────────────────────┘
                       │ REST + WebSocket
┌──────────────────────▼──────────────────────────────┐
│                  FastAPI Backend                     │
│                                                     │
│  PlanningAgent (Gemini)  → DecomposesRequirements  │
│  Scheduler               → Routes tasks             │
│  DeveloperAgent (Gemini) → Generates code           │
│  TestingAgent (Groq)     → Writes+runs tests        │
│  DebuggingAgent (Gemini) → Fixes failures           │
│  EvaluatorAgent (Groq)   → Scores output            │
│  CorrectionEngine        → Self-correction loop     │
└────────┬─────────────────────────┬──────────────────┘
         │ Neo4j Cypher            │ ChromaDB
┌────────▼──────────┐   ┌──────────▼──────────────────┐
│   Neo4j Graph DB  │   │  ChromaDB Vector Store       │
│  (Task knowledge) │   │  (sentence-transformers)      │
└───────────────────┘   └──────────────────────────────┘
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- API keys (all free):
  - [Google AI Studio](https://aistudio.google.com) → Gemini 2.5 Flash
  - [Groq Cloud](https://console.groq.com) → Llama 4 Scout
  - [OpenRouter](https://openrouter.ai) → Fallback (optional)

### 1. Configure Environment

```bash
cd autonomousdev
cp .env.example .env
# Edit .env and fill in your API keys and Neo4j password
```

`.env` required fields:
```env
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
NEO4J_PASSWORD=choose_a_password
```

### 2. Start with Docker Compose

```bash
docker-compose up -d
```

Services start in order: Neo4j → ChromaDB → Backend → Frontend

### 3. Verify Services

| Service   | URL                           | Purpose                |
|-----------|-------------------------------|------------------------|
| Dashboard | http://localhost:3000         | React UI               |
| API Docs  | http://localhost:8000/docs    | Swagger UI             |
| Neo4j     | http://localhost:7474         | Graph Browser          |
| ChromaDB  | http://localhost:8001         | Vector DB              |

### 4. Run Without Docker (Development)

**Backend:**
```bash
cd autonomousdev/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd autonomousdev/frontend
npm install
npm run dev  # runs on http://localhost:3000
```

## Usage

### Via Dashboard
1. Open http://localhost:3000
2. Enter a requirement in the launcher (right panel)
3. Click **🚀 Start Autonomous Pipeline**
4. Watch the Task Graph panel fill with nodes
5. Monitor live events in the Agent Feed panel
6. View generated code in the Code Viewer
7. Download the ZIP export when complete

### Via API

**Plan only:**
```bash
curl -X POST http://localhost:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Build a REST API for a task management app"}'
```

**Full pipeline:**
```bash
curl -X POST http://localhost:8000/api/start \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Build a REST API for a student grade management system with endpoints to add students, record grades, and calculate GPA. Use FastAPI and SQLite."}'
```

**Check status:**
```bash
curl http://localhost:8000/api/status/{project_id}
```

**Download export:**
```bash
curl -O http://localhost:8000/api/export/{project_id}
```

## LLM Configuration

| Agent           | Provider | Model                         | Why |
|-----------------|----------|-------------------------------|-----|
| Planning        | Gemini   | gemini-2.5-flash              | Deep reasoning |
| Developer       | Gemini   | gemini-2.5-flash              | Code generation |
| Debugger        | Gemini   | gemini-2.5-flash              | Root-cause analysis |
| Testing         | Groq     | llama-4-scout-17b-16e-instruct| Speed + volume |
| Evaluator       | Groq     | llama-4-scout-17b-16e-instruct| Speed + volume |
| Fallback (all)  | OpenRouter| meta-llama/llama-4-scout:free | Rate limit backup |

## Neo4j Graph Schema

```
Project ──HAS_FEATURE──► Feature ──HAS_TASK──► Task ──HAS_SUBTASK──► SubTask
                                                 │
                                          ◄DEPENDS_ON
                                                 │
                                       CodeModule ──PRODUCED_BY──► Task
                                          │
                                     TestResult ──VALIDATES──► CodeModule
                                          │
                            Bug ──FAILED_BY──► CodeModule
                             │
                           Fix ──RESOLVES──► Bug
                                          │
                          EvaluationResult ──EVALUATES──► CodeModule
                                          │
                         LearningNode ──PRODUCED_BY──► Task
                              │
                         Agent ──LEARNED_FROM──► LearningNode
```

## File Structure

```
autonomousdev/
├── backend/
│   ├── agents/
│   │   ├── planning_agent.py      # Gemini — requirement decomposition
│   │   ├── developer_agent.py     # Gemini — code generation
│   │   ├── testing_agent.py       # Groq   — test gen + execution
│   │   ├── debugging_agent.py     # Gemini — root cause + fix
│   │   ├── evaluator_agent.py     # Groq   — quality scoring
│   │   ├── correction_engine.py   # Self-correction loop orchestrator
│   │   └── scheduler.py           # Task polling + routing
│   ├── graph/
│   │   └── neo4j_client.py        # All Cypher queries
│   ├── memory/
│   │   ├── memory_store.py        # ChromaDB + sentence-transformers
│   │   └── context_retriever.py   # Similar context finder
│   ├── llm_client.py              # Shared LLM client (NEVER bypass this)
│   ├── main.py                    # FastAPI app + all routes
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx                # Main dashboard
│       └── components/
│           ├── TaskGraph.jsx      # Force graph visualization
│           ├── AgentFeed.jsx      # Live WebSocket feed
│           ├── CodeViewer.jsx     # Syntax-highlighted code
│           ├── EvalChart.jsx      # Score charts
│           └── InsightsPanel.jsx  # Neo4j analytics
├── docker-compose.yml
├── PHASE_1_SUMMARY.md ... PHASE_5_SUMMARY.md
└── .env.example
```

## Generated Output

The ZIP export (`GET /api/export/{project_id}`) contains:
- `src/` — all generated Python source files
- `requirements.txt` — auto-detected dependencies
- `README.md` — project overview generated by Gemini
- `test_report.json` — full pytest results
- `EVALUATION_REPORT.md` — per-module quality scores

---

Built with ❤️ by **Codonova** — Autonomous AI Software Development
