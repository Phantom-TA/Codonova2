"""
debugging_agent.py — Root-Cause Analysis & Fix Agent
=====================================================
Uses Gemini 2.5 Flash (reasoning) for deep debugging.
Two-call approach: chain-of-thought root cause, then corrected code.
Creates Bug and Fix nodes in Neo4j.
"""

import os
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from llm_client import llm_call, parse_json_response, set_active_agent
from graph.neo4j_client import (
    create_node, link_nodes, query_graph, upsert_agent, update_agent_profile
)

logger = logging.getLogger("debugging_agent")

GENERATED_CODE_DIR = Path(os.getenv("GENERATED_CODE_DIR", "./generated_code"))

DEBUG_SYSTEM = """Analyze a code bug and provide the fix. Return JSON only:
{
  "root_cause": "one sentence",
  "error_type": "TypeError|LogicError|etc.",
  "fix_strategy": "one sentence",
  "filename": "same/filename.js",
  "code": "// complete corrected code",
  "changes_made": ["what changed"]
}
Return the COMPLETE corrected file. No new bugs. Keep same API surface."""


class DebuggingAgent:
    """
    Analyzes test failures and generates fixes for broken code.
    """

    AGENT_NAME = "DebuggingAgent"

    def __init__(self):
        upsert_agent(self.AGENT_NAME)

    def run(self, task_node: dict) -> dict:
        task_id = task_node["id"]
        logger.info(f"DebuggingAgent analyzing task: {task_id}")
        set_active_agent(self.AGENT_NAME)

        context = self._gather_debug_context(task_id)
        if not context:
            logger.warning(f"Cannot debug task {task_id}: insufficient context")
            # Still record the attempt so score isn't zero
            update_agent_profile(self.AGENT_NAME, score=5.0, task_type="DEBUG", retries=0)
            return {"success": False, "reason": "Insufficient debug context"}

        # Single call: root cause + fix together
        debug_result = self._analyze_and_fix(context)

        fixed_filepath = self._apply_fix(context, debug_result)
        fix_success = fixed_filepath is not None and bool(debug_result.get("code", ""))

        bug_id, fix_id = self._store_debug_results(
            task_id, context, debug_result, fixed_filepath
        )

        score = 8.5 if fix_success else 5.5
        update_agent_profile(self.AGENT_NAME, score=score, task_type="DEBUG", retries=0)

        return {
            "success": True,
            "task_id": task_id,
            "bug_id": bug_id,
            "fix_id": fix_id,
            "root_cause": debug_result.get("root_cause", ""),
            "error_type": debug_result.get("error_type", ""),
            "changes": debug_result.get("changes_made", []),
            "fixed_file": str(fixed_filepath) if fixed_filepath else None,
            "needs_retest": True,
        }

    def _gather_debug_context(self, task_id: str) -> dict | None:
        """Collect all available debug information from Neo4j."""
        cypher = """
        MATCH (t:Task {id: $task_id})
        OPTIONAL MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t)
        OPTIONAL MATCH (tr:TestResult)-[:VALIDATES]->(cm)
        RETURN
          t.title AS title,
          t.description AS description,
          cm.filename AS filename,
          cm.filepath AS filepath,
          cm.id AS module_id,
          tr.output AS error_output,
          tr.errors AS errors
        ORDER BY tr.created_at DESC
        LIMIT 1
        """
        results = query_graph(cypher, {"task_id": task_id})
        if not results or not results[0].get("filepath"):
            return None

        row = results[0]
        # Read source code
        source_code = ""
        filepath = row.get("filepath", "")
        if filepath and Path(filepath).exists():
            source_code = Path(filepath).read_text(encoding="utf-8")

        return {
            "task_id": task_id,
            "title": row.get("title", ""),
            "description": row.get("description", ""),
            "filename": row.get("filename", ""),
            "filepath": filepath,
            "module_id": row.get("module_id", ""),
            "source_code": source_code,
            "error_output": row.get("error_output", ""),
            "errors": row.get("errors", "[]"),
        }

    def _analyze_and_fix(self, context: dict) -> dict:
        """Single call: root cause analysis + corrected code in one response."""
        logger.info("Analyzing and generating fix in one call...")

        errors_str = context.get("errors", "[]")
        if isinstance(errors_str, str):
            try:
                errors = json.loads(errors_str)
            except Exception:
                errors = []
        else:
            errors = errors_str

        error_summary = "; ".join(str(e) for e in errors[:3]) if errors else context.get("error_output", "")[:300]

        messages = [
            {"role": "system", "content": DEBUG_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"File: {context['filename']}\n"
                    f"Error: {error_summary}\n\n"
                    f"Code:\n{context['source_code'][:1500]}\n\n"
                    f"Test output:\n{context['error_output'][:800]}"
                ),
            },
        ]

        raw = llm_call("reasoning", messages, json_mode=True)
        result = parse_json_response(raw)
        logger.info(f"Debug fix generated: {result.get('error_type')} — {result.get('root_cause', '')[:80]}")
        return result

    def _apply_fix(self, context: dict, fix_result: dict) -> Path | None:
        """Write the fixed code to the filesystem."""
        filepath = context.get("filepath")
        if not filepath:
            return None

        fixed_code = fix_result.get("code", "")
        if not fixed_code:
            logger.warning("No fix code generated")
            return None

        path = Path(filepath)
        # Backup original
        backup = path.with_suffix(".py.bak")
        if path.exists():
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

        path.write_text(fixed_code, encoding="utf-8")
        logger.info(f"Fix applied to: {path}")
        return path

    def _store_debug_results(
        self,
        task_id: str,
        context: dict,
        debug_result: dict,
        fixed_filepath: Path | None,
    ) -> tuple[str, str]:
        """Create Bug and Fix nodes in Neo4j."""
        bug_id = str(uuid.uuid4())
        create_node("Bug", {
            "id": bug_id,
            "task_id": task_id,
            "error_type": debug_result.get("error_type", "Unknown"),
            "root_cause": debug_result.get("root_cause", ""),
        })

        fix_id = str(uuid.uuid4())
        create_node("Fix", {
            "id": fix_id,
            "bug_id": bug_id,
            "task_id": task_id,
            "changes_made": json.dumps(debug_result.get("changes_made", [])),
            "fixed_filepath": str(fixed_filepath) if fixed_filepath else "",
        })

        link_nodes(bug_id, fix_id, "RESOLVES")
        if context.get("module_id"):
            link_nodes(bug_id, context["module_id"], "FAILED_BY")
            link_nodes(fix_id, context["module_id"], "FIXED_BY")

        logger.info(f"Bug {bug_id} and Fix {fix_id} stored")
        return bug_id, fix_id
