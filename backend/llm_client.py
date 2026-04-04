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
from datetime import datetime
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
# Call Log (in-memory for metrics)
# ─────────────────────────────────────────
call_log: list[dict] = []


def _log_call(agent_type: str, model: str, latency_ms: float, tokens: int | None, success: bool):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "agent_type": agent_type,
        "model": model,
        "latency_ms": round(latency_ms, 2),
        "tokens_used": tokens,
        "success": success,
    }
    call_log.append(entry)
    logger.info(
        f"LLM call | agent={agent_type} model={model} "
        f"latency={latency_ms:.0f}ms tokens={tokens} success={success}"
    )


def get_call_log() -> list[dict]:
    """Return the in-memory LLM call log."""
    return call_log


# ─────────────────────────────────────────
# Client Factory
# ─────────────────────────────────────────
def get_client(agent_type: str) -> tuple[OpenAI, str]:
    """
    Returns (client, model_name) based on agent type.
    agent_type: "reasoning" | "fast"
    """
    if agent_type == "reasoning":
        return (
            OpenAI(
                api_key=os.getenv("GEMINI_API_KEY"),
                base_url=os.getenv("GEMINI_BASE_URL"),
            ),
            os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest"),
        )
    else:
        return (
            OpenAI(
                api_key=os.getenv("GROQ_API_KEY"),
                base_url=os.getenv("GROQ_BASE_URL"),
            ),
            os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )


def _get_fallback_client() -> tuple[OpenAI, str]:
    """OpenRouter fallback for rate-limited calls."""
    return (
        OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL"),
        ),
        os.getenv("OPENROUTER_MODEL", "meta-llama/llama-4-scout:free"),
    )


# ─────────────────────────────────────────
# Unified LLM Call
# ─────────────────────────────────────────
def llm_call(
    agent_type: str,
    messages: list[dict],
    json_mode: bool = True,
    temperature: float = 0.7,
    max_tokens: int = 32768,
) -> str:
    """
    Unified LLM call with automatic fallback to OpenRouter if rate limited.
    Retries up to 3 times with exponential backoff.
    """
    client, model = get_client(agent_type)

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    # We remove response_format for Gemini as it causes 400s on their OpenAI proxy
    # For others (Groq, OpenRouter), we keep it if requested
    is_gemini = "google" in str(client.base_url).lower() or "gemini" in model.lower()
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    start_time = time.time()

    for attempt in range(5):
        try:
            response = client.chat.completions.create(**kwargs)
            latency_ms = (time.time() - start_time) * 1000
            tokens = getattr(response.usage, "total_tokens", None)
            _log_call(agent_type, model, latency_ms, tokens, success=True)
            return response.choices[0].message.content

        except Exception as e:
            # Enhanced error body logging
            error_details = getattr(e, "body", None)
            if error_details:
                logger.error(f"LLM API Error Body: {error_details}")

            error_str = str(e).lower()
            is_rate_limit = "rate" in error_str or "429" in error_str or "quota" in error_str

            if is_rate_limit:
                wait_time = 30
                logger.warning(
                    f"Rate limit hit for {model} (attempt {attempt + 1}/5). "
                    f"Waiting {wait_time}s..."
                )

                if attempt < 4:
                    time.sleep(wait_time)
                    continue

                # After 5 attempts, fall back to OpenRouter
                logger.warning("All retries exhausted. Falling back to OpenRouter...")
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

    if start == -1 or end == -1:
        logger.error(f"No JSON object found in response: {raw[:500]}")
        raise ValueError("Failed to find JSON object in LLM response.")

    json_str = content[start:end+1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e}\nRaw snippet: {json_str[:500]}")
        raise ValueError(f"Failed to parse LLM JSON response: {e}") from e
