"""
One JSON line per request, appended to LOG_FILE. Simple JSONL instead of a
DB — trivial to inspect with `cat logs/requests.jsonl | jq` or pandas.
"""
import json, os, time
from datetime import datetime, timezone
from app.config import settings

def log_request(endpoint, model, usage, cost_usd, latency_ms, extra=None):
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "cost_usd": cost_usd,
        "latency_ms": round(latency_ms, 1),
    }
    if extra:
        record.update(extra)
    with open(settings.log_file, "a") as f:
        f.write(json.dumps(record) + "\n")

class Timer:
    """Context manager for measuring request latency."""
    def __enter__(self):
        self._start = time.perf_counter()
        return self
    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000