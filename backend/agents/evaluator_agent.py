"""
evaluator_agent.py — Code Quality Evaluation Agent
===================================================
Uses Groq Llama 4 Scout (fast) for rapid quality assessment.
Scores code output 0-10 on correctness, quality, and completeness.
Stores EvaluationResult node in Neo4j.
"""

import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from llm_client import llm_call, parse_json_response, set_active_agent
from graph.neo4j_client import (
    create_node, link_nodes, query_graph, upsert_agent, update_agent_profile
)

logger = logging.getLogger("evaluator_agent")

EVAL_SYSTEM = """Score AI-generated code. Return JSON only:
{
  "scores": {"correctness": 8, "code_quality": 7, "completeness": 9},
  "score": 8.0,
  "critique": "One sentence summary",
  "suggestions": ["fix 1"],
  "strengths": ["strength 1"],
  "passed": true
}
scored 0-10. passed=true if score>=7."""


class EvaluatorAgent:
    """
    Evaluates generated code modules and stores quality metrics in Neo4j.
    """

    AGENT_NAME = "EvaluatorAgent"

    def __init__(self):
        upsert_agent(self.AGENT_NAME)

    def run(self, task_node: dict) -> dict:
        """
        Evaluate the CodeModule for a given task.

        Args:
            task_node: Task dict from Neo4j

        Returns:
            dict with score, critique, and suggestions
        """
        task_id = task_node["id"]
        logger.info(f"EvaluatorAgent assessing task: {task_id}")
        set_active_agent(self.AGENT_NAME)

        # Get code module and test results
        context = self._gather_eval_context(task_id)
        if not context:
            logger.warning(f"No context for evaluation of task {task_id}")
            return {
                "score": 0,
                "passed": False,
                "critique": "No code module found for evaluation",
                "suggestions": [],
            }

        # Run evaluation
        eval_result = self._evaluate(task_node, context)

        # Store in Neo4j
        eval_id = self._store_eval_result(task_id, context.get("module_id"), eval_result)

        update_agent_profile(
            self.AGENT_NAME,
            score=9.0,
            task_type="EVAL",
            retries=0,
        )

        return {
            **eval_result,
            "eval_id": eval_id,
            "task_id": task_id,
        }

    def _gather_eval_context(self, task_id: str) -> dict | None:
        """Gather code and test results for evaluation."""
        cypher = """
        MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t:Task {id: $task_id})
        OPTIONAL MATCH (tr:TestResult)-[:VALIDATES]->(cm)
        RETURN
          cm.id AS module_id,
          cm.filepath AS filepath,
          cm.filename AS filename,
          cm.module_type AS module_type,
          cm.explanation AS explanation,
          tr.status AS test_status,
          tr.tests_passed AS tests_passed,
          tr.tests_failed AS tests_failed,
          tr.output AS test_output
        ORDER BY cm.version DESC
        LIMIT 1
        """
        results = query_graph(cypher, {"task_id": task_id})
        if not results:
            return None

        row = results[0]
        source_code = ""
        filepath = row.get("filepath", "")
        if filepath and Path(filepath).exists():
            source_code = Path(filepath).read_text(encoding="utf-8")

        return {
            "module_id": row.get("module_id"),
            "filename": row.get("filename"),
            "module_type": row.get("module_type"),
            "explanation": row.get("explanation"),
            "source_code": source_code,
            "test_status": row.get("test_status"),
            "tests_passed": row.get("tests_passed", 0),
            "tests_failed": row.get("tests_failed", 0),
            "test_output": row.get("test_output", ""),
        }

    def _evaluate(self, task_node: dict, context: dict) -> dict:
        """Send code to Groq for quality evaluation."""
        test_summary = (
            f"Tests: {context['tests_passed']} passed, {context['tests_failed']} failed. "
            f"Status: {context['test_status'] or 'Not run'}"
        )

        messages = [
            {"role": "system", "content": EVAL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Task: {task_node.get('title')}\n"
                    f"File: {context['filename']} ({context['module_type']})\n"
                    f"Tests: {context['tests_passed']} passed / {context['tests_failed']} failed\n\n"
                    f"Code (first 1000 chars):\n{context['source_code'][:1000]}"
                ),
            },
        ]

        raw = llm_call("fast", messages, json_mode=True)
        result = parse_json_response(raw)
        logger.info(
            f"Evaluation: score={result.get('score')}, passed={result.get('passed')}"
        )
        return result

    def _store_eval_result(
        self, task_id: str, module_id: str | None, eval_result: dict
    ) -> str:
        """Store EvaluationResult node in Neo4j."""
        eval_id = str(uuid.uuid4())
        scores = eval_result.get("scores", {})

        create_node("EvaluationResult", {
            "id": eval_id,
            "task_id": task_id,
            "score": eval_result.get("score", 0),
            "correctness": scores.get("correctness", 0),
            "code_quality": scores.get("code_quality", 0),
            "completeness": scores.get("completeness", 0),
            "critique": eval_result.get("critique", ""),
            "suggestions": json.dumps(eval_result.get("suggestions", [])),
            "strengths": json.dumps(eval_result.get("strengths", [])),
            "passed": eval_result.get("passed", False),
        })

        if module_id:
            link_nodes(eval_id, module_id, "EVALUATES")

        logger.info(f"EvaluationResult {eval_id} stored (score={eval_result.get('score')})")
        return eval_id
