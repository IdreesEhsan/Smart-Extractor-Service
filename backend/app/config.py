"""
Central settings. Nothing environment-specific (keys, model names, retry
counts) should be hardcoded anywhere else in the app — it all comes from here,
which in turn reads from .env.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Tells pydantic-settings to auto-load values from a .env file
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Default models used unless a request overrides them
    chat_model: str = "openai/gpt-4o-mini"
    extract_model: str = "openai/gpt-4o-mini"

    max_extract_retries: int = 2   # how many times /extract retries on bad JSON
    log_file: str = "logs/requests.jsonl"

settings = Settings()  # a single shared instance, imported everywhere else

# Ordered fallback list of free models to try if the primary one is
# rate-limited (429). Tried in order — first one that responds wins.
FREE_MODEL_FALLBACKS = [
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "cohere/north-mini-code:free",
]

# USD per 1,000,000 tokens. Check openrouter.ai/models for current numbers —
# these change over time and this is just an approximation for logging.
MODEL_PRICING_PER_1M = {
    "openai/gpt-oss-20b:free": {"input": 0.0, "output": 0.0},
    "nvidia/nemotron-3-nano-30b-a3b:free": {"input": 0.0, "output": 0.0},
    # keep your paid entries too, in case you switch later
}
DEFAULT_PRICING = {"input": 0.50, "output": 1.50}  # fallback for unlisted models


def get_pricing(model: str) -> dict:
    return MODEL_PRICING_PER_1M.get(model, DEFAULT_PRICING)