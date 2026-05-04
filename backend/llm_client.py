"""
llm_client.py — Shared LLM Client for Codonova
================================================
All agents must import llm_call() from this module.
Never instantiate OpenAI clients directly in agent files.

LLM Routing:
  "reasoning" → Gemini 2.5 Flash (planning, dev, debug)
  "fast"      → Groq Llama 4 Scout (testing, evaluation)
  Fallback    → OpenRouter on 429 / rate limit
"""

import os
import time
import json
import logging
import re
import threading
from datetime import datetime
from contextvars import ContextVar
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
# Logger Setup
# ─────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("llm_client")


# ─────────────────────────────────────────
# Project + Agent Context
# ─────────────────────────────────────────
_active_project: ContextVar[str] = ContextVar('active_project', default='__global__')
_active_agent:   ContextVar[str] = ContextVar('active_agent',   default='unknown')

def set_active_project(project_id: str):
    """Tag all subsequent LLM calls in this context with the given project_id."""
    _active_project.set(project_id)

def set_active_agent(agent_name: str):
    """Tag all subsequent LLM calls in this context with the calling agent name."""
    _active_agent.set(agent_name)


# ─────────────────────────────────────────
# Call Log (in-memory for metrics)
# ─────────────────────────────────────────
call_log: list[dict] = []


def _preload_from_neo4j():
    """On startup, load historical LLM calls from Neo4j into the in-memory log."""
    try:
        from graph.neo4j_client import load_llm_call_log
        historical = load_llm_call_log(limit=2000)
        if historical:
            call_log.extend(historical)
            logger.info(f"Preloaded {len(historical)} LLM call log entries from Neo4j.")
    except Exception as e:
        logger.debug(f"Could not preload LLM call log from Neo4j (first start?): {e}")

# Preload in background so it doesn't block startup
threading.Thread(target=_preload_from_neo4j, daemon=True).start()


def _log_call(model_tier: str, model: str, latency_ms: float, tokens: int | None, success: bool):
    entry = {
        "timestamp":   datetime.utcnow().isoformat(),
        "agent_type":  _active_agent.get(),   # named agent: PlanningAgent, DeveloperAgent...
        "model_tier":  model_tier,             # 'reasoning' or 'fast'
        "model":       model,
        "latency_ms":  round(latency_ms, 2),
        "tokens_used": tokens,
        "success":     success,
        "project_id":  _active_project.get(),
    }
    call_log.append(entry)
    logger.info(
        f"LLM call | agent={_active_agent.get()} tier={model_tier} model={model} "
        f"latency={latency_ms:.0f}ms tokens={tokens} success={success}"
    )
    # Persist to Neo4j in background thread (non-blocking)
    def _persist():
        try:
            from graph.neo4j_client import persist_llm_call
            persist_llm_call(entry)
        except Exception:
            pass
    threading.Thread(target=_persist, daemon=True).start()


def get_call_log() -> list[dict]:
    """Return the in-memory LLM call log."""
    return call_log


# ─────────────────────────────────────────
# Client Factory
# ─────────────────────────────────────────
gemini_key_index = 0
groq_key_index = 0

def get_client(agent_type: str, key_offset: int = 0) -> tuple[OpenAI, str]:
    """
    Returns (client, model_name) with round-robin key selection for rate limit failover.
    agent_type: "reasoning" | "fast"
    """
    provider_env = "REASONING_LLM_PROVIDER" if agent_type == "reasoning" else "FAST_LLM_PROVIDER"
    provider = os.getenv(provider_env, "gemini").lower()
    
    if provider == "gemini":
        keys_str = os.getenv("GEMINI_API_KEY", "")
        keys = [k.strip(' "\'') for k in keys_str.split(",") if k.strip(' "\'')]
        if not keys:
            keys = [""]
        global gemini_key_index
        active_key = keys[(gemini_key_index + key_offset) % len(keys)]
        
        return (
            OpenAI(
                api_key=active_key,
                base_url=os.getenv("GEMINI_BASE_URL"),
                max_retries=0,
            ),
            os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        )
    else:
        keys_str = os.getenv("GROQ_API_KEY", "")
        keys = [k.strip(' "\'') for k in keys_str.split(",") if k.strip(' "\'')]
        if not keys:
            keys = [""]
        global groq_key_index
        active_key = keys[(groq_key_index + key_offset) % len(keys)]
        
        return (
            OpenAI(
                api_key=active_key,
                base_url=os.getenv("GROQ_BASE_URL"),
                max_retries=0,
            ),
            os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )


def _get_fallback_client() -> tuple[OpenAI, str]:
    """OpenRouter fallback for rate-limited calls."""
    return (
        OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL"),
            max_retries=0,
        ),
        os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.2-3b-instruct:free"),
    )


# ─────────────────────────────────────────
# Unified LLM Call
# ─────────────────────────────────────────
def llm_call(
    agent_type: str,
    messages: list[dict],
    json_mode: bool = True,
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> str:
    """
    Unified LLM call with automatic fallback to OpenRouter if rate limited.
    Retries up to 3 times with exponential backoff.
    """
    kwargs: dict = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    start_time = time.time()
    key_offset = 0

    # Determine total available keys for the primary provider (no fixed limit)
    provider_env = "REASONING_LLM_PROVIDER" if agent_type == "reasoning" else "FAST_LLM_PROVIDER"
    provider = os.getenv(provider_env, "gemini").lower()
    keys_str = os.getenv(f"{provider.upper()}_API_KEY", "")
    primary_keys = [k.strip(' "\'') for k in keys_str.split(",") if k.strip(' "\'')]
    key_count = max(1, len(primary_keys))

    for attempt in range(key_count):
        client, model = get_client(agent_type, key_offset)
        kwargs["model"] = model

        try:
            response = client.chat.completions.create(**kwargs)
            latency_ms = (time.time() - start_time) * 1000
            tokens = getattr(response.usage, "total_tokens", None)
            _log_call(agent_type, model, latency_ms, tokens, success=True)

            global gemini_key_index, groq_key_index
            if provider == "gemini" and key_offset > 0:
                gemini_key_index += key_offset
            elif provider == "groq" and key_offset > 0:
                groq_key_index += key_offset

            return response.choices[0].message.content

        except Exception as e:
            error_details = getattr(e, "body", None)
            if error_details:
                logger.error(f"LLM API Error Body: {error_details}")

            error_str = str(e).lower()
            is_retryable = (
                "rate" in error_str or "429" in error_str or
                "quota" in error_str or "resource exhausted" in error_str or
                "403" in error_str or "permission_denied" in error_str or
                "503" in error_str or "500" in error_str or "overloaded" in error_str
            )

            if is_retryable:
                logger.warning(
                    f"Retryable error hit for {model} (attempt {attempt + 1}/{key_count}). "
                    f"Rotating to next API key..."
                )
                key_offset += 1
                time.sleep(1) # Small pause before trying next key

                if attempt < key_count - 1:
                    continue

                # After trying all keys, fall back to OpenRouter
                logger.warning("All provided keys exhausted. Falling back to OpenRouter...")
                fallback_client, fallback_model = _get_fallback_client()
                kwargs["model"] = fallback_model
                # OpenRouter usually supports json_object
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                fb_start = time.time()
                try:
                    fb_response = fallback_client.chat.completions.create(**kwargs)
                    latency_ms = (time.time() - fb_start) * 1000
                    tokens = getattr(fb_response.usage, "total_tokens", None)
                    _log_call(agent_type, fallback_model, latency_ms, tokens, success=True)
                    return fb_response.choices[0].message.content
                except Exception as fb_e:
                    latency_ms = (time.time() - fb_start) * 1000
                    _log_call(agent_type, fallback_model, latency_ms, None, success=False)
                    raise RuntimeError(f"All LLM providers failed. Last error: {fb_e}") from fb_e
            else:
                latency_ms = (time.time() - start_time) * 1000
                _log_call(agent_type, model, latency_ms, None, success=False)
                logger.error(f"LLM call failed (non-rate-limit): {e}")
                raise

    raise RuntimeError("llm_call exhausted all attempts without returning.")


def parse_json_response(raw: str) -> dict:
    """
    Safely parse a JSON string from an LLM response.
    Robustly extracts the first '{' and last '}' to handle conversational text.
    """
    if not raw or not isinstance(raw, str):
        return {}

    content = raw.strip()

    # Strip markdown code fences
    if "```json" in content:
        content = content.split("```json")[-1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[-1].split("```")[0].strip()

    # Find the largest JSON object
    start = content.find('{')
    end = content.rfind('}')

    if start == -1:
        logger.error(f"No JSON object start found in response: {raw[:500]}")
        raise ValueError("Failed to find JSON object start in LLM response.")

    # If no closing brace is found, it's likely truncated. Try to fix it.
    if end == -1 or end < start:
        logger.warning("Detected truncated JSON (missing closing brace). Attempting to fix.")
        
        # Check if we are inside a string. Count unescaped double quotes.
        # This is a heuristic: if we have an odd number of quotes, we are inside a string.
        json_fragment = content[start:]
        quote_count = 0
        escaped = False
        for char in json_fragment:
             if char == '\\' and not escaped:
                 escaped = True
             elif char == '"' and not escaped:
                 quote_count += 1
                 escaped = False
             else:
                 escaped = False
        
        if quote_count % 2 != 0:
             # We are inside a string value (likely the 'code' field).
             # Close the string and then the object.
             json_str = json_fragment + '"\n}'
        elif "[" in json_fragment and "]" not in json_fragment[json_fragment.rfind("["):]:
             # We are inside a list (likely 'tasks' or 'features').
             # Close the list and then the object.
             json_str = json_fragment + ']\n}'
        else:
             json_str = json_fragment + "\n}"
    else:
        json_str = content[start:end+1]

    try:
        return json.loads(json_str, strict=False)
    except json.JSONDecodeError as e:
        # If the LLM truncated the response, our rfind('}') might have grabbed a '}'
        # from inside the code string instead of the actual JSON closing brace.
        # We try repairing both json_str and the raw content from start.
        raw_frag = content[start:]
        fixes = [
            json_str.strip().rstrip(',').rstrip() + "}",
            json_str.strip().rstrip(',').rstrip() + "]}",
            json_str.strip().rstrip(',').rstrip() + '"\n}',
            raw_frag.strip().rstrip(',').rstrip() + "}",
            raw_frag.strip().rstrip(',').rstrip() + "]}",
            raw_frag.strip().rstrip(',').rstrip() + '"\n}',
        ]
        
        for fix in fixes:
            try:
                return json.loads(fix, strict=False)
            except:
                pass
        
        logger.error(f"JSON parse failed after repair attempt: {e}\nRaw snippet: {json_str[:500]}")
        raise ValueError(f"Failed to parse LLM JSON response: {e}") from e
