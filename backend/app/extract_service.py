"""
Orchestrates one full extraction: load the active prompt -> call the LLM ->
parse JSON -> validate against LeadSchema -> on failure, feed the exact
error back to the model and retry. This is the "reliable structured JSON"
part of the assignment.
"""
import json
import re
from pathlib import Path
import yaml
from pydantic import ValidationError

from app.config import settings
from app.llm_client import chat_completion_with_fallback, calc_cost
from app.schemas import LeadSchema

PROMPTS_DIR = Path(__file__).parent / "prompts" / "extraction"

def _load_prompt_config() -> dict:
    with open(PROMPTS_DIR / "prompt_config.yaml") as f:
        return yaml.safe_load(f)

def _load_prompt_template(filename: str) -> str:
    with open(PROMPTS_DIR / filename) as f:
        return f.read()

def _strip_code_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` even when told not to."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text.strip()


async def extract_lead(text: str) -> dict:
    cfg = _load_prompt_config()
    template = _load_prompt_template(cfg["file"])
    # Note: this is only the *configured* default model. Since the actual
    # call below goes through chat_completion_with_fallback(), a rate-limited
    # request may really be served by a different model in FREE_MODEL_FALLBACKS.
    # calc_cost() further down still prices against this variable, not
    # whichever model actually responded.
    model = settings.extract_model

    messages = [{"role": "user", "content": template.format(text=text)}]

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    retries_used = 0
    last_error = last_output = None

    # +1 because attempt 0 is the first try, not a retry
    for attempt in range(settings.max_extract_retries + 1):
        result = await chat_completion_with_fallback(messages, temperature=0.0)
        for k in total_usage:
            total_usage[k] += result["usage"].get(k, 0)

        raw = _strip_code_fences(result['content'])
        last_output = raw

        try:
            parsed = json.loads(raw)
            validated = LeadSchema.model_validate(parsed)
            # Success — return immediately
            return {
                "data": validated,
                "retries_used": retries_used,
                "prompt_version": cfg["active_version"],
                "usage": total_usage,
                "cost_usd": calc_cost(model, total_usage),
            }
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = str(e)
            retries_used += 1
            if attempt < settings.max_extract_retries:
                # Give the model its own bad output + the exact error, ask it
                # to fix itself. More reliable than a generic "try again".
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": cfg["retry_feedback_template"].format(
                        error=last_error, previous_output=raw
                    ),
                })

    # Ran out of retries
    raise ValueError(
        f"Extraction failed after {retries_used} retries. "
        f"Last error: {last_error}. Last output: {last_output}"
    )