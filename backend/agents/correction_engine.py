"""
correction_engine.py — Self-Correction & Re-planning Engine
============================================================
Orchestrates the feedback loop:
  1. If score < 7: retry with critique (max 3 attempts)
  2. Each attempt = versioned CodeModule in Neo4j
  3. If still failing after 3 retries: escalate to Planning Agent
  4. Block downstream dependent tasks on failure

Integrates with WebSocket event emitter for real-time updates.
"""

import json
import logging
from datetime import datetime
from .developer_agent import DeveloperAgent
from .testing_agent import TestingAgent
from .evaluator_agent import EvaluatorAgent
from .debugging_agent import DebuggingAgent
from graph.neo4j_client import (
    query_graph, block_dependent_tasks, create_node, link_nodes,
    mark_task_status
)
from memory.memory_store import MemoryStore

logger = logging.getLogger("correction_engine")

PASS_SCORE = 7
MAX_RETRIES = 3


class CorrectionEngine:
    """
    Manages the self-correction loop for code generation tasks.
    Retries failing code with critiques, then escalates if needed.
    """

    def __init__(self, ws_broadcaster=None):
        self.dev_agent = DeveloperAgent()
        self.test_agent = TestingAgent()
        self.eval_agent = EvaluatorAgent()
        self.debug_agent = DebuggingAgent()
        self.memory = MemoryStore()
        self.ws_broadcaster = ws_broadcaster  # Async callable for WebSocket events

    async def run(self, task_node: dict) -> dict:
        """
        Execute a CODE task with full self-correction loop.

        Returns:
            dict with final status, score, attempts used
        """
        task_id = task_node["id"]
        logger.info(f"CorrectionEngine starting for task: {task_id}")

        await self._emit("task_started", task_id=task_id, agent="DeveloperAgent")

        attempts = 0
        last_eval = None
        last_critique = ""

        while attempts < MAX_RETRIES:
            attempts += 1
            logger.info(f"Attempt {attempts}/{MAX_RETRIES} for task {task_id}")

            # 1. Generate/regenerate code
            if attempts == 1:
                dev_result = self.dev_agent.run(task_node)
            else:
                dev_result = self.dev_agent.run_with_critique(
                    task_node, last_critique, version=attempts
                )

            if not dev_result.get("success"):
                logger.error(f"Developer agent failed on attempt {attempts}")
                await self._emit("task_failed", task_id=task_id, retry=attempts, agent="DeveloperAgent")
                continue

            # 2. Run tests
            await self._emit("task_started", task_id=task_id, agent="TestingAgent")
            test_result = self.test_agent.run(task_node)

            # 3. Evaluate quality
            await self._emit("task_started", task_id=task_id, agent="EvaluatorAgent")
            eval_result = self.eval_agent.run(task_node)
            score = eval_result.get("score", 0)
            last_eval = eval_result

            await self._emit(
                "task_done",
                task_id=task_id,
                agent="EvaluatorAgent",
                score=score,
                attempt=attempts,
            )

            logger.info(f"Attempt {attempts}: score={score}, passed={score >= PASS_SCORE}")

            if score >= PASS_SCORE:
                # ✅ Success — store in memory
                self.memory.store_success(
                    task_description=task_node.get("description", "") + " " + task_node.get("title", ""),
                    code=self._get_generated_code(dev_result.get("filename", "")),
                    score=score,
                    task_id=task_id,
                    module_id=dev_result.get("code_module_id", ""),
                )
                mark_task_status(task_id, "DONE")
                await self._emit("task_done", task_id=task_id, score=score, agent="Pipeline")
                return {
                    "status": "DONE",
                    "task_id": task_id,
                    "score": score,
                    "attempts": attempts,
                }

            # ❌ Score < 7 — prepare critique for next attempt
            critique_parts = [eval_result.get("critique", "")]
            suggestions = eval_result.get("suggestions", [])
            if suggestions:
                critique_parts.append("Suggestions: " + "; ".join(suggestions))

            # If tests failed, also run debugger
            if not test_result.get("success"):
                await self._emit("task_started", task_id=task_id, agent="DebuggingAgent")
                debug_result = self.debug_agent.run(task_node)
                critique_parts.append(
                    f"Bug found: {debug_result.get('root_cause', '')}. "
                    f"Fix applied: {', '.join(debug_result.get('changes', []))}"
                )

            last_critique = "\n".join(critique_parts)
            await self._emit("task_failed", task_id=task_id, retry=attempts, agent="Pipeline")
            logger.info(f"Retrying with critique: {last_critique[:200]}...")

        # ─── All retries exhausted ────────────────────────────────────────────
        logger.warning(f"Task {task_id} failed after {MAX_RETRIES} attempts. Escalating...")

        # Block dependent tasks
        blocked = block_dependent_tasks(task_id)
        if blocked:
            logger.info(f"Blocked {len(blocked)} dependent tasks: {blocked}")

        # Escalate — re-plan this task with critique context
        await self._escalate_to_planner(task_node, last_eval)

        mark_task_status(task_id, "FAILED")
        await self._emit("task_failed", task_id=task_id, retry=MAX_RETRIES, agent="Escalated")

        return {
            "status": "FAILED",
            "task_id": task_id,
            "score": last_eval.get("score", 0) if last_eval else 0,
            "attempts": attempts,
            "blocked_tasks": blocked,
        }

    async def _escalate_to_planner(self, task_node: dict, last_eval: dict | None):
        """Re-plan the failed task using the Planning Agent."""
        from .planning_agent import PlanningAgent
        planner = PlanningAgent()

        critique = ""
        if last_eval:
            critique = (
                f"Previous attempts failed. Issues: {last_eval.get('critique', '')}. "
                f"Suggestions: {'; '.join(last_eval.get('suggestions', []))}"
            )

        # Re-plan just this task with the critique as additional context
        augmented_requirement = (
            f"Fix this failing task: {task_node.get('title')}\n"
            f"Original description: {task_node.get('description')}\n"
            f"Known issues: {critique}"
        )
        logger.info(f"Escalating to PlanningAgent with augmented requirement...")
        # Note: Full re-planning would create new subtasks; simplified here
        create_node("Decision", {
            "decision": f"Escalated task {task_node['id']} to re-planning",
            "reason": critique,
            "task_id": task_node["id"],
        })

    def _get_generated_code(self, filepath: str) -> str:
        """Read generated code for memory storage."""
        from pathlib import Path
        try:
            return Path(filepath).read_text(encoding="utf-8")
        except Exception:
            return ""

    async def _emit(self, event: str, **kwargs):
        """Emit WebSocket event if broadcaster is available."""
        if self.ws_broadcaster:
            try:
                payload = {
                    "event": event,
                    "timestamp": datetime.utcnow().isoformat(),
                    **kwargs,
                }
                await self.ws_broadcaster(json.dumps(payload))
            except Exception as e:
                logger.debug(f"WebSocket emit failed: {e}")
