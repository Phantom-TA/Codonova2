#!/usr/bin/env python3
"""
setup.py — Quick setup validator for Codonova
Checks environment variables, connectivity, and dependencies.
Run: python setup.py
"""

import os
import sys

def check_env():
    """Check required environment variables."""
    from dotenv import load_dotenv
    load_dotenv()

    required = [
        ("GEMINI_API_KEY", "Get from https://aistudio.google.com"),
        ("GROQ_API_KEY", "Get from https://console.groq.com"),
        ("NEO4J_PASSWORD", "Set a password for Neo4j"),
    ]
    optional = [
        ("OPENROUTER_API_KEY", "Optional fallback — get from https://openrouter.ai"),
    ]

    print("=== Environment Variables ===")
    all_ok = True
    for key, hint in required:
        val = os.getenv(key, "")
        if val and val != f"your_{key.lower()}_here":
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key} — {hint}")
            all_ok = False

    for key, hint in optional:
        val = os.getenv(key, "")
        status = "✓" if (val and "your_" not in val) else "○"
        print(f"  {status} {key} (optional)")

    return all_ok

def check_imports():
    """Check Python dependencies."""
    print("\n=== Python Dependencies ===")
    deps = [
        ("openai", "pip install openai"),
        ("dotenv", "pip install python-dotenv"),
        ("neo4j", "pip install neo4j"),
        ("fastapi", "pip install fastapi"),
        ("uvicorn", "pip install uvicorn[standard]"),
        ("chromadb", "pip install chromadb"),
        ("sentence_transformers", "pip install sentence-transformers"),
        ("pytest", "pip install pytest pytest-json-report"),
    ]
    all_ok = True
    for pkg, install in deps:
        try:
            __import__(pkg)
            print(f"  ✓ {pkg}")
        except ImportError:
            print(f"  ✗ {pkg} — {install}")
            all_ok = False
    return all_ok

def check_neo4j():
    """Check Neo4j connectivity."""
    print("\n=== Neo4j Connection ===")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
        )
        with driver.session() as s:
            result = s.run("RETURN 1 AS ok").single()
            if result and result["ok"] == 1:
                print("  ✓ Neo4j connected")
                driver.close()
                return True
    except Exception as e:
        print(f"  ✗ Neo4j not reachable: {e}")
        print("    Run: docker-compose up neo4j -d")
    return False

def check_chromadb():
    """Check ChromaDB connectivity."""
    print("\n=== ChromaDB Connection ===")
    try:
        import chromadb
        from dotenv import load_dotenv
        load_dotenv()
        host = os.getenv("CHROMA_HOST", "localhost")
        port = int(os.getenv("CHROMA_PORT", "8001"))
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        print(f"  ✓ ChromaDB connected at {host}:{port}")
        return True
    except Exception as e:
        print(f"  ○ ChromaDB not reachable (will use local fallback): {e}")
    return False

def main():
    print("Codonova Setup Validator")
    print("=" * 40)

    env_ok = check_env()
    deps_ok = check_imports()
    neo4j_ok = check_neo4j()
    check_chromadb()

    print("\n" + "=" * 40)
    if env_ok and deps_ok and neo4j_ok:
        print("✅ Ready to run! Start the server:")
        print("   uvicorn main:app --reload --port 8000")
    else:
        issues = []
        if not env_ok: issues.append("Set API keys in .env")
        if not deps_ok: issues.append("Install missing packages")
        if not neo4j_ok: issues.append("Start Neo4j (docker-compose up neo4j -d)")
        print("⚠  Fix these issues first:")
        for i in issues:
            print(f"   • {i}")

if __name__ == "__main__":
    main()
