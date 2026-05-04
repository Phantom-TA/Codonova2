import sys
sys.path.append('.')
from graph.neo4j_client import query_graph
from datetime import datetime

try:
    # Get all projects
    projects = query_graph("MATCH (p:Project) RETURN p.id AS id, p.title AS title, p.created_at AS created_at")
    for p in projects:
        # Get max task completion time
        cypher = """
        MATCH (p:Project {id: $pid})-[:HAS_FEATURE]->(:Feature)-[:HAS_TASK]->(t:Task)
        RETURN min(t.created_at) as first_task, max(t.updated_at) as last_task
        """
        res = query_graph(cypher, {"pid": p["id"]})
        if res and res[0]["first_task"] and res[0]["last_task"]:
            try:
                first = datetime.fromisoformat(res[0]["first_task"].replace("Z", "+00:00"))
                last = datetime.fromisoformat(res[0]["last_task"].replace("Z", "+00:00"))
                duration = (last - first).total_seconds() / 60.0
                print(f"Project: {p['title']} - Duration: {duration:.1f} minutes")
            except Exception as e:
                pass
except Exception as e:
    print(f"Error: {e}")
