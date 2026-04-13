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
        a.updated_at = $at
    """
    query_graph(cypher, {"name": name, "score": score, "at": datetime.utcnow().isoformat()})


# ─────────────────────────────────────────
# Analytics (Used by APIs)
# ─────────────────────────────────────────
def get_project_graph_data(project_id: str) -> dict:
    nodes = query_graph("""
    MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(f:Feature)-[:HAS_TASK]->(t:Task)
    RETURN t.id AS id, t.title AS label, t.status AS status
    """, {"pid": project_id})
    links = query_graph("""
    MATCH (t1:Task)-[:DEPENDS_ON]->(t2:Task)
    RETURN t1.id AS source, t2.id AS target, 'DEPENDS_ON' AS type
    """)
    return {"nodes": nodes, "links": links}


def get_most_failed_task_types():
    return query_graph("MATCH (t:Task) WHERE t.status = 'FAILED' RETURN t.type AS type, count(*) AS failures ORDER BY failures DESC LIMIT 10")


def get_agent_retry_rates():
    return query_graph("MATCH (a:Agent) RETURN a.name AS agent, a.total_tasks AS tasks, a.avg_score AS score ORDER BY score DESC")


def get_recurring_bugs():
    """Get the most common root causes from Bug nodes stored by the debugging agent."""
    return query_graph("""
    MATCH (b:Bug)
    RETURN b.root_cause AS root_cause, count(*) AS occurrences
    ORDER BY occurrences DESC
    LIMIT 10
    """)


def get_reused_patterns():
    """Get CodeModules that have been reused (linked to multiple tasks)."""
    return query_graph("""
    MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t:Task)
    WITH cm, count(t) AS usage
    WHERE usage > 1
    RETURN cm.filename AS pattern, cm.module_type AS type, usage
    ORDER BY usage DESC
    LIMIT 10
    """)


def create_project_snapshot(project_id: str):
    query_graph("MATCH (p:Project {id: $pid}) SET p.last_snapshot = $at", {"pid": project_id, "at": datetime.utcnow().isoformat()})