"""
Calls /extract on each labeled test item and scores field-level accuracy.
Run this once per prompt version (change prompt_config.yaml, restart the
server, rerun this) to get the numbers for your report.
"""
import json
import time
import httpx

API_URL = "http://localhost:8000/extract"
TEST_SET_PATH = "leads_10.json"
RESULTS_PATH = "results.json"

STRING_FIELDS = [
    "full_name", "company", "email", "phone",
    "budget_mentioned", "product_interest", "next_step",
]
ENUM_FIELDS = ["interest_level", "urgency"]


def fuzzy_match(expected, actual) -> bool:
    """Lenient match for free-text fields — wording can vary slightly."""
    if expected is None:
        return actual is None
    if actual is None:
        return False
    e, a = str(expected).lower(), str(actual).lower()
    return e in a or a in e


def main():
    with open(TEST_SET_PATH) as f:
        items = json.load(f)

    field_correct = {f: 0 for f in STRING_FIELDS + ENUM_FIELDS}
    total_cost = 0.0
    total_retries = 0
    results = []  # per-item breakdown, saved to results.json for the report

    with httpx.Client(timeout=60.0) as client:
        for item in items:
            start = time.perf_counter()
            resp = client.post(API_URL, json={"text": item["text"]})
            latency = (time.perf_counter() - start) * 1000

            if resp.status_code != 200:
                print(f"id={item['id']} FAILED: {resp.text[:150]}")
                results.append({"id": item["id"], "error": resp.text})
                continue

            body = resp.json()
            actual = body["data"]
            total_cost += body["cost_usd"]
            total_retries += body["retries_used"]

            row = {"id": item["id"], "latency_ms": round(latency, 1), "fields": {}}
            for f in STRING_FIELDS:
                ok = fuzzy_match(item["expected"][f], actual.get(f))
                field_correct[f] += int(ok)
                row["fields"][f] = ok
            for f in ENUM_FIELDS:
                # Enum fields require an EXACT match — no leniency
                ok = item["expected"][f] == actual.get(f)
                field_correct[f] += int(ok)
                row["fields"][f] = ok

            results.append(row)
            print(f"id={item['id']:>2}  retries={body['retries_used']}"
                  f"cost=${body['cost_usd']:.5f}  latency={latency:.0f}ms")
            time.sleep(3)

    n = len(items)
    print("\n--- Field accuracy ---")
    scores = []
    for f, correct in field_correct.items():
        pct = 100 * correct / n
        scores.append(pct)
        print(f"  {f:<20} {correct}/{n}  ({pct:.0f}%)")

    overall = sum(scores) / len(scores)
    print(f"\nOverall: {overall:.1f}%")
    print(f"Total cost for {n} extractions: ${total_cost:.5f}")
    print(f"Total retries triggered: {total_retries}")

    with open(RESULTS_PATH, "w") as f:
        json.dump(
            {
                "field_accuracy": {f: field_correct[f] / n for f in field_correct},
                "overall_accuracy_pct": overall,
                "total_cost_usd": total_cost,
                "total_retries": total_retries,
                "per_item": results,
            },
            f,
            indent=2,
        )
    print(f"\nWrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()