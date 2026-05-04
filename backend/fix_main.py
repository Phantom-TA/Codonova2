import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = '@app.get("/api/llm-log")'
end_marker   = '@app.get("/api/projects")'

start_idx = content.find(start_marker)
end_idx   = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print(f'ERROR: markers not found. start={start_idx}, end={end_idx}')
    exit(1)

replacement = r'''@app.get("/api/llm-log")
async def get_llm_log():
    """Return the LLM call log for monitoring."""
    from llm_client import get_call_log
    log = get_call_log()
    return {"total_calls": len(log), "calls": log[-100:]}


@app.get("/api/analytics/agents")
async def get_agent_analytics(project_id: Optional[str] = None):
    """
    Per-agent analytics. Handles both old log format (agent_type='reasoning'/'fast')
    and new format (agent_type='PlanningAgent', model_tier='reasoning').
    """
    from llm_client import get_call_log
    from graph.neo4j_client import get_agent_retry_rates, get_most_failed_task_types

    all_calls = get_call_log()
    if project_id:
        call_log = [e for e in all_calls if e.get("project_id") == project_id]
        scope = f"project:{project_id[:8]}"
    else:
        call_log = all_calls
        scope = "global"

    TIER_NAMES = {"reasoning", "fast"}

    def _resolve(entry):
        raw_agent = entry.get("agent_type") or "unknown"
        raw_tier  = entry.get("model_tier")  or ""
        # Old entries: agent_type held the tier name
        if raw_agent in TIER_NAMES and not raw_tier:
            return "unknown", raw_agent
        return raw_agent, raw_tier or "unknown"

    def _agg(entries, group_key):
        stats = {}
        for entry in entries:
            agent_key, tier_key = _resolve(entry)
            key = (agent_key if group_key == "agent_type" else tier_key) or "unknown"
            if key not in stats:
                stats[key] = {
                    "total_calls": 0, "successful_calls": 0, "failed_calls": 0,
                    "total_tokens": 0, "total_latency_ms": 0, "models_used": set(),
                }
            s = stats[key]
            s["total_calls"]      += 1
            s["successful_calls"] += int(bool(entry.get("success")))
            s["failed_calls"]     += int(not bool(entry.get("success")))
            s["total_tokens"]     += entry.get("tokens_used") or 0
            s["total_latency_ms"] += entry.get("latency_ms")  or 0
            s["models_used"].add(entry.get("model", "unknown"))
        for s in stats.values():
            calls = s["total_calls"] or 1
            s["avg_latency_ms"]   = round(s["total_latency_ms"] / calls, 1)
            s["success_rate_pct"] = round((s["successful_calls"] / calls) * 100, 1)
            s["models_used"]      = list(s["models_used"])
        return stats

    agent_stats      = _agg(call_log, "agent_type")
    model_tier_stats = _agg(call_log, "model_tier")

    neo4j_agents = []
    try:
        neo4j_agents = get_agent_retry_rates()
        if project_id:
            for ag in neo4j_agents:
                ag_s = agent_stats.get(ag.get("agent", ""), {})
                ag["project_tokens"] = ag_s.get("total_tokens", 0)
                ag["project_calls"]  = ag_s.get("total_calls",  0)
    except Exception:
        pass

    total_tokens = sum(s["total_tokens"] for s in agent_stats.values())
    total_calls  = sum(s["total_calls"]  for s in agent_stats.values())
    total_failed = sum(s["failed_calls"] for s in agent_stats.values())

    failed_types = []
    try:
        failed_types = get_most_failed_task_types()
    except Exception:
        pass

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "scope": scope,
        "summary": {
            "total_llm_calls":          total_calls,
            "total_tokens_used":        total_tokens,
            "total_failed_calls":       total_failed,
            "overall_success_rate_pct": round(((total_calls - total_failed) / max(1, total_calls)) * 100, 1),
        },
        "per_agent":              agent_stats,
        "per_model_tier":         model_tier_stats,
        "neo4j_agents":           neo4j_agents,
        "most_failed_task_types": failed_types,
    }


'''

new_content = content[:start_idx] + replacement + content[end_idx:]

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f'Done. File is now {len(new_content)} bytes.')

# Verify syntax
import ast, sys
try:
    ast.parse(new_content)
    print('Syntax OK')
except SyntaxError as e:
    print(f'Syntax ERROR: {e}')
    sys.exit(1)
