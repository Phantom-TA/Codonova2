"""
neo4j_client.py — Neo4j Graph Database Client
==============================================
All graph operations use raw Cypher queries — no ORM.

Node Types:
  Project, Requirement, Feature, Task, SubTask, CodeModule,
  Bug, Fix, TestCase, TestResult, Agent, Decision, Feedback, LearningNode,
  EvaluationResult, ProjectSnapshot

Relationships:
  DEPENDS_ON, GENERATES, RESOLVES, VALIDATES, LEARNED_FROM,
  PRODUCED_BY, HAS_REQUIREMENT, HAS_FEATURE, HAS_TASK, HAS_SUBTASK,
  LINKED_TO, FAILED_BY, FIXED_BY
"""

import os
import uuid
import logging
from datetime import datetime
from typing import Any, Optional
from neo4j import GraphDatabase, Driver
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("neo4j_client")


# ─────────────────────────────────────────
# Driver Singleton
# ─────────────────────────────────────────
_driver: Optional[Driver] = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Neo4j driver connected: {uri}")
    return _driver


def close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None


def query_graph(cypher: str, params: dict = None) -> list[dict]:
    """
    Execute a Cypher query and return results as a list of dicts.
    This is the core building block for all graph operations.
    """
    driver = get_driver()
    params = params or {}
    with driver.session() as session:
        result = session.run(cypher, **params)
        records = []
        for record in result:
            records.append(dict(record))
        return records


# ─────────────────────────────────────────
# Schema Initialization
# ─────────────────────────────────────────
def initialize_schema():
    """Create indexes and constraints for the graph schema."""
    constraints = [
        "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT feature_id IF NOT EXISTS FOR (f:Feature) REQUIRE f.id IS UNIQUE",
        "CREATE CONSTRAINT subtask_id IF NOT EXISTS FOR (s:SubTask) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT codemodule_id IF NOT EXISTS FOR (c:CodeModule) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT bug_id IF NOT EXISTS FOR (b:Bug) REQUIRE b.id IS UNIQUE",
        "CREATE CONSTRAINT fix_id IF NOT EXISTS FOR (f:Fix) REQUIRE f.id IS UNIQUE",
        "CREATE CONSTRAINT testcase_id IF NOT EXISTS FOR (t:TestCase) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT testresult_id IF NOT EXISTS FOR (t:TestResult) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT agent_name IF NOT EXISTS FOR (a:Agent) REQUIRE a.name IS UNIQUE",
        "CREATE CONSTRAINT learningnode_id IF NOT EXISTS FOR (l:LearningNode) REQUIRE l.id IS UNIQUE",
    ]
    for stmt in constraints:
        try:
            query_graph(stmt)
        except Exception as e:
            logger.debug(f"Constraint already exists or error: {e}")

    logger.info("Neo4j schema initialized.")


# ─────────────────────────────────────────
# Node Operations
# ─────────────────────────────────────────
def create_node(label: str, properties: dict) -> str:
    """
    Create a node with the given label and properties.
    Auto-assigns uuid id if not provided.
    Returns the node id.
    """
    if "id" not in properties:
        properties["id"] = str(uuid.uuid4())
    if "created_at" not in properties:
        properties["created_at"] = datetime.utcnow().isoformat()

    # Build dynamic SET clause
    prop_str = ", ".join([f"n.{k} = ${k}" for k in properties])
    cypher = f"CREATE (n:{label}) SET {prop_str} RETURN n.id AS id"

    result = query_graph(cypher, properties)
    node_id = result[0]["id"] if result else properties["id"]
    logger.debug(f"Created {label} node: {node_id}")
    return node_id


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
    """
    Create a directed relationship between two nodes.
    Nodes are matched by their id property regardless of label.
    """
    props = properties or {}
    if props:
        prop_str = "{" + ", ".join([f"{k}: ${k}" for k in props]) + "}"
        cypher = (
            f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
            f"MERGE (a)-[r:{relationship} {prop_str}]->(b) RETURN type(r)"
        )
    else:
        cypher = (
            f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
            f"MERGE (a)-[r:{relationship}]->(b) RETURN type(r)"
        )
    query_graph(cypher, {"from_id": from_id, "to_id": to_id, **props})


# ─────────────────────────────────────────
# Task Management
# ─────────────────────────────────────────
def get_task_tree(project_id: str) -> list[dict]:
    """Get the full task tree for a project."""
    cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)
    OPTIONAL MATCH (f)-[:HAS_TASK]->(t:Task)
    OPTIONAL MATCH (t)-[:HAS_SUBTASK]->(st:SubTask)
    RETURN f.id AS feature_id, f.title AS feature_title,
           t.id AS task_id, t.title AS task_title, t.status AS task_status,
           t.type AS task_type, t.priority AS task_priority,
           st.id AS subtask_id, st.title AS subtask_title
    ORDER BY f.title, t.priority
    """
    return query_graph(cypher, {"project_id": project_id})


def get_pending_tasks(project_id: str) -> list[dict]:
    """
    Get all PENDING tasks whose dependencies are all DONE.
    Only tasks with no unfinished DEPENDS_ON edges are returned.
    """
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
    """Update a task's status (PENDING/IN_PROGRESS/DONE/FAILED/BLOCKED)."""
    cypher = """
    MATCH (t:Task {id: $task_id})
    SET t.status = $status, t.updated_at = $updated_at
    """
    query_graph(cypher, {
        "task_id": task_id,
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
    })
    logger.info(f"Task {task_id} → {status}")


def get_failed_tests(project_id: str) -> list[dict]:
    """Get all failed test results for a project."""
    cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
          <-[:PRODUCED_BY]-(cm:CodeModule)<-[:VALIDATES]-(tr:TestResult)
    WHERE tr.status = 'FAILED'
    RETURN properties(tr) AS result, properties(cm) AS code_module, t.id AS task_id
    """
    return query_graph(cypher, {"project_id": project_id})


def get_dependent_tasks(task_id: str) -> list[dict]:
    """Get all tasks that depend on the given task (downstream)."""
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
    SET dep.status = 'BLOCKED', dep.updated_at = $updated_at
    RETURN dep.id
    """
    results = query_graph(cypher, {
        "task_id": task_id,
        "updated_at": datetime.utcnow().isoformat(),
    })
    return [r["dep.id"] for r in results]


# ─────────────────────────────────────────
# Agent Profile Management
# ─────────────────────────────────────────
def upsert_agent(name: str):
    """Create or ensure an Agent node exists."""
    cypher = """
    MERGE (a:Agent {name: $name})
    ON CREATE SET a.id = $id, a.avg_score = 0.0, a.total_tasks = 0,
                  a.total_retries = 0, a.best_task_type = '',
                  a.created_at = $created_at
    RETURN a.name
    """
    query_graph(cypher, {
        "name": name,
        "id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
    })


def update_agent_profile(name: str, score: float, task_type: str, retries: int):
    """Update agent metrics after completing a task."""
    cypher = """
    MATCH (a:Agent {name: $name})
    SET a.avg_score = ((a.avg_score * a.total_tasks) + $score) / (a.total_tasks + 1),
        a.total_tasks = a.total_tasks + 1,
        a.total_retries = a.total_retries + $retries,
        a.updated_at = $updated_at
    """
    query_graph(cypher, {
        "name": name,
        "score": score,
        "task_type": task_type,
        "retries": retries,
        "updated_at": datetime.utcnow().isoformat(),
    })


# ─────────────────────────────────────────
# Analytics Queries
# ─────────────────────────────────────────
def get_most_failed_task_types() -> list[dict]:
    cypher = """
    MATCH (t:Task)
    WHERE t.status = 'FAILED'
    RETURN t.type AS task_type, count(t) AS failure_count
    ORDER BY failure_count DESC
    LIMIT 10
    """
    return query_graph(cypher)


def get_agent_retry_rates() -> list[dict]:
    cypher = """
    MATCH (a:Agent)
    RETURN a.name AS agent, a.total_tasks AS tasks,
           a.total_retries AS retries,
           CASE WHEN a.total_tasks > 0
                THEN toFloat(a.total_retries) / a.total_tasks
                ELSE 0.0
           END AS retry_rate,
           a.avg_score AS avg_score
    ORDER BY retry_rate DESC
    """
    return query_graph(cypher)


def get_recurring_bugs() -> list[dict]:
    cypher = """
    MATCH (b:Bug)-[:RESOLVES]->(f:Fix)
    RETURN b.error_type AS error_type, count(f) AS frequency
    ORDER BY frequency DESC
    LIMIT 10
    """
    return query_graph(cypher)


def get_reused_patterns() -> list[dict]:
    cypher = """
    MATCH (l:LearningNode)
    RETURN l.pattern_summary AS pattern, l.use_count AS uses,
           l.avg_score AS avg_score
    ORDER BY uses DESC
    LIMIT 10
    """
    return query_graph(cypher)


def get_project_graph_data(project_id: str) -> dict:
    """
    Return graph data in d3/force-graph format: {nodes, links}
    """
    # Nodes: all tasks, features, code modules
    node_cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    OPTIONAL MATCH (t)<-[:PRODUCED_BY]-(cm:CodeModule)
    OPTIONAL MATCH (cm)<-[:VALIDATES]-(tr:TestResult)
    WITH f, t, cm, tr
    RETURN
      collect(DISTINCT {id: f.id, label: f.title, type: 'Feature', status: 'DONE'}) AS features,
      collect(DISTINCT {id: t.id, label: t.title, type: t.type, status: t.status, priority: t.priority}) AS tasks,
      collect(DISTINCT {id: cm.id, label: cm.filename, type: 'CodeModule', status: COALESCE(tr.status, 'PENDING')}) AS modules
    """
    # Edges: DEPENDS_ON, HAS_TASK, PRODUCED_BY
    edge_cypher = """
    MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    OPTIONAL MATCH (t)-[:DEPENDS_ON]->(dep:Task)
    OPTIONAL MATCH (t)<-[:PRODUCED_BY]-(cm:CodeModule)
    RETURN
      collect(DISTINCT {source: f.id, target: t.id, type: 'HAS_TASK'}) AS feature_edges,
      collect(DISTINCT {source: t.id, target: dep.id, type: 'DEPENDS_ON'}) AS dep_edges,
      collect(DISTINCT {source: cm.id, target: t.id, type: 'PRODUCED_BY'}) AS module_edges
    """
    params = {"project_id": project_id}
    node_data = query_graph(node_cypher, params)
    edge_data = query_graph(edge_cypher, params)

    nodes = []
    links = []

    if node_data:
        row = node_data[0]
        for lst in [row.get("features", []), row.get("tasks", []), row.get("modules", [])]:
            if lst:
                nodes.extend([n for n in lst if n and n.get("id")])

    if edge_data:
        row = edge_data[0]
        for lst in [row.get("feature_edges", []), row.get("dep_edges", []), row.get("module_edges", [])]:
            if lst:
                links.extend([e for e in lst if e and e.get("source") and e.get("target")])

    return {"nodes": nodes, "links": links}


def create_project_snapshot(project_id: str) -> str:
    """Create a snapshot node for the final project state."""
    snapshot_id = str(uuid.uuid4())
    cypher = """
    MATCH (p:Project {id: $project_id})
    CREATE (snap:ProjectSnapshot {
        id: $snapshot_id,
        project_id: $project_id,
        timestamp: $timestamp
    })
    CREATE (p)-[:HAS_SNAPSHOT]->(snap)
    RETURN snap.id AS id
    """
    result = query_graph(cypher, {
        "project_id": project_id,
        "snapshot_id": snapshot_id,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return result[0]["id"] if result else snapshot_id
