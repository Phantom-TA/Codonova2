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

    FEATURE_EXTRACTION_SYSTEM = """Extract features from a software requirement.
Return JSON only:
{
  "project_title": "string",
  "project_description": "string",
  "features": [
    {"id": "f1", "title": "Feature name", "description": "One sentence", "priority": 1}
  ]
}
Rules: 2-5 features max. Be concise."""

    TASK_DECOMPOSITION_SYSTEM = """Break a software feature into development tasks.
Return JSON only:
{
  "tasks": [
    {
      "id": "t1",
      "feature_id": "f1",
      "title": "Task title",
      "description": "One sentence describing what to build",
      "type": "CODE",
      "priority": 1,
      "depends_on": []
    }
  ]
}
Rules:
- type must be CODE or TEST
- 3-6 tasks per feature max
- Each task = one file. No subtasks.
- depends_on: list task ids this needs first"""

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
        """Call 2: Break features into tasks individually to avoid large JSON truncation."""
        logger.info("Call 2: Decomposing features into tasks (modular)...")

        all_tasks = []
        features = features_data.get("features", [])

        for i, feature in enumerate(features):
            logger.info(f"Decomposing Feature {i+1}/{len(features)}: {feature.get('title')}")
            
            messages = [
                {"role": "system", "content": self.TASK_DECOMPOSITION_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Feature: {feature.get('title')}\n"
                        f"Description: {feature.get('description')}\n\n"
                        "Break this into 3-6 tasks (CODE type only, no TEST tasks). "
                        "Each task = one file. Be brief."
                    ),
                },
            ]

            raw = llm_call("reasoning", messages, json_mode=True)
            try:
                data = parse_json_response(raw)
                feature_tasks = data.get("tasks", [])
                
                # Ensure each task is correctly linked to the feature ID
                for task in feature_tasks:
                    if not task.get("feature_id"):
                        task["feature_id"] = feature.get("id")
                
                all_tasks.extend(feature_tasks)
            except Exception as e:
                logger.error(f"Failed to decompose feature {feature.get('id')}: {e}")
                # Log the raw response to help debugging
                logger.debug(f"Raw response: {raw[:500]}...")
                continue

        logger.info(f"Total decomposition results: {len(all_tasks)} tasks.")
        return {"tasks": all_tasks}

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
                "project_id": project_id,
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
