"""
Wraps the OpenRouter chat-completions endpoint. Using OpenRouter (instead of
calling OpenAI/Anthropic directly) means one client works for any model —
swap CHAT_MODEL/EXTRACT_MODEL in .env and nothing here changes.
"""

import json
import httpx
from typing import AsyncGenerator
from app.config import settings, get_pricing

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

def calc_cost(model: str, usage: dict) -> float:
    """Converts token usage into an estimated USD cost using our pricing table."""
    pricing = get_pricing(model)
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (prompt_tokens / 1_000_000) * pricing["input"] \
         + (completion_tokens / 1_000_000) * pricing["output"]
    return round(cost, 6)


async def chat_completion(messages: list[dict], model: str, temperature: float = 0.7) -> dict:
    """
    Non-streaming call — waits for the full response. Used by /extract,
    where we need the whole JSON blob before we can validate it.
    """
    payload = {"model": model, "messages": messages, "temperature": temperature}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()  # raises on 4xx/5xx so errors don't fail silently
        data = resp.json()

    return {
        "content": data["choices"][0]["message"]["content"],
        "usage": data.get("usage", {}),
        "model": model,
    }

async def chat_completion_stream(
    messages: list[dict], model: str, temperature: float = 0.7
) -> AsyncGenerator[str, None]:
    """
    Streaming call — yields text chunks as they arrive instead of waiting
    for the full response. Used by /chat for token-by-token UI updates.
    """
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{settings.openrouter_base_url}/chat/completions",
            headers=_headers(), json=payload,
        ) as resp:
            resp.raise_for_status()
            # OpenRouter streams Server-Sent Events: lines like "data: {...}"
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue  # skip malformed keep-alive lines
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content")
                if text:
                    yield text
