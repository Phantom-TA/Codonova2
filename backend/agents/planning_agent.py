"""
planning_agent.py — Deep Planning Agent
========================================
Uses Gemini 2.5 Flash (reasoning) for two-stage LLM decomposition:
  Call 1: Extract features + acceptance criteria from raw requirement
  Call 2: Break each feature into tasks/subtasks with dependency detection

All task data is stored into Neo4j as a graph.
"""

import json
import uuid
import logging
from datetime import datetime
from llm_client import llm_call, parse_json_response
from graph.neo4j_client import (
    create_node, link_nodes, query_graph, upsert_agent, update_agent_profile
)

logger = logging.getLogger("planning_agent")


class PlanningAgent:
    """
    Decomposes a raw software requirement into a structured task graph in Neo4j.
    """

    AGENT_NAME = "PlanningAgent"

    # ─── System Prompts ───────────────────────────────────────────────────────

    FEATURE_EXTRACTION_SYSTEM = """You are an expert software architect and product manager.
Given a software requirement, extract all major features and their acceptance criteria.

Return a valid JSON object with this exact structure:
{
  "project_title": "string",
  "project_description": "string",
  "features": [
    {
      "id": "f1",
      "title": "Feature name",
      "description": "Detailed feature description",
      "acceptance_criteria": ["criterion 1", "criterion 2"],
      "priority": 1
    }
  ]
}

Rules:
- Extract 3-8 meaningful features from the requirement
- Each feature must have 2-5 concrete acceptance criteria
- Priority 1 = highest priority"""

    TASK_DECOMPOSITION_SYSTEM = """You are a senior software engineer and technical lead.
Given a list of software features, break each into concrete development tasks and subtasks.

Return a valid JSON object with this exact structure:
{
  "tasks": [
    {
      "id": "t1",
      "feature_id": "f1",
      "title": "Task title",
      "description": "What needs to be done",
      "type": "CODE",
      "priority": 1,
      "depends_on": [],
      "subtasks": [
        {
          "id": "st1",
          "title": "Subtask title",
          "description": "Specific action"
        }
      ]
    }
  ]
}

Rules:
- Task type must be: CODE, TEST, or DEBUG
- For each CODE task, create a corresponding TEST task
- depends_on contains task id strings (e.g., ["t1", "t2"])
- TEST tasks always depend on their corresponding CODE task
- Priority 1 = must be done first
- Be specific: each task should correspond to one file or one function group"""

    # ─── Core Methods ─────────────────────────────────────────────────────────

    def run(self, requirement: str) -> dict:
        """
        Main entry point. Runs the full planning pipeline.

        Args:
            requirement: Raw software requirement string

        Returns:
            dict with project_id, plan, and task count
        """
        logger.info(f"PlanningAgent starting for requirement: {requirement[:100]}...")
        upsert_agent(self.AGENT_NAME)

        start_time = datetime.utcnow()

        # Step 1: Extract features
        features_data = self._extract_features(requirement)

        # Step 2: Decompose into tasks
        tasks_data = self._decompose_tasks(requirement, features_data)

        # Step 3: Store everything in Neo4j
        project_id = self._store_in_graph(requirement, features_data, tasks_data)

        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Planning complete: project={project_id}, "
            f"features={len(features_data.get('features', []))}, "
            f"tasks={len(tasks_data.get('tasks', []))}, "
            f"elapsed={elapsed:.1f}s"
        )

        update_agent_profile(self.AGENT_NAME, score=9.0, task_type="PLAN", retries=0)

        return {
            "project_id": project_id,
            "title": features_data.get("project_title", "Untitled Project"),
            "description": features_data.get("project_description", ""),
            "feature_count": len(features_data.get("features", [])),
            "task_count": len(tasks_data.get("tasks", [])),
            "plan": {
                "features": features_data.get("features", []),
                "tasks": tasks_data.get("tasks", []),
            },
        }

    def _extract_features(self, requirement: str) -> dict:
        """Call 1: Extract features and acceptance criteria."""
        logger.info("Call 1: Extracting features from requirement...")

        messages = [
            {"role": "system", "content": self.FEATURE_EXTRACTION_SYSTEM},
            {"role": "user", "content": f"Software Requirement:\n{requirement}"},
        ]

        raw = llm_call("reasoning", messages, json_mode=True)
        data = parse_json_response(raw)
        logger.info(f"Extracted {len(data.get('features', []))} features.")
        return data

    def _decompose_tasks(self, requirement: str, features_data: dict) -> dict:
        """Call 2: Break features into tasks and subtasks with dependencies."""
        logger.info("Call 2: Decomposing features into tasks...")

        features_json = json.dumps(features_data.get("features", []), indent=2)

        messages = [
            {"role": "system", "content": self.TASK_DECOMPOSITION_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Original Requirement:\n{requirement}\n\n"
                    f"Extracted Features:\n{features_json}\n\n"
                    "Now decompose these into specific CODE, TEST, and DEBUG tasks with dependencies."
                ),
            },
        ]

        raw = llm_call("reasoning", messages, json_mode=True)
        data = parse_json_response(raw)
        logger.info(f"Decomposed into {len(data.get('tasks', []))} tasks.")
        return data

    def _store_in_graph(
        self, requirement: str, features_data: dict, tasks_data: dict
    ) -> str:
        """Store the full plan into Neo4j and return the project_id."""
        project_id = str(uuid.uuid4())

        # Create Project node
        create_node("Project", {
            "id": project_id,
            "title": features_data.get("project_title", "Untitled"),
            "description": features_data.get("project_description", ""),
            "requirement": requirement,
            "status": "PLANNING",
            "created_at": datetime.utcnow().isoformat(),
        })
        logger.info(f"Created Project node: {project_id}")

        # Create Requirement node
        req_id = str(uuid.uuid4())
        create_node("Requirement", {
            "id": req_id,
            "text": requirement,
            "created_at": datetime.utcnow().isoformat(),
        })
        link_nodes(project_id, req_id, "HAS_REQUIREMENT")

        # Create Feature nodes
        feature_neo4j_ids: dict[str, str] = {}  # logical id → neo4j id
        for feature in features_data.get("features", []):
            logical_id = feature.get("id", str(uuid.uuid4()))
            feature_id = str(uuid.uuid4())
            feature_neo4j_ids[logical_id] = feature_id

            create_node("Feature", {
                "id": feature_id,
                "logical_id": logical_id,
                "title": feature.get("title", ""),
                "description": feature.get("description", ""),
                "acceptance_criteria": json.dumps(feature.get("acceptance_criteria", [])),
                "priority": feature.get("priority", 1),
            })
            link_nodes(project_id, feature_id, "HAS_FEATURE")

        # Create Task nodes (first pass — no dependencies yet)
        task_neo4j_ids: dict[str, str] = {}
        for task in tasks_data.get("tasks", []):
            logical_id = task.get("id", str(uuid.uuid4()))
            task_id = str(uuid.uuid4())
            task_neo4j_ids[logical_id] = task_id

            create_node("Task", {
                "id": task_id,
                "logical_id": logical_id,
                "title": task.get("title", ""),
                "description": task.get("description", ""),
                "type": task.get("type", "CODE"),
                "status": "PENDING",
                "priority": task.get("priority", 5),
                "feature_logical_id": task.get("feature_id", ""),
            })

            # Link to Feature
            feature_logical_id = task.get("feature_id", "")
            if feature_logical_id in feature_neo4j_ids:
                link_nodes(feature_neo4j_ids[feature_logical_id], task_id, "HAS_TASK")

            # Create SubTask nodes
            for subtask in task.get("subtasks", []):
                st_id = str(uuid.uuid4())
                create_node("SubTask", {
                    "id": st_id,
                    "title": subtask.get("title", ""),
                    "description": subtask.get("description", ""),
                    "status": "PENDING",
                })
                link_nodes(task_id, st_id, "HAS_SUBTASK")

        # Second pass — create DEPENDS_ON edges
        for task in tasks_data.get("tasks", []):
            logical_id = task.get("id")
            task_neo4j_id = task_neo4j_ids.get(logical_id)
            if not task_neo4j_id:
                continue
            for dep_logical_id in task.get("depends_on", []):
                dep_neo4j_id = task_neo4j_ids.get(dep_logical_id)
                if dep_neo4j_id:
                    link_nodes(task_neo4j_id, dep_neo4j_id, "DEPENDS_ON")
                    logger.debug(f"Dependency: {logical_id} → {dep_logical_id}")

        # Update project status
        query_graph(
            "MATCH (p:Project {id: $pid}) SET p.status = 'PLANNED', p.task_count = $tc",
            {"pid": project_id, "tc": len(tasks_data.get("tasks", []))},
        )

        return project_id
