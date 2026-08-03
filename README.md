# Smart Extractor & Chat Service

A FastAPI service demonstrating production-grade LLM usage:
- **`/chat`** — streaming, role-based chatbot (persona selected per request)
- **`/extract`** — converts raw lead-email text into validated, structured JSON
  (Pydantic-validated, with automatic retry-on-invalid-JSON)
- Prompt templates live outside the code, as plain text/YAML files, so you can
  iterate on prompts without touching Python
- Every request is logged with token counts and cost in USD
- Automatic fallback across free-tier OpenRouter models on rate limits
- A React UI (console-styled) for both endpoints

## Results summary

Measured on the 10-item test set in `test_set/leads_10.json` (see
`PROMPT_ENGINEERING_REPORT.md` for the full breakdown):

| Prompt version | Overall accuracy | Retries needed |
|---|---|---|
| v1 — naive baseline | 54.4% | 1/10 |
| v2 — schema + 1 example | 94.4% | 0/10 |
| v3 — rules + 3 examples | 94.4% | 0/10 |

## Project layout

```
smart-extractor-service/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, routes
│   │   ├── config.py                # settings + pricing table + free-model fallback list
│   │   ├── schemas.py               # Pydantic models (LeadSchema, etc.)
│   │   ├── llm_client.py            # OpenRouter client, streaming + non-streaming + fallback
│   │   ├── extract_service.py       # prompt loading, JSON parse, validate, retry
│   │   ├── logging_utils.py         # per-request JSONL logging
│   │   └── prompts/
│   │       ├── chat/system_prompts.yaml
│   │       └── extraction/
│   │           ├── lead_extraction_v1.txt   # naive baseline
│   │           ├── lead_extraction_v2.txt   # + schema + 1 few-shot example
│   │           ├── lead_extraction_v3.txt   # + rules + 3 few-shot examples
│   │           └── prompt_config.yaml       # which version is "active"
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html                   # single-file React app (no build step)
├── test_set/
│   ├── leads_10.json                # 10 labeled test emails
│   ├── eval.py                      # runs extraction + scores accuracy
│   ├── results_v1.json              # saved accuracy run per prompt version
│   ├── results_v2.json
│   └── results_v3.json
└── PROMPT_ENGINEERING_REPORT.md      # full write-up with real accuracy numbers
```

## 1. Local setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add your OpenRouter API key (get one at https://openrouter.ai/keys —
it gives you one key for OpenAI, Anthropic, and dozens of other models, with
usage-based pricing and no separate accounts).

```bash
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for interactive API docs (FastAPI's built-in
Swagger UI) — good for testing `/chat` and `/extract` directly before wiring
up the frontend.

## 2. Run the frontend

The frontend is a single static HTML file (React loaded from CDN, no build
step needed). Just open it:

```bash
cd frontend
python -m http.server 5500
# visit http://localhost:5500
```

If your backend isn't on localhost:8000, set the API base before the app
loads by adding this above the `<script type="text/babel">` tag in
`index.html`:
```html
<script>window.__API_BASE__ = "https://your-deployed-api.com";</script>
```

## 3. Test the extractor against the 10-item set

```bash
# backend must be running (step 1)
cd test_set
python eval.py
```

This prints per-field accuracy and writes `results.json`. Run it once per
prompt version (change `active_version`/`file` in `prompt_config.yaml`,
restart uvicorn, rerun) to get the numbers for the Prompt Engineering
Report. Copy each run's output (`results_v1.json`, `results_v2.json`,
`results_v3.json`) to compare versions side by side.

## 4. Free-tier models and rate limits

`EXTRACT_MODEL`/`CHAT_MODEL` in `.env` default to free OpenRouter models
(`:free` suffix), which cost $0 but are rate-limited (commonly a handful
of requests per minute/day depending on the model). `/extract` routes
through `chat_completion_with_fallback()` in `llm_client.py`, which tries
each model in `FREE_MODEL_FALLBACKS` (see `config.py`) in order and moves
to the next one automatically on a 429. `/chat` currently uses a single
fixed model with no fallback — if you hit a 429 there during manual
testing, swap `CHAT_MODEL` in `.env` by hand and restart.

If you have budget, adding a small balance to your OpenRouter account
(even $5-10) substantially raises free-tier rate limits — worth doing if
you're running the eval script repeatedly.

## 5. Deploy

Any container-friendly host works (Render, Railway, Fly.io, a VPS). Quickest
path with Render:

1. Push this repo to GitHub.
2. On Render: New → Web Service → connect the repo, root directory `backend`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add `OPENROUTER_API_KEY` (and other `.env` vars) as environment variables
   in Render's dashboard.
6. Deploy the frontend separately as a static site (Render Static Site,
   Netlify, Vercel, or GitHub Pages) — just the `frontend/` folder, with
   `window.__API_BASE__` set to your Render backend URL.

## 6. Cost log

Every request appends a line to `backend/logs/requests.jsonl`:

```json
{"timestamp": "...", "endpoint": "/extract", "model": "openai/gpt-oss-20b:free", "prompt_tokens": 512, "completion_tokens": 96, "total_tokens": 608, "cost_usd": 0.0, "latency_ms": 812.3, "retries_used": 0, "prompt_version": "v3"}
```

Note: `get_pricing()` in `config.py` checks for a `:free` suffix on the
model name before consulting the pricing table, so free-tier models always
log `cost_usd: 0.0` regardless of what they'd cost on a paid tier.

Load it into pandas for a quick cost report:
```python
import pandas as pd
df = pd.read_json("backend/logs/requests.jsonl", lines=True)
print(df.groupby("endpoint")["cost_usd"].sum())
```

## Notes on design decisions

- **OpenRouter** is used as the provider so the same code path works for
  OpenAI, Anthropic, or any other model — swap `CHAT_MODEL`/`EXTRACT_MODEL`
  in `.env` and nothing else changes.
- **Temperature 0.0** is used for extraction (deterministic, repeatable) and
  a configurable temperature (default 0.7) for chat (natural variation).
- **Retry-on-invalid** re-sends the model's own bad output plus the Pydantic
  validation error and asks it to self-correct — this consistently fixes
  malformed JSON without needing a second, different prompt.
- **Streaming cost** is estimated (chars/4) rather than exact, since not all
  providers return token usage on the SSE stream. For exact numbers per
  request, the non-streaming `/extract` path reports real usage from the API.
- **Free-model fallback** (`chat_completion_with_fallback` in
  `llm_client.py`) tries a short list of free OpenRouter models in order and
  moves to the next one on a 429, so a single rate-limited model doesn't
  fail the whole batch during evaluation runs.