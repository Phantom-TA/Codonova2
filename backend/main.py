"""
main.py — Codonova FastAPI Application
=======================================
All REST endpoints and WebSocket for the autonomous development system.

Routes:
  POST /api/plan                  → Run planning agent
  POST /api/start                 → Start full pipeline
  GET  /api/status/{project_id}   → Pipeline status
  GET  /api/graph/{project_id}    → Task graph (nodes + links)
  GET  /api/export/{project_id}   → ZIP export
  GET  /api/insights              → Neo4j analytics
  GET  /api/llm-log               → LLM call history
  GET  /health                    → Health check
  WS   /ws/progress               → Real-time event stream
"""

import os
import io
import json
import asyncio
import logging
import zipfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

app = FastAPI(
    title="Codonova API",
    description="Autonomous Software Development System powered by AI agents and Neo4j",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GENERATED_CODE_DIR = Path(os.getenv("GENERATED_CODE_DIR", "./generated_code"))
GENERATED_CODE_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────
# WebSocket Manager
# ─────────────────────────────────────────
class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.global_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, project_id: str = None):
        await websocket.accept()
        if project_id:
            if project_id not in self.active_connections:
                self.active_connections[project_id] = []
            self.active_connections[project_id].append(websocket)
        else:
            self.global_connections.append(websocket)

    def disconnect(self, websocket: WebSocket, project_id: str = None):
        if project_id and project_id in self.active_connections:
            try:
                self.active_connections[project_id].remove(websocket)
            except ValueError:
                pass
        else:
            try:
                self.global_connections.remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, message: str, project_id: str = None):
        """Broadcast to all connections (or project-specific ones)."""
        targets = []
        if project_id and project_id in self.active_connections:
            targets = self.active_connections[project_id]
        targets += self.global_connections

        dead = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, project_id)


ws_manager = ConnectionManager()


async def broadcast_event(message: str):
    """Global broadcaster used by agents."""
    await ws_manager.broadcast(message)


# ─────────────────────────────────────────
# Startup
# ─────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Initialize Neo4j schema and agent nodes on startup."""
    try:
        import graph.neo4j_client as neo4j_client

        neo4j_client.initialize_schema()

        for agent_name in [
            "PlanningAgent", "DeveloperAgent", "TestingAgent",
            "DebuggingAgent", "EvaluatorAgent",
        ]:
            neo4j_client.upsert_agent(agent_name)

        logger.info("✅ Neo4j schema and agents initialized.")

    except Exception as e:
        logger.warning(f"Neo4j startup init failed (may not be running): {e}")

@app.on_event("shutdown")
async def shutdown_event():
    import graph.neo4j_client as neo4j_client
    neo4j_client.close_driver()
    logger.info("Neo4j driver closed.")


# ─────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────
class PlanRequest(BaseModel):
    requirement: str

class StartRequest(BaseModel):
    requirement: str

# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    neo4j_ok = False
    try:
        from graph.neo4j_client import query_graph
        query_graph("RETURN 1 AS ok")
        neo4j_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "neo4j": "connected" if neo4j_ok else "disconnected",
    }


@app.post("/api/plan")
async def create_plan(request: PlanRequest):
    """
    Run the Deep Planning Agent on a requirement string.
    Stores the complete task graph into Neo4j.
    """
    if not request.requirement.strip():
        raise HTTPException(status_code=400, detail="Requirement cannot be empty")

    try:
        from agents.planning_agent import PlanningAgent
        planner = PlanningAgent()
        result = planner.run(request.requirement)
        return {
            "project_id": result["project_id"],
            "title": result["title"],
            "description": result["description"],
            "feature_count": result["feature_count"],
            "task_count": result["task_count"],
            "plan": result["plan"],
            "graph_url": f"/api/graph/{result['project_id']}",
            "neo4j_browser": "http://localhost:7474",
        }
    except Exception as e:
        logger.error(f"Planning failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/start")
async def start_pipeline(request: StartRequest, background_tasks: BackgroundTasks):
    """
    Start the full autonomous development pipeline.
    Runs planning then launches the scheduler in the background.
    """
    if not request.requirement.strip():
        raise HTTPException(status_code=400, detail="Requirement cannot be empty")

    try:
        # Ensure generated_code directory exists
        GENERATED_CODE_DIR.mkdir(parents=True, exist_ok=True)

        # Step 1: Plan
        from agents.planning_agent import PlanningAgent
        planner = PlanningAgent()
        plan_result = planner.run(request.requirement)
        project_id = plan_result["project_id"]

        # Step 2: Launch scheduler in background
        background_tasks.add_task(
            _run_scheduler_background,
            project_id=project_id,
        )

        await ws_manager.broadcast(json.dumps({
            "event": "pipeline_started",
            "project_id": project_id,
            "task_count": plan_result["task_count"],
            "timestamp": datetime.utcnow().isoformat(),
        }))

        return {
            "project_id": project_id,
            "status": "RUNNING",
            "task_count": plan_result["task_count"],
            "feature_count": plan_result["feature_count"],
            "message": "Pipeline started. Monitor via WebSocket ws://localhost:8000/ws/progress",
            "status_url": f"/api/status/{project_id}",
            "graph_url": f"/api/graph/{project_id}",
        }

    except Exception as e:
        logger.error(f"Pipeline start failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute/{project_id}")
async def execute_pipeline(project_id: str, background_tasks: BackgroundTasks):
    """Start the scheduler for an already planned project."""
    try:
        from graph.neo4j_client import query_graph
        # Verify project exists
        res = query_graph("MATCH (p:Project {id: $pid}) RETURN p.status AS status", {"pid": project_id})
        if not res:
            raise HTTPException(status_code=404, detail="Project not found")
            
        # Update status to RUNNING
        query_graph("MATCH (p:Project {id: $pid}) SET p.status = 'RUNNING'", {"pid": project_id})
        
        # Launch scheduler in background
        background_tasks.add_task(_run_scheduler_background, project_id=project_id)
        
        await ws_manager.broadcast(json.dumps({
            "event": "pipeline_started",
            "project_id": project_id,
            "timestamp": datetime.utcnow().isoformat(),
        }))
        
        return {"status": "RUNNING", "project_id": project_id}
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



async def _run_scheduler_background(project_id: str):
    """Background task: run the scheduler for a project."""
    try:
        from agents.scheduler import Scheduler
        scheduler = Scheduler(project_id=project_id, ws_broadcaster=broadcast_event)
        await scheduler.start()
    except Exception as e:
        logger.error(f"Scheduler crashed for project {project_id}: {e}", exc_info=True)


@app.get("/api/status/{project_id}")
async def get_project_status(project_id: str):
    """Get the current status of a project pipeline."""
    try:
        from graph.neo4j_client import query_graph

        cypher = """
        MATCH (p:Project {id: $project_id})
        OPTIONAL MATCH (p)-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
        RETURN
          p.title AS title,
          p.status AS project_status,
          count(t) AS total_tasks,
          count(DISTINCT f) AS feature_count,
          count(CASE WHEN t.status = 'DONE' THEN 1 END) AS done,
          count(CASE WHEN t.status = 'FAILED' THEN 1 END) AS failed,
          count(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 END) AS in_progress,
          count(CASE WHEN t.status = 'PENDING' THEN 1 END) AS pending,
          count(CASE WHEN t.status = 'BLOCKED' THEN 1 END) AS blocked
        """
        result = query_graph(cypher, {"project_id": project_id})
        if not result:
            raise HTTPException(status_code=404, detail="Project not found")

        row = result[0]
        total = row.get("total_tasks") or 1
        done = row.get("done", 0) or 0
        # Progress = done / (total - blocked) so blocked don't skew 100%
        effective_total = max(1, total - (row.get("blocked", 0) or 0))
        progress = round((done / effective_total) * 100, 1)

        return {
            "project_id": project_id,
            "title": row.get("title"),
            "status": row.get("project_status"),
            "progress_pct": min(progress, 100.0),
            "tasks": {
                "total": total,
                "done": done,
                "failed": row.get("failed", 0),
                "in_progress": row.get("in_progress", 0),
                "pending": row.get("pending", 0),
                "blocked": row.get("blocked", 0),
                "features": row.get("feature_count", 0),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph/{project_id}")
async def get_project_graph(project_id: str):
    """Return task graph in d3-force compatible format."""
    try:
        from graph.neo4j_client import get_project_graph_data
        data = get_project_graph_data(project_id)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/insights")
async def get_insights():
    """
    Return Neo4j-powered analytics insights.
    All queries use raw Cypher.
    """
    try:
        from graph.neo4j_client import (
            get_most_failed_task_types,
            get_agent_retry_rates,
            get_recurring_bugs,
            get_reused_patterns,
        )
        return {
            "most_failed_task_types": get_most_failed_task_types(),
            "agent_retry_rates": get_agent_retry_rates(),
            "recurring_bugs": get_recurring_bugs(),
            "reused_patterns": get_reused_patterns(),
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/llm-log")
async def get_llm_log():
    """Return the LLM call log for monitoring."""
    from llm_client import get_call_log
    log = get_call_log()
    return {"total_calls": len(log), "calls": log[-100:]}


@app.get("/api/analytics/agents")
async def get_agent_analytics(project_id: Optional[str] = None):
    """
    Per-agent analytics. Handles both old log format (agent_type='reasoning'/'fast')
    and new format (agent_type='PlanningAgent', model_tier='reasoning').
    """
    from llm_client import get_call_log
    from graph.neo4j_client import get_agent_retry_rates, get_most_failed_task_types

    all_calls = get_call_log()
    if project_id:
        call_log = [e for e in all_calls if e.get("project_id") == project_id]
        scope = f"project:{project_id[:8]}"
    else:
        call_log = all_calls
        scope = "global"

    TIER_NAMES = {"reasoning", "fast"}

    def _resolve(entry):
        raw_agent = entry.get("agent_type") or "unknown"
        raw_tier  = entry.get("model_tier")  or ""
        # Old entries: agent_type held the tier name
        if raw_agent in TIER_NAMES and not raw_tier:
            return "unknown", raw_agent
        return raw_agent, raw_tier or "unknown"

    def _agg(entries, group_key):
        stats = {}
        for entry in entries:
            agent_key, tier_key = _resolve(entry)
            key = (agent_key if group_key == "agent_type" else tier_key) or "unknown"
            if key not in stats:
                stats[key] = {
                    "total_calls": 0, "successful_calls": 0, "failed_calls": 0,
                    "total_tokens": 0, "total_latency_ms": 0, "models_used": set(),
                }
            s = stats[key]
            s["total_calls"]      += 1
            s["successful_calls"] += int(bool(entry.get("success")))
            s["failed_calls"]     += int(not bool(entry.get("success")))
            s["total_tokens"]     += entry.get("tokens_used") or 0
            s["total_latency_ms"] += entry.get("latency_ms")  or 0
            s["models_used"].add(entry.get("model", "unknown"))
        for s in stats.values():
            calls = s["total_calls"] or 1
            s["avg_latency_ms"]   = round(s["total_latency_ms"] / calls, 1)
            s["success_rate_pct"] = round((s["successful_calls"] / calls) * 100, 1)
            s["models_used"]      = list(s["models_used"])
        return stats

    agent_stats      = _agg(call_log, "agent_type")
    model_tier_stats = _agg(call_log, "model_tier")

    neo4j_agents = []
    try:
        neo4j_agents = get_agent_retry_rates()
        if project_id:
            for ag in neo4j_agents:
                ag_s = agent_stats.get(ag.get("agent", ""), {})
                ag["project_tokens"] = ag_s.get("total_tokens", 0)
                ag["project_calls"]  = ag_s.get("total_calls",  0)
    except Exception:
        pass

    total_tokens = sum(s["total_tokens"] for s in agent_stats.values())
    total_calls  = sum(s["total_calls"]  for s in agent_stats.values())
    total_failed = sum(s["failed_calls"] for s in agent_stats.values())

    failed_types = []
    try:
        failed_types = get_most_failed_task_types()
    except Exception:
        pass

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "scope": scope,
        "summary": {
            "total_llm_calls":          total_calls,
            "total_tokens_used":        total_tokens,
            "total_failed_calls":       total_failed,
            "overall_success_rate_pct": round(((total_calls - total_failed) / max(1, total_calls)) * 100, 1),
        },
        "per_agent":              agent_stats,
        "per_model_tier":         model_tier_stats,
        "neo4j_agents":           neo4j_agents,
        "most_failed_task_types": failed_types,
    }


@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    try:
        from graph.neo4j_client import query_graph
        cypher = """
        MATCH (p:Project)
        OPTIONAL MATCH (p)-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
        RETURN
          p.id AS id,
          p.title AS title,
          p.status AS status,
          p.created_at AS created_at,
          count(t) AS task_count
        ORDER BY p.created_at DESC
        LIMIT 50
        """
        return query_graph(cypher)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks/{project_id}/all")
async def get_all_tasks(project_id: str):
    """Get all tasks for a project with their details."""
    try:
        from graph.neo4j_client import query_graph
        cypher = """
        MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
        OPTIONAL MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t)
        OPTIONAL MATCH (tr:TestResult)-[:VALIDATES]->(cm)
        OPTIONAL MATCH (er:EvaluationResult)-[:EVALUATES]->(cm)
        RETURN
          t.id AS id,
          t.title AS title,
          t.description AS description,
          t.type AS type,
          t.status AS status,
          t.priority AS priority,
          f.title AS feature,
          cm.filename AS filename,
          tr.status AS test_status,
          tr.tests_passed AS tests_passed,
          tr.tests_failed AS tests_failed,
          er.score AS eval_score
        ORDER BY t.priority ASC
        """
        return query_graph(cypher, {"project_id": project_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/code/{project_id}/files")
async def list_generated_files(project_id: str):
    """List all generated files for a project."""
    try:
        from graph.neo4j_client import query_graph
        cypher = """
        MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
              <-[:PRODUCED_BY]-(cm:CodeModule)
        RETURN
          cm.id AS id,
          cm.filename AS filename,
          cm.filepath AS filepath,
          cm.module_type AS type,
          cm.version AS version,
          t.title AS task_title
        ORDER BY cm.filename
        """
        files = query_graph(cypher, {"project_id": project_id})

        # Add code preview
        for f in files:
            fp = f.get("filepath", "")
            try:
                f["code"] = Path(fp).read_text(encoding="utf-8") if fp and Path(fp).exists() else ""
                f["size"] = len(f["code"])
            except Exception:
                f["code"] = ""
                f["size"] = 0

        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/evaluations/{project_id}")
async def get_evaluations(project_id: str):
    """Get evaluation scores for all modules in a project."""
    try:
        from graph.neo4j_client import query_graph
        cypher = """
        MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
              <-[:PRODUCED_BY]-(cm:CodeModule)<-[:EVALUATES]-(er:EvaluationResult)
        RETURN
          cm.filename AS filename,
          er.score AS score,
          er.correctness AS correctness,
          er.code_quality AS code_quality,
          er.completeness AS completeness,
          er.critique AS critique,
          er.passed AS passed
        ORDER BY er.score DESC
        """
        return query_graph(cypher, {"project_id": project_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/{project_id}")
async def export_project(project_id: str):
    """
    Export project as a ZIP file containing:
    - All generated source code
    - requirements.txt
    - README.md (auto-generated)
    - test_report.json
    - EVALUATION_REPORT.md
    """
    try:
        from graph.neo4j_client import query_graph, create_project_snapshot

        # Fetch all data
        files_cypher = """
        MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
              <-[:PRODUCED_BY]-(cm:CodeModule)
        RETURN cm.filepath AS filepath, cm.filename AS filename
        """
        files = query_graph(files_cypher, {"pid": project_id})

        eval_cypher = """
        MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
              <-[:PRODUCED_BY]-(cm:CodeModule)<-[:EVALUATES]-(er:EvaluationResult)
        RETURN cm.filename AS file, er.score AS score, er.critique AS critique,
               er.passed AS passed, er.suggestions AS suggestions
        """
        evaluations = query_graph(eval_cypher, {"pid": project_id})

        test_cypher = """
        MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
              <-[:PRODUCED_BY]-(cm:CodeModule)<-[:VALIDATES]-(tr:TestResult)
        RETURN cm.filename AS file, tr.status AS status,
               tr.tests_passed AS passed, tr.tests_failed AS failed
        """
        tests = query_graph(test_cypher, {"pid": project_id})

        proj_cypher = "MATCH (p:Project {id: $pid}) RETURN p.title AS title, p.description AS desc"
        proj_info = query_graph(proj_cypher, {"pid": project_id})
        title = proj_info[0]["title"] if proj_info else "Project"
        description = proj_info[0]["desc"] if proj_info else ""

        # Build ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Source files
            for f in files:
                fp = f.get("filepath", "")
                fn = f.get("filename", "unknown.py")
                if fp and Path(fp).exists():
                    code = Path(fp).read_text(encoding="utf-8", errors="replace")
                    zf.writestr(f"src/{fn}", code)

            # requirements.txt
            zf.writestr("requirements.txt", _generate_requirements(files))

            # README.md
            zf.writestr("README.md", _generate_readme(title, description, files, evaluations))

            # test_report.json
            zf.writestr("test_report.json", json.dumps(tests, indent=2))

            # EVALUATION_REPORT.md
            zf.writestr("EVALUATION_REPORT.md", _generate_eval_report(evaluations))

        # Create snapshot
        create_project_snapshot(project_id)

        zip_buffer.seek(0)
        filename = f"codonova_{project_id[:8]}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"

        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _generate_requirements(files: list) -> str:
    """Extract imports from generated files to create requirements.txt."""
    known_packages = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn[standard]",
        "sqlalchemy": "sqlalchemy",
        "pydantic": "pydantic",
        "httpx": "httpx",
        "aiofiles": "aiofiles",
        "pytest": "pytest",
        "sqlite3": None,  # stdlib
        "email": None,
    }
    used = set()
    for f in files:
        fp = f.get("filepath", "")
        if fp and Path(fp).exists():
            code = Path(fp).read_text(errors="replace")
            for pkg, req in known_packages.items():
                if f"import {pkg}" in code or f"from {pkg}" in code:
                    if req:
                        used.add(req)

    defaults = ["fastapi", "uvicorn[standard]", "pydantic", "python-dotenv"]
    all_reqs = sorted(used | set(defaults))
    return "\n".join(all_reqs) + "\n"


def _generate_readme(title: str, description: str, files: list, evaluations: list) -> str:
    avg_score = 0
    if evaluations:
        scores = [e.get("score", 0) for e in evaluations if e.get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0

    return f"""# {title}

{description}

## Overview
This project was autonomously generated by Codonova — an AI-powered software development system.

## Generated Files
{chr(10).join(f'- `{f.get("filename")}`: {f.get("filename", "").split("/")[-1]}' for f in files if f.get("filename"))}

## Evaluation Summary
- **Average Score**: {avg_score:.1f}/10
- **Files Generated**: {len(files)}
- **Evaluated**: {len(evaluations)} modules

## Running the Project
```bash
pip install -r requirements.txt
python main.py
```

## Generated by
[Codonova](https://github.com/codonova) — Autonomous Software Development System
Powered by: Gemini 2.5 Flash, Groq Llama 4 Scout, Neo4j, ChromaDB
"""


def _generate_eval_report(evaluations: list) -> str:
    lines = ["# Evaluation Report\n", f"Generated: {datetime.utcnow().isoformat()}\n"]
    for ev in evaluations:
        status = "✅ PASSED" if ev.get("passed") else "❌ FAILED"
        lines.append(f"\n## {ev.get('file', 'Unknown')} — Score: {ev.get('score', 0)}/10 {status}")
        lines.append(f"\n**Critique**: {ev.get('critique', '')}")

        suggestions = ev.get("suggestions", "[]")
        if isinstance(suggestions, str):
            try:
                suggestions = json.loads(suggestions)
            except Exception:
                suggestions = [suggestions]
        if suggestions:
            lines.append("\n**Suggestions**:")
            for s in suggestions:
                lines.append(f"- {s}")
    return "\n".join(lines)


# ─────────────────────────────────────────
# WebSocket
# ─────────────────────────────────────────
@app.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    """Global WebSocket endpoint for real-time agent events."""
    await ws_manager.connect(websocket)
    try:
        # Send initial ping
        await websocket.send_text(json.dumps({
            "event": "connected",
            "message": "Connected to Codonova real-time stream",
            "timestamp": datetime.utcnow().isoformat(),
        }))
        while True:
            # Keep connection alive (agents push data via broadcast)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"event": "heartbeat"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.websocket("/ws/progress/{project_id}")
async def websocket_project_progress(websocket: WebSocket, project_id: str):
    """Project-specific WebSocket for targeted event stream."""
    await ws_manager.connect(websocket, project_id)
    try:
        await websocket.send_text(json.dumps({
            "event": "connected",
            "project_id": project_id,
            "timestamp": datetime.utcnow().isoformat(),
        }))
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"event": "heartbeat"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, project_id)
