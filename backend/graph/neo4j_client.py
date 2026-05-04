import os
import uuid
import time
import logging
from datetime import datetime
from typing import Any, Optional
from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)

_driver: Optional[Driver] = None


# ─────────────────────────────────────────
# Connection (with retry)
# ─────────────────────────────────────────
def get_driver() -> Driver:
    global _driver
    if _driver is not None:
        return _driver

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    retries = 10
    delay = 3

    for attempt in range(retries):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            _driver = driver
            logger.info(f"✅ Neo4j connected: {uri}")
            return _driver
        except Exception as e:
            logger.warning(f"⏳ Neo4j not ready (attempt {attempt+1}/{retries})... {e}")
            time.sleep(delay)

    raise Exception("❌ Failed to connect to Neo4j after retries")


def close_driver():
    global _driver
    if _driver is not None:
        try:
            _driver.close()
            logger.info("Neo4j driver closed")
        except Exception as e:
            logger.warning(f"Error closing Neo4j driver: {e}")
        finally:
            _driver = None


# ─────────────────────────────────────────
# Query Helper
# ─────────────────────────────────────────
def query_graph(cypher: str, params: dict = None) -> list[dict]:
    driver = get_driver()
    params = params or {}
    try:
        with driver.session() as session:
            result = session.run(cypher, **params)
            return [dict(record) for record in result]
    except Exception as e:
        logger.error(f"Neo4j query failed: {e}")
        raise


# ─────────────────────────────────────────
# Schema Initialization
# ─────────────────────────────────────────
def initialize_schema():
    constraints = [
        "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT feature_id IF NOT EXISTS FOR (f:Feature) REQUIRE f.id IS UNIQUE",
        "CREATE CONSTRAINT codemodule_id IF NOT EXISTS FOR (c:CodeModule) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT agent_name IF NOT EXISTS FOR (a:Agent) REQUIRE a.name IS UNIQUE",
        "CREATE CONSTRAINT learningnode_id IF NOT EXISTS FOR (l:LearningNode) REQUIRE l.id IS UNIQUE",
    ]
    for stmt in constraints:
        try:
            query_graph(stmt)
        except Exception as e:
            logger.debug(f"Schema update: {e}")
    logger.info("✅ Neo4j schema initialized")


# ─────────────────────────────────────────
# Node Operations
# ─────────────────────────────────────────
def create_node(label: str, properties: dict) -> str:
    """Create a node with UUID and timestamp and return its ID."""
    if "id" not in properties:
        properties["id"] = str(uuid.uuid4())
    if "created_at" not in properties:
        properties["created_at"] = datetime.utcnow().isoformat()

    prop_str = ", ".join([f"n.{k} = ${k}" for k in properties])
    cypher = f"CREATE (n:{label}) SET {prop_str} RETURN n.id AS id"
    result = query_graph(cypher, properties)
    return result[0]["id"] if result else properties["id"]


def get_node(label: str, node_id: str) -> Optional[dict]:
    """Fetch a single node by label and id."""
    cypher = f"MATCH (n:{label} {{id: $id}}) RETURN properties(n) AS props"
    result = query_graph(cypher, {"id": node_id})
    return result[0]["props"] if result else None


def update_node(label: str, node_id: str, properties: dict):
    """Update properties of an existing node."""
    properties["updated_at"] = datetime.utcnow().isoformat()
    prop_str = ", ".join([f"n.{k} = ${k}" for k in properties])
    cypher = f"MATCH (n:{label} {{id: $id}}) SET {prop_str}"
    query_graph(cypher, {"id": node_id, **properties})


def link_nodes(from_id: str, to_id: str, relationship: str, properties: dict = None):
    """Link two nodes by ID (matches any label)."""
    props = properties or {}
    prop_str = "{" + ", ".join([f"{k}: ${k}" for k in props]) + "}" if props else ""
    cypher = f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) MERGE (a)-[r:{relationship} {prop_str}]->(b)"
    query_graph(cypher, {"from_id": from_id, "to_id": to_id, **props})


# Aliases for compatibility
create_relationship = link_nodes
get_node_by_id = lambda node_id: query_graph("MATCH (n {id: $id}) RETURN properties(n) AS n", {"id": node_id})[0]["n"]


# ─────────────────────────────────────────
# Task Management
# ─────────────────────────────────────────
def get_task_tree(project_id: str) -> list[dict]:
    cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    RETURN f.id AS feature_id, f.title AS feature_title,
           t.id AS task_id, t.title AS task_title, t.status AS task_status,
           t.type AS task_type, t.priority AS task_priority
    ORDER BY f.title, t.priority
    """
    return query_graph(cypher, {"project_id": project_id})


def get_pending_tasks(project_id: str) -> list[dict]:
    cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    WHERE t.status = 'PENDING'
    AND NOT EXISTS {
        MATCH (t)-[:DEPENDS_ON]->(dep:Task)
        WHERE dep.status <> 'DONE'
    }
    RETURN properties(t) AS task
    ORDER BY t.priority ASC
    """
    results = query_graph(cypher, {"project_id": project_id})
    return [r["task"] for r in results]


def mark_task_status(task_id: str, status: str):
    cypher = "MATCH (t:Task {id: $task_id}) SET t.status = $status, t.updated_at = $at"
    query_graph(cypher, {"task_id": task_id, "status": status, "at": datetime.utcnow().isoformat()})
    logger.info(f"Task {task_id} → {status}")


def get_failed_tests(project_id: str) -> list[dict]:
    cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
          <-[:PRODUCED_BY]-(cm:CodeModule)<-[:VALIDATES]-(tr:TestResult)
    WHERE tr.status = 'FAILED'
    RETURN properties(tr) AS result, properties(cm) AS code_module, t.id AS task_id
    """
    return query_graph(cypher, {"project_id": project_id})


def get_dependent_tasks(task_id: str) -> list[dict]:
    cypher = """
    MATCH (t:Task {id: $task_id})<-[:DEPENDS_ON*]-(dep:Task)
    RETURN properties(dep) AS task
    """
    results = query_graph(cypher, {"task_id": task_id})
    return [r["task"] for r in results]


def block_dependent_tasks(task_id: str):
    """Block all downstream tasks when a task fails."""
    cypher = """
    MATCH (t:Task {id: $task_id})<-[:DEPENDS_ON*]-(dep:Task)
    WHERE dep.status = 'PENDING'
    SET dep.status = 'BLOCKED', dep.updated_at = $at
    RETURN dep.id AS id
    """
    results = query_graph(cypher, {"task_id": task_id, "at": datetime.utcnow().isoformat()})
    return [r["id"] for r in results]


# ─────────────────────────────────────────
# Agent Management
# ─────────────────────────────────────────
def upsert_agent(name: str):
    query_graph("""
    MERGE (a:Agent {name: $name})
    ON CREATE SET a.created_at = $at, a.total_tasks = 0, a.avg_score = 0.0
    """, {"name": name, "at": datetime.utcnow().isoformat()})


def update_agent_profile(name: str, score: float, task_type: str, retries: int):
    cypher = """
    MATCH (a:Agent {name: $name})
    SET a.avg_score = ((a.avg_score * a.total_tasks) + $score) / (a.total_tasks + 1),
        a.total_tasks = a.total_tasks + 1,
        a.retries = coalesce(a.retries, 0) + $retries,
        a.updated_at = $at
    """
    query_graph(cypher, {"name": name, "score": score, "retries": retries, "at": datetime.utcnow().isoformat()})


# ─────────────────────────────────────────
# Analytics (Used by APIs)
# ─────────────────────────────────────────
def get_project_graph_data(project_id: str) -> dict:
    nodes = query_graph("""
    MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    UNWIND [
        {id: f.id, label: f.title, type: 'Feature', status: 'Feature'},
        {id: t.id, label: t.title, type: 'Task', status: t.status}
    ] AS n
    WITH n WHERE n IS NOT NULL
    RETURN DISTINCT n.id AS id, n.label AS label, n.type AS type, n.status AS status
    """, {"pid": project_id})
    
    links = query_graph("""
    MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    OPTIONAL MATCH (t)-[dep:DEPENDS_ON]->(t2:Task)
    UNWIND [
        {source: f.id, target: t.id, type: 'HAS_TASK'},
        CASE WHEN t2 IS NOT NULL THEN {source: t.id, target: t2.id, type: 'DEPENDS_ON'} ELSE null END
    ] AS link
    WITH link WHERE link IS NOT NULL
    RETURN DISTINCT link.source AS source, link.target AS target, link.type AS type
    """, {"pid": project_id})
    
    return {"nodes": nodes, "links": links}


def get_most_failed_task_types():
    return query_graph("MATCH (t:Task) WHERE t.status = 'FAILED' RETURN t.type AS task_type, count(*) AS failure_count ORDER BY failure_count DESC LIMIT 10")


def get_agent_retry_rates():
    return query_graph("MATCH (a:Agent) RETURN a.name AS agent, a.total_tasks AS tasks, coalesce(a.retries, 0) AS retries, a.avg_score AS avg_score, CASE WHEN a.total_tasks > 0 THEN toFloat(coalesce(a.retries,0)) / a.total_tasks ELSE 0 END AS retry_rate ORDER BY avg_score DESC")


def get_recurring_bugs():
    """Get the most common root causes from Bug nodes stored by the debugging agent."""
    return query_graph("""
    MATCH (b:Bug)
    RETURN b.error_type AS error_type, count(*) AS frequency
    ORDER BY frequency DESC
    LIMIT 10
    """)


def get_reused_patterns():
    """Get CodeModules that have been reused (linked to multiple tasks)."""
    return query_graph("""
    MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t:Task)
    WITH cm, count(t) AS uses
    WHERE uses > 1
    RETURN cm.filename AS pattern, cm.module_type AS type, uses
    ORDER BY uses DESC
    LIMIT 10
    """)


def create_project_snapshot(project_id: str):
    query_graph("MATCH (p:Project {id: $pid}) SET p.last_snapshot = $at", {"pid": project_id, "at": datetime.utcnow().isoformat()})


# ─────────────────────────────────────────
# LLM Call Log Persistence
# ─────────────────────────────────────────
def persist_llm_call(entry: dict):
    """
    Write a single LLM call log entry as an LLMCallLog node in Neo4j.
    Called non-blocking from llm_client._log_call().
    """
    try:
        query_graph("""
        CREATE (l:LLMCallLog {
            id:         $id,
            timestamp:  $timestamp,
            agent_type: $agent_type,
            model:      $model,
            latency_ms: $latency_ms,
            tokens_used: $tokens_used,
            success:    $success,
            project_id: $project_id
        })
        """, {
            "id":          str(uuid.uuid4()),
            "timestamp":   entry.get("timestamp", datetime.utcnow().isoformat()),
            "agent_type":  entry.get("agent_type", "unknown"),
            "model":       entry.get("model", "unknown"),
            "latency_ms":  entry.get("latency_ms", 0),
            "tokens_used": entry.get("tokens_used") or 0,
            "success":     entry.get("success", False),
            "project_id":  entry.get("project_id", "__global__"),
        })
    except Exception as e:
        logger.debug(f"LLM call log persist failed (non-critical): {e}")


def load_llm_call_log(limit: int = 2000) -> list[dict]:
    """
    Load the most recent LLM call log entries from Neo4j.
    Used on startup to pre-populate the in-memory call_log.
    """
    try:
        results = query_graph("""
        MATCH (l:LLMCallLog)
        RETURN
            l.timestamp   AS timestamp,
            l.agent_type  AS agent_type,
            l.model       AS model,
            l.latency_ms  AS latency_ms,
            l.tokens_used AS tokens_used,
            l.success     AS success,
            l.project_id  AS project_id
        ORDER BY l.timestamp DESC
        LIMIT $limit
        """, {"limit": limit})
        return results
    except Exception as e:
        logger.warning(f"Could not load LLM call log from Neo4j: {e}")
        return []

# -----------------------------------------
# API Schema (cross-agent contract)
# -----------------------------------------

def store_api_schema(project_id: str, schema: dict) -> None:
    """Persist the API endpoint contract on the Project node."""
    import json
    try:
        query_graph(
            "MATCH (p:Project {id: $pid}) SET p.api_schema = $schema",
            {"pid": project_id, "schema": json.dumps(schema)},
        )
        logger.info(f"API schema stored for project {project_id}: {len(schema.get('endpoints', []))} endpoints")
    except Exception as e:
        logger.warning(f"Could not store API schema: {e}")


def get_api_schema(project_id: str) -> dict:
    """Retrieve the API endpoint contract for a project."""
    import json
    try:
        results = query_graph(
            "MATCH (p:Project {id: $pid}) RETURN p.api_schema AS schema",
            {"pid": project_id},
        )
        if results and results[0].get("schema"):
            return json.loads(results[0]["schema"])
    except Exception as e:
        logger.warning(f"Could not retrieve API schema: {e}")
    return {"endpoints": [], "base_port": 4000}
