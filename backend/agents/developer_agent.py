"""
developer_agent.py — Code Generation Agent
==========================================
Uses Gemini 2.5 Flash (reasoning) for high-quality code generation.
Reads full task context from Neo4j, generates code, writes to filesystem,
and records CodeModule node in Neo4j.
"""

import os
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from llm_client import llm_call, parse_json_response
from graph.neo4j_client import (
    create_node, link_nodes, get_node, query_graph, upsert_agent, update_agent_profile
)
from memory.context_retriever import ContextRetriever

logger = logging.getLogger("developer_agent")

GENERATED_CODE_DIR = Path(os.getenv("GENERATED_CODE_DIR", "./generated_code"))

CODE_GEN_SYSTEM = """Generate clean Node.js/Express backend code or React components.
Return JSON only:
{
  "filename": "path/to/module.js",
  "code": "// complete code",
  "explanation": "one sentence",
  "module_type": "endpoint|schema|service|utility|component",
  "dependencies": ["npm-pkg"]
}
Rules:
- Complete runnable code, no TODOs
- Use ES6+, handle errors
- Paths: api/routes/*.js | services/*.js | models/*.js | ui/components/*.jsx
- No markdown blocks in code field"""


class DeveloperAgent:
    """
    Generates code for a given task by reading full context from Neo4j.
    Writes output to filesystem and records CodeModule in Neo4j.
    """

    AGENT_NAME = "DeveloperAgent"

    def __init__(self):
        upsert_agent(self.AGENT_NAME)
        self.retriever = ContextRetriever()
        GENERATED_CODE_DIR.mkdir(parents=True, exist_ok=True)

    def run(self, task_node: dict) -> dict:
        """
        Generate code for a task.

        Args:
            task_node: Task dict from Neo4j (must have 'id', 'title', 'description')

        Returns:
            dict with filename, code_module_id, and success status
        """
        task_id = task_node["id"]
        logger.info(f"DeveloperAgent processing task: {task_id} — {task_node.get('title')}")

        # Fetch full context from Neo4j
        context = self._build_context(task_node)

        # Get similar past solutions from memory
        similar_examples = self.retriever.get_similar_context(
            task_node.get("description", "") + " " + task_node.get("title", "")
        )

        # Build prompt with context injection
        messages = self._build_messages(task_node, context, similar_examples)

        # Generate code via Gemini
        raw = llm_call("reasoning", messages, json_mode=True)
        result = parse_json_response(raw)

        # Write code to filesystem
        filepath = self._write_code(task_node, result)

        # Store CodeModule in Neo4j
        module_id = self._store_code_module(task_id, result, filepath)

        update_agent_profile(self.AGENT_NAME, score=7.5, task_type="CODE", retries=0)

        return {
            "success": True,
            "task_id": task_id,
            "code_module_id": module_id,
            "filename": str(filepath),
            "explanation": result.get("explanation", ""),
        }

    def run_with_critique(self, task_node: dict, critique: str, version: int) -> dict:
        """
        Re-generate code incorporating a critic's feedback.
        Used by the correction engine.
        """
        task_id = task_node["id"]
        logger.info(f"DeveloperAgent retry (v{version}) for task: {task_id}")

        context = self._build_context(task_node)
        similar_examples = self.retriever.get_similar_context(task_node.get("description", ""))

        messages = self._build_messages(task_node, context, similar_examples)
        # Append the critique as a follow-up
        messages.append({
            "role": "user",
            "content": (
                f"Your previous implementation was evaluated and received this critique:\n\n"
                f"{critique}\n\n"
                f"Please fix the issues and return improved code following the same JSON format."
            ),
        })

        raw = llm_call("reasoning", messages, json_mode=True)
        result = parse_json_response(raw)

        filepath = self._write_code(task_node, result, version=version)
        module_id = self._store_code_module(task_id, result, filepath, version=version)

        return {
            "success": True,
            "task_id": task_id,
            "code_module_id": module_id,
            "filename": str(filepath),
            "version": version,
        }

    def _build_context(self, task_node: dict) -> dict:
        """Fetch parent feature, sibling tasks, and acceptance criteria from Neo4j."""
        cypher = """
        MATCH (t:Task {id: $task_id})
        OPTIONAL MATCH (f:Feature)-[:HAS_TASK]->(t)
        OPTIONAL MATCH (f)-[:HAS_TASK]->(sibling:Task)
        WHERE sibling.id <> $task_id
        RETURN
          f.title AS feature_title,
          f.description AS feature_description,
          f.acceptance_criteria AS acceptance_criteria,
          collect(sibling.title) AS sibling_tasks
        """
        results = query_graph(cypher, {"task_id": task_node["id"]})
        if results:
            row = results[0]
            criteria = row.get("acceptance_criteria", "[]")
            if isinstance(criteria, str):
                try:
                    criteria = json.loads(criteria)
                except Exception:
                    criteria = [criteria]
            return {
                "feature_title": row.get("feature_title", ""),
                "feature_description": row.get("feature_description", ""),
                "acceptance_criteria": criteria,
                "sibling_tasks": row.get("sibling_tasks", []),
            }
        return {}

    def _build_messages(
        self, task_node: dict, context: dict, similar_examples: list
    ) -> list[dict]:
        """Construct the full message list for the LLM."""
        user_content = (
            f"Task: {task_node.get('title', '')}\n"
            f"Description: {task_node.get('description', '')}\n"
            f"Feature: {context.get('feature_title', 'N/A')}"
        )

        if similar_examples:
            eg = similar_examples[0]  # Only first example to save tokens
            user_content += f"\n\nSimilar pattern (use as reference):\n{eg['code'][:200]}"

        return [
            {"role": "system", "content": CODE_GEN_SYSTEM},
            {"role": "user", "content": user_content},
        ]

    def _write_code(self, task_node: dict, result: dict, version: int = 1) -> Path:
        """Write generated code to the project-specific filesystem folder."""
        filename = result.get("filename", f"module_{task_node['id'][:8]}.js")
        project_id = task_node.get("project_id", "default_project")

        # Sanitize filename
        filename = filename.replace("..", "").lstrip("/").lstrip("\\")

        # Version suffix if retrying
        if version > 1:
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            filename = str(Path(filename).parent / f"{stem}_v{version}{suffix}")

        filepath = GENERATED_CODE_DIR / project_id / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        code = result.get("code", "# No code generated")
        filepath.write_text(code, encoding="utf-8")
        logger.info(f"Code written to: {filepath}")
        return filepath

    def _store_code_module(
        self, task_id: str, result: dict, filepath: Path, version: int = 1
    ) -> str:
        """Create a CodeModule node in Neo4j linked to the Task."""
        module_id = str(uuid.uuid4())
        create_node("CodeModule", {
            "id": module_id,
            "filename": result.get("filename", ""),
            "filepath": str(filepath),
            "module_type": result.get("module_type", "utility"),
            "explanation": result.get("explanation", ""),
            "version": version,
            "status": "GENERATED",
            "dependencies": json.dumps(result.get("dependencies", [])),
        })
        link_nodes(module_id, task_id, "PRODUCED_BY")
        logger.info(f"CodeModule {module_id} linked to Task {task_id}")
        return module_id
