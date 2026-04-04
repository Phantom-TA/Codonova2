"""
context_retriever.py — Similar Context Finder
=============================================
Queries ChromaDB for top-3 similar past successful patterns
and formats them as few-shot examples for LLM prompt injection.
"""

import logging
from memory.memory_store import MemoryStore

logger = logging.getLogger("context_retriever")


class ContextRetriever:
    """
    Retrieves similar successful past solutions for context injection.
    """

    def __init__(self):
        self.memory = MemoryStore()

    def get_similar_context(self, query: str, n: int = 3) -> list[dict]:
        """
        Find top-N similar successful patterns from memory.

        Args:
            query: Current task description/title to match against
            n: Number of examples to retrieve

        Returns:
            List of dicts with 'task', 'code', 'score', 'similarity'
        """
        if not query or not query.strip():
            return []

        similar = self.memory.query_similar(query_text=query, n_results=n)

        if similar:
            logger.info(
                f"Context retrieval: found {len(similar)} similar patterns "
                f"(best similarity={similar[0].get('similarity', 0):.2f})"
            )
        else:
            logger.debug("No similar patterns found in memory.")

        return similar

    def format_for_prompt(self, similar_examples: list[dict]) -> str:
        """
        Format retrieved examples as a string for LLM prompt injection.
        """
        if not similar_examples:
            return ""

        lines = ["Here are similar tasks solved successfully before:\n"]
        for i, ex in enumerate(similar_examples, 1):
            lines.append(f"--- Example {i} (score={ex.get('score'):.1f}, "
                         f"similarity={ex.get('similarity', 0):.2f}) ---")
            lines.append(f"Task: {ex.get('task', '')}")
            lines.append(f"Solution:\n{ex.get('code', '')}")
            lines.append("")

        return "\n".join(lines)
