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
from llm_client import llm_call, parse_json_response
from graph.neo4j_client import (
    create_node, link_nodes, query_graph, upsert_agent, update_agent_profile
)

logger = logging.getLogger("debugging_agent")

GENERATED_CODE_DIR = Path(os.getenv("GENERATED_CODE_DIR", "./generated_code"))

ROOT_CAUSE_SYSTEM = """You are an expert software debugger and code analyst.
Given failing code, test output, and error logs, perform thorough root cause analysis.

Return a valid JSON object with this exact structure:
{
  "root_cause": "Clear explanation of the underlying bug",
  "error_type": "TypeError|ValueError|LogicError|ImportError|etc.",
  "affected_lines": [10, 15, 23],
  "chain_of_thought": [
    "Step 1: Observed error is...",
    "Step 2: This occurs because...",
    "Step 3: The root cause is..."
  ],
  "fix_strategy": "High-level description of how to fix it"
}"""

FIX_SYSTEM = """You are an expert software engineer who fixes bugs precisely.
Given the original buggy code, root cause analysis, and test errors, provide corrected code.

Return a valid JSON object with this exact structure:
{
  "filename": "same/filename/as/before.py",
  "code": "# Complete corrected Python code",
  "changes_made": ["List of specific changes made"],
  "explanation": "Why these changes fix the issue"
}

Rules:
- Return the COMPLETE corrected file, not just the changed lines
- Do NOT introduce new bugs while fixing existing ones
- Maintain the same module structure and API surface
- Add comments explaining the fix"""


class DebuggingAgent:
    """
    Analyzes test failures and generates fixes for broken code.
    """

    AGENT_NAME = "DebuggingAgent"

    def __init__(self):
        upsert_agent(self.AGENT_NAME)

    def run(self, task_node: dict) -> dict:
        """
        Debug a failed task by analyzing errors and generating a fix.

        Args:
            task_node: Task dict from Neo4j (status should be FAILED)

        Returns:
            dict with fix status and details
        """
        task_id = task_node["id"]
        logger.info(f"DebuggingAgent analyzing task: {task_id}")

        # Gather all context
        context = self._gather_debug_context(task_id)
        if not context:
            logger.warning(f"Cannot debug task {task_id}: insufficient context")
            return {"success": False, "reason": "Insufficient debug context"}

        # Call 1: Root cause analysis
        root_cause = self._analyze_root_cause(context)

        # Call 2: Generate fix
        fix_result = self._generate_fix(context, root_cause)

        # Apply fix to filesystem
        fixed_filepath = self._apply_fix(context, fix_result)

        # Record in Neo4j
        bug_id, fix_id = self._store_debug_results(
            task_id, context, root_cause, fix_result, fixed_filepath
        )

        update_agent_profile(self.AGENT_NAME, score=7.0, task_type="DEBUG", retries=0)

        # Re-trigger testing
        logger.info(f"Triggering re-test for task {task_id} after fix")

        return {
            "success": True,
            "task_id": task_id,
            "bug_id": bug_id,
            "fix_id": fix_id,
            "root_cause": root_cause.get("root_cause", ""),
            "error_type": root_cause.get("error_type", ""),
            "changes": fix_result.get("changes_made", []),
            "fixed_file": str(fixed_filepath) if fixed_filepath else None,
            "needs_retest": True,
        }

    def _gather_debug_context(self, task_id: str) -> dict | None:
        """Collect all available debug information from Neo4j."""
        cypher = """
        MATCH (t:Task {id: $task_id})
        OPTIONAL MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t)
        OPTIONAL MATCH (tr:TestResult)-[:VALIDATES]->(cm)
        WHERE tr.status = 'FAILED'
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

    def _analyze_root_cause(self, context: dict) -> dict:
        """Call 1: Chain-of-thought root cause analysis."""
        logger.info("Analyzing root cause...")

        errors_str = context.get("errors", "[]")
        if isinstance(errors_str, str):
            try:
                errors = json.loads(errors_str)
            except Exception:
                errors = []
        else:
            errors = errors_str

        messages = [
            {"role": "system", "content": ROOT_CAUSE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Task: {context['title']}\n"
                    f"Description: {context['description']}\n\n"
                    f"Source Code ({context['filename']}):\n"
                    f"```python\n{context['source_code'][:3000]}\n```\n\n"
                    f"Test Error Output:\n{context['error_output'][:2000]}\n\n"
                    f"Specific Errors:\n{json.dumps(errors, indent=2)}"
                ),
            },
        ]

        raw = llm_call("reasoning", messages, json_mode=True)
        result = parse_json_response(raw)
        logger.info(f"Root cause identified: {result.get('error_type')} — {result.get('root_cause', '')[:100]}")
        return result

    def _generate_fix(self, context: dict, root_cause: dict) -> dict:
        """Call 2: Generate corrected code based on root cause analysis."""
        logger.info("Generating fix...")

        messages = [
            {"role": "system", "content": FIX_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Buggy File ({context['filename']}):\n"
                    f"```python\n{context['source_code'][:3000]}\n```\n\n"
                    f"Root Cause Analysis:\n"
                    f"  Error Type: {root_cause.get('error_type')}\n"
                    f"  Root Cause: {root_cause.get('root_cause')}\n"
                    f"  Affected Lines: {root_cause.get('affected_lines', [])}\n"
                    f"  Fix Strategy: {root_cause.get('fix_strategy')}\n\n"
                    f"Test Errors:\n{context['error_output'][:1500]}\n\n"
                    "Provide the complete corrected code."
                ),
            },
        ]

        raw = llm_call("reasoning", messages, json_mode=True)
        result = parse_json_response(raw)
        logger.info(f"Fix generated with {len(result.get('changes_made', []))} changes")
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
        root_cause: dict,
        fix_result: dict,
        fixed_filepath: Path | None,
    ) -> tuple[str, str]:
        """Create Bug and Fix nodes in Neo4j."""
        # Bug node
        bug_id = str(uuid.uuid4())
        create_node("Bug", {
            "id": bug_id,
            "task_id": task_id,
            "error_type": root_cause.get("error_type", "Unknown"),
            "root_cause": root_cause.get("root_cause", ""),
            "affected_lines": json.dumps(root_cause.get("affected_lines", [])),
            "chain_of_thought": json.dumps(root_cause.get("chain_of_thought", [])),
        })

        # Fix node
        fix_id = str(uuid.uuid4())
        create_node("Fix", {
            "id": fix_id,
            "bug_id": bug_id,
            "task_id": task_id,
            "changes_made": json.dumps(fix_result.get("changes_made", [])),
            "explanation": fix_result.get("explanation", ""),
            "fixed_filepath": str(fixed_filepath) if fixed_filepath else "",
        })

        # Relationships
        link_nodes(bug_id, fix_id, "RESOLVES")
        if context.get("module_id"):
            link_nodes(bug_id, context["module_id"], "FAILED_BY")
            link_nodes(fix_id, context["module_id"], "FIXED_BY")

        logger.info(f"Bug {bug_id} and Fix {fix_id} stored in Neo4j")
        return bug_id, fix_id
