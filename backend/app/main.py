import yaml
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.schemas import ChatRequest, ExtractRequest, ExtractResponse
from app.llm_client import chat_completion_stream, calc_cost
from app.extract_service import extract_lead
from app.logging_utils import log_request, Timer

app = FastAPI(title="Smart Extractor and Chat Service")

# Loosen for local dev; restrict to your real frontend origin in production
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CHAT_PROMPTS_PATH = Path(__file__).parent / "prompts" / "chat" / "system_prompts.yaml"


def _load_system_prompt(role: str) -> str:
    with open(CHAT_PROMPTS_PATH) as f:
        prompts = yaml.safe_load(f)
    if role not in prompts:
        raise HTTPException(400, f"Unknown role '{role}'. Options: {list(prompts.keys())}")
    return prompts[role]

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/roles")
async def list_roles():
    with open(CHAT_PROMPTS_PATH) as f:
        return {"roles": list(yaml.safe_load(f).keys())}


@app.post("/chat")
async def chat(req: ChatRequest):
    system_prompt = _load_system_prompt(req.role)
    messages = [{"role": "system", "content": system_prompt}] + \
               [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_stream():
        full_text = ""
        with Timer() as t:
             async for chunk in chat_completion_stream(messages, settings.chat_model, req.temperature):
                full_text += chunk
                yield chunk
        # Streaming doesn't always return exact token usage, so we estimate
        # (roughly 4 chars/token) for logging purposes only.
        usage = {
            "prompt_tokens": sum(len(m["content"]) for m in messages) // 4,
            "completion_tokens": len(full_text) // 4,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        log_request("/chat", settings.chat_model, usage,
                     calc_cost(settings.chat_model, usage), t.elapsed_ms,
                     extra={"role": req.role})

    return StreamingResponse(event_stream(), media_type="text/plain")


@app.post("/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest):
    with Timer() as t:
        try:
            result = await extract_lead(req.text)
        except ValueError as e:
            raise HTTPException(422, str(e))

    log_request("/extract", settings.extract_model, result["usage"],
                 result["cost_usd"], t.elapsed_ms,
                 extra={"retries_used": result["retries_used"],
                        "prompt_version": result["prompt_version"]})
    return ExtractResponse(**result)