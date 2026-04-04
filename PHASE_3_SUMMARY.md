# Phase 3 Summary — Feedback Loop & Self-Correction

## What Was Built

### Evaluator Agent (`backend/agents/evaluator_agent.py`)
- Uses Groq Llama 4 Scout (fast, low-cost)
- Scores each CodeModule on 3 dimensions (0-10 each):
  - **Correctness** — logic correctness, no obvious bugs (weight 50%)
  - **Code Quality** — PEP8, naming, no duplication, error handling (weight 30%)
  - **Completeness** — meets acceptance criteria (weight 20%)
- Returns `{scores, score, critique, suggestions, strengths, passed}`
- Stores EvaluationResult node linked to CodeModule in Neo4j

### Correction Engine (`backend/agents/correction_engine.py`)
- Orchestrates the full retry loop for CODE tasks
- If score < 7.0: retries with critique-augmented prompt (max 3 attempts)
- Each retry = new versioned CodeModule node (v1, v2, v3)
- If tests also fail: runs DebuggingAgent to fix first, then re-evaluates
- If all 3 retries fail:
  - Calls `block_dependent_tasks()` — cascades BLOCKED status via Cypher DEPENDS_ON traversal
  - Creates Decision node documenting the escalation
- On success (score ≥ 7): stores code pattern in ChromaDB + Neo4j LearningNode

### WebSocket Event Stream
- `ws://localhost:8000/ws/progress` — global stream
- `ws://localhost:8000/ws/progress/{project_id}` — project-specific stream
- Events emitted:
  - `{"event": "task_started", "task_id": "...", "agent": "DeveloperAgent"}`
  - `{"event": "task_done", "task_id": "...", "score": 8, "attempt": 1}`
  - `{"event": "task_failed", "task_id": "...", "retry": 2}`
  - `{"event": "pipeline_started", "project_id": "...", "task_count": 18}`
  - `{"event": "project_complete", "project_id": "..."}`
- Auto-reconnect on disconnect (3s delay)
- Heartbeat every 30s to keep connections alive

### Re-planning Logic
Failed task → downstream dependents blocked via:
```cypher
MATCH (t:Task {id: $task_id})<-[:DEPENDS_ON*]-(dep:Task)
WHERE dep.status = 'PENDING'
SET dep.status = 'BLOCKED'
```
Only the failed branch is re-planned, not the entire project.
