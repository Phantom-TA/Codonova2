"""
scheduler.py — Task Scheduler & Agent Router
=============================================
Polls Neo4j every 10 seconds for PENDING tasks.
Routes tasks to the correct agent based on task.type:
  CODE  → CorrectionEngine (wraps DeveloperAgent + TestingAgent + EvaluatorAgent)
  TEST  → TestingAgent
  DEBUG → DebuggingAgent

Updates task status: PENDING → IN_PROGRESS → DONE/FAILED
"""

import asyncio
import logging
from datetime import datetime
from graph.neo4j_client import (
    get_pending_tasks, mark_task_status, query_graph
)
from agents.correction_engine import CorrectionEngine
from agents.testing_agent import TestingAgent
from agents.debugging_agent import DebuggingAgent

logger = logging.getLogger("scheduler")

POLL_INTERVAL = 10  # seconds


class Scheduler:
    """
    Autonomous task scheduler that drives the full pipeline.
    """

    def __init__(self, project_id: str, ws_broadcaster=None):
        self.project_id = project_id
        self.ws_broadcaster = ws_broadcaster
        self.running = False
        self.correction_engine = CorrectionEngine(ws_broadcaster=ws_broadcaster)
        self.test_agent = TestingAgent()
        self.debug_agent = DebuggingAgent()

    async def start(self):
        """Start polling loop."""
        self.running = True
        logger.info(f"Scheduler started for project: {self.project_id}")

        while self.running:
            try:
                await self._poll_and_dispatch()
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)

            # Check if project is complete
            if await self._is_project_complete():
                logger.info(f"Project {self.project_id} is complete. Stopping scheduler.")
                await self._finalize_project()
                self.running = False
                break

            await asyncio.sleep(POLL_INTERVAL)

    def stop(self):
        """Stop the polling loop."""
        self.running = False
        logger.info("Scheduler stopped.")

    async def _poll_and_dispatch(self):
        """Get all ready tasks and dispatch them."""
        pending = get_pending_tasks(self.project_id)

        if not pending:
            logger.debug(f"No pending tasks for project {self.project_id}")
            return

        logger.info(f"Found {len(pending)} ready task(s) to dispatch")

        # Dispatch tasks concurrently (up to 3 at a time)
        tasks_to_run = pending[:3]  # Rate limit
        dispatch_tasks = [self._dispatch(task) for task in tasks_to_run]
        await asyncio.gather(*dispatch_tasks, return_exceptions=True)

    async def _dispatch(self, task_node: dict):
        """Route a single task to the appropriate agent."""
        task_id = task_node["id"]
        task_type = task_node.get("type", "CODE")
        title = task_node.get("title", "Unknown")

        logger.info(f"Dispatching task [{task_type}]: {title}")

        # Mark as in-progress
        mark_task_status(task_id, "IN_PROGRESS")

        try:
            if task_type == "CODE":
                result = await self.correction_engine.run(task_node)
            elif task_type == "TEST":
                result = self.test_agent.run(task_node)
                # Determine task completion
                status = "DONE" if result.get("success") else "FAILED"
                mark_task_status(task_id, status)
            elif task_type == "DEBUG":
                result = self.debug_agent.run(task_node)
                # After debugging, put the task back for re-testing
                if result.get("needs_retest"):
                    # Find the original CODE task and reset it
                    mark_task_status(task_id, "DONE")  # DEBUG task done
                else:
                    mark_task_status(task_id, "FAILED")
            else:
                logger.warning(f"Unknown task type: {task_type}")
                mark_task_status(task_id, "FAILED")

        except Exception as e:
            logger.error(f"Task {task_id} failed with exception: {e}", exc_info=True)
            mark_task_status(task_id, "FAILED")

    async def _is_project_complete(self) -> bool:
        """Check if all tasks in the project are done or failed."""
        cypher = """
        MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
        WHERE t.status IN ['PENDING', 'IN_PROGRESS']
        RETURN count(t) AS pending_count
        """
        result = query_graph(cypher, {"project_id": self.project_id})
        pending = result[0]["pending_count"] if result else 0
        return pending == 0

    async def _finalize_project(self):
        """Mark project as complete and create snapshot."""
        from graph.neo4j_client import query_graph, create_project_snapshot
        # Calculate final stats
        cypher = """
        MATCH (p:Project {id: $project_id})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
        RETURN
          count(CASE WHEN t.status = 'DONE' THEN 1 END) AS done_count,
          count(CASE WHEN t.status = 'FAILED' THEN 1 END) AS failed_count,
          count(t) AS total_count
        """
        result = query_graph(cypher, {"project_id": self.project_id})
        if result:
            stats = result[0]
            final_status = "COMPLETED" if stats["failed_count"] == 0 else "COMPLETED_WITH_ERRORS"
            query_graph(
                "MATCH (p:Project {id: $pid}) SET p.status = $status, p.completed_at = $ts",
                {"pid": self.project_id, "status": final_status, "ts": datetime.utcnow().isoformat()},
            )
            create_project_snapshot(self.project_id)
            logger.info(
                f"Project finalized: {stats['done_count']}/{stats['total_count']} tasks done"
            )

        # Emit final event
        if self.ws_broadcaster:
            import json
            await self.ws_broadcaster(json.dumps({
                "event": "project_complete",
                "project_id": self.project_id,
                "timestamp": datetime.utcnow().isoformat(),
            }))
