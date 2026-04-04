# Phase 2 Summary — Execution Agents (Dev, Test, Debug)

## What Was Built

### Task Scheduler (`backend/agents/scheduler.py`)
- Polls Neo4j every 10 seconds for PENDING tasks
- Respects DEPENDS_ON edges — only dispatches when all dependencies are DONE
- Routes by task type: CODE → CorrectionEngine, TEST → TestingAgent, DEBUG → DebuggingAgent
- Runs up to 3 tasks concurrently with asyncio.gather
- Detects project completion and calls finalize_project()

### Developer Agent (`backend/agents/developer_agent.py`)
- Uses Gemini 2.5 Flash via llm_call("reasoning", ...)
- Reads parent feature, acceptance criteria, and sibling tasks from Neo4j for full context
- Injects similar past solutions from ChromaDB memory as few-shot examples
- Returns `{filename, code, explanation, module_type, dependencies}`
- Writes code to `generated_code/` filesystem
- Creates CodeModule node in Neo4j with PRODUCED_BY → Task relationship
- `run_with_critique()` method for retry attempts (versioned v2, v3)

### Testing Agent (`backend/agents/testing_agent.py`)
- Uses Groq Llama 4 Scout via llm_call("fast", ...)
- Generates pytest test suites for CodeModule files
- Runs via subprocess: `pytest --json-report`
- Parses JSON test report for pass/fail counts and error messages
- Creates TestCase nodes and TestResult node in Neo4j
- Links TestResult -[VALIDATES]-> CodeModule

### Debugging Agent (`backend/agents/debugging_agent.py`)
- Uses Gemini 2.5 Flash via llm_call("reasoning", ...)
- **Call 1**: Chain-of-thought root cause analysis → `{root_cause, error_type, chain_of_thought, fix_strategy}`
- **Call 2**: Complete corrected code → `{filename, code, changes_made}`
- Backs up original file before applying fix
- Creates Bug node and Fix node in Neo4j
- Bug -[RESOLVES]-> Fix, Bug -[FAILED_BY]-> CodeModule

## End-to-End Flow
```
CODE task ready → DeveloperAgent → writes code → TestingAgent → runs pytest
  ↓ tests fail
DebuggingAgent → root cause analysis → corrected code → re-run tests
```
