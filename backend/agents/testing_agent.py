"""
testing_agent.py — Automated Test Generation & Execution Agent
==============================================================
Uses Groq Llama 4 Scout (fast) for test generation.
Reads CodeModule nodes, generates pytest tests, runs them via subprocess,
stores TestCase + TestResult nodes in Neo4j.
"""

import os
import json
import uuid
import subprocess
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from llm_client import llm_call, parse_json_response
from graph.neo4j_client import (
    create_node, link_nodes, query_graph, get_node, upsert_agent, update_agent_profile
)

logger = logging.getLogger("testing_agent")

GENERATED_CODE_DIR = Path(os.getenv("GENERATED_CODE_DIR", "./generated_code"))

TEST_GEN_SYSTEM = """Write a Jest test suite for the given code. Return JSON only:
{
  "test_filename": "tests/module_name.test.js",
  "test_code": "const m = require('../module');\\n// tests",
  "test_cases": [
    {"name": "test_name", "description": "what it checks"}
  ]
}
Rules:
- Write 2-4 tests only (happy path + key edge case)
- Use Jest describe/it
- Import module relative to its filename
- No markdown in test_code"""


class TestingAgent:
    """
    Generates and executes pytest tests for generated code modules.
    """

    AGENT_NAME = "TestingAgent"

    def __init__(self):
        upsert_agent(self.AGENT_NAME)


    def run(self, task_node: dict) -> dict:
        """
        Generate and run tests for the CodeModule associated with this task.

        Args:
            task_node: Task dict from Neo4j

        Returns:
            dict with test results summary
        """
        task_id = task_node["id"]
        logger.info(f"TestingAgent processing task: {task_id}")

        # Find CodeModule for this task
        code_module = self._get_code_module(task_id)
        if not code_module:
            logger.warning(f"No CodeModule found for task {task_id}")
            return {"success": False, "reason": "No CodeModule found"}

        # Read source code from filesystem
        filepath = code_module.get("filepath", "")
        source_code = self._read_source(filepath)
        if not source_code:
            return {"success": False, "reason": f"Cannot read source: {filepath}"}

        # Generate tests
        test_result = self._generate_tests(task_node, code_module, source_code)

        # Write test file
        project_id = task_node.get("project_id", "default_project")
        test_filepath = self._write_tests(test_result, project_id)

        self._ensure_npm_env(project_id)

        # Run tests
        run_results = self._run_tests(test_filepath, project_id)

        # Store in Neo4j
        self._store_results(task_id, code_module["id"], test_result, run_results, test_filepath)

        update_agent_profile(
            self.AGENT_NAME,
            score=8.0 if run_results["passed"] > 0 else 4.0,
            task_type="TEST",
            retries=0,
        )

        return {
            "success": run_results["all_passed"],
            "task_id": task_id,
            "tests_written": len(test_result.get("test_cases", [])),
            "tests_passed": run_results["passed"],
            "tests_failed": run_results["failed"],
            "test_output": run_results["output"],
        }

    def _get_code_module(self, task_id: str) -> dict | None:
        """Find the most recent CodeModule for a task."""
        cypher = """
        MATCH (cm:CodeModule)-[:PRODUCED_BY]->(t:Task {id: $task_id})
        RETURN properties(cm) AS module
        ORDER BY cm.version DESC
        LIMIT 1
        """
        results = query_graph(cypher, {"task_id": task_id})
        return results[0]["module"] if results else None

    def _read_source(self, filepath: str) -> str | None:
        """Read source code from filesystem."""
        try:
            return Path(filepath).read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Cannot read {filepath}: {e}")
            return None

    def _generate_tests(self, task_node: dict, code_module: dict, source_code: str) -> dict:
        """Use Groq to generate pytest tests."""
        messages = [
            {"role": "system", "content": TEST_GEN_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Task: {task_node.get('title', '')}\n"
                    f"Description: {task_node.get('description', '')}\n"
                    f"Filename: {code_module.get('filename', '')}\n"
                    f"Module Type: {code_module.get('module_type', '')}\n\n"
                    f"Source Code:\n```python\n{source_code}\n```\n\n"
                    "Generate comprehensive pytest tests for this code."
                ),
            },
        ]
        raw = llm_call("fast", messages, json_mode=True)
        return parse_json_response(raw)

    def _write_tests(self, test_result: dict, project_id: str) -> Path:
        """Write test file to filesystem."""
        test_filename = test_result.get("test_filename", f"tests/test_generated_{uuid.uuid4().hex[:8]}.test.js")
        test_filename = test_filename.replace("..", "").lstrip("/")
        test_filepath = GENERATED_CODE_DIR / project_id / test_filename
        test_filepath.parent.mkdir(parents=True, exist_ok=True)
        test_code = test_result.get("test_code", "// No tests generated")
        test_filepath.write_text(test_code, encoding="utf-8")
        logger.info(f"Test file written: {test_filepath}")
        return test_filepath

    def _ensure_npm_env(self, project_id: str):
        project_dir = GENERATED_CODE_DIR / project_id
        pkg_json = project_dir / "package.json"
        if not pkg_json.exists():
            pkg_json.write_text('{"name": "codonova-project", "scripts": {"test": "jest"}}')

    def _run_tests(self, test_filepath: Path, project_id: str) -> dict:
        """Execute jest and parse results."""
        report_file = test_filepath.parent / f".report_{test_filepath.stem}.json"
        project_dir = GENERATED_CODE_DIR / project_id

        # Use 'npx --yes jest' to bypass the install prompt if jest is missing locally
        cmd = [
            "npx", "--yes", "jest",
            str(test_filepath.relative_to(project_dir)),
            "--json",
            f"--outputFile={report_file}",
            "--passWithNoTests"
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(project_dir),
            )
            output = proc.stdout + proc.stderr

            # Parse JSON report if available
            passed, failed, errors_list = 0, 0, []
            if report_file.exists():
                try:
                    report = json.loads(report_file.read_text())
                    passed = report.get("numPassedTests", 0)
                    failed = report.get("numFailedTests", 0)
                    # Extract error messages
                    for test_res in report.get("testResults", []):
                        if test_res.get("status") == "failed":
                            msg = test_res.get("message", "")[:500]
                            errors_list.append({"test": "jest", "message": msg})
                    report_file.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Could not parse Jest report: {e}")
                    passed = 1 if proc.returncode == 0 else 0
                    failed = 0 if proc.returncode == 0 else 1
            else:
                passed = 1 if proc.returncode == 0 else 0
                failed = 0 if proc.returncode == 0 else 1

            return {
                "all_passed": failed == 0 and passed > 0,
                "passed": passed,
                "failed": failed,
                "output": output[:3000],
                "errors": errors_list,
                "return_code": proc.returncode,
            }

        except subprocess.TimeoutExpired:
            logger.error(f"Test execution timed out for {test_filepath}")
            return {
                "all_passed": False,
                "passed": 0,
                "failed": 1,
                "output": "Test execution timed out after 120 seconds",
                "errors": [{"test": "timeout", "message": "Execution timed out"}],
                "return_code": -1,
            }
        except Exception as e:
            logger.error(f"Test execution error: {e}")
            return {
                "all_passed": False,
                "passed": 0,
                "failed": 1,
                "output": str(e),
                "errors": [{"test": "execution_error", "message": str(e)}],
                "return_code": -1,
            }

    def _store_results(
        self,
        task_id: str,
        module_id: str,
        test_result: dict,
        run_results: dict,
        test_filepath: Path,
    ):
        """Create TestCase and TestResult nodes in Neo4j."""
        # Create TestCase nodes
        for tc in test_result.get("test_cases", []):
            tc_id = str(uuid.uuid4())
            create_node("TestCase", {
                "id": tc_id,
                "name": tc.get("name", ""),
                "description": tc.get("description", ""),
                "test_file": str(test_filepath),
            })
            link_nodes(tc_id, module_id, "VALIDATES")

        # Create TestResult node
        tr_id = str(uuid.uuid4())
        status = "PASSED" if run_results["all_passed"] else "FAILED"
        create_node("TestResult", {
            "id": tr_id,
            "status": status,
            "tests_passed": run_results["passed"],
            "tests_failed": run_results["failed"],
            "output": run_results["output"][:2000],
            "errors": json.dumps(run_results.get("errors", [])),
            "task_id": task_id,
        })
        link_nodes(tr_id, module_id, "VALIDATES")

        # Mark task accordingly
        from graph.neo4j_client import mark_task_status
        mark_task_status(task_id, "DONE" if run_results["all_passed"] else "FAILED")
        logger.info(f"TestResult {tr_id}: {status}")
