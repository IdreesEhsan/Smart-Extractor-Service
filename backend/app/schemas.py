"""
Pydantic models = the data contract for the whole app. /chat and /extract
requests/responses are all defined here. LeadSchema is what raw LLM output
gets validated against before we ever trust it.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

# ---------- /chat models ----------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    role: str = "general_assistant"   # picks which persona from system_prompts.yaml
    temperature: float = 0.7

# ---------- /extract models ----------
# Domain: sales lead emails. Swap this whole class (and the prompt files) to retarget the project at CVs or invoices instead.

class LeadSchema(BaseModel):
    full_name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    # Literal[...] is doing real work here: if the model returns anything other than these exact strings, Pydantic raises ValidationError — which is exactly what feeds the retry loop in extract_service.py.
    interest_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    urgency: Literal["low", "medium", "high", "unknown"] = "unknown"

    budget_mentioned: Optional[str] = None
    product_interest: Optional[str] = None
    next_step: Optional[str] = None

    @field_validator("email")
    @classmethod
    def basic_email_check(cls, v):
        if v and "@" not in v:
            raise ValueError("Email must contain '@'")
        return v


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length = 1)


class ExtractResponse(BaseModel):
    data: LeadSchema
    retries_used: int      # how many times validation failed before success
    prompt_version: str    # which prompt file was active (v1/v2/v3)
    usage: dict            # token counts from the LLM API
    cost_usd: float