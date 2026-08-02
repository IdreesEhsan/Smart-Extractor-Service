"""
Calls /extract on each labeled test item and scores field-level accuracy.
Run this once per prompt version (change prompt_config.yaml, restart the
server, rerun this) to get the numbers for your report.
"""
import json, time, httpx
API_URL = "http://localhost:8000/extract"
STRING_FIELDS = ["full_name", "company", "email", "phone",
                  "budget_mentioned", "product_interest", "next_step"]
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
    with open("leads_10.json") as f:
        items = json.load(f)

    field_correct = {f: 0 for f in STRING_FIELDS + ENUM_FIELDS}
    total_cost = 0.0

    with httpx.Client(timeout=60.0) as client:
        for item in items:
            resp = client.post(API_URL, json={"text": item["text"]})
            if resp.status_code != 200:
                print(f"id={item['id']} FAILED: {resp.text[:150]}")
                continue

            body = resp.json()
            actual = body['data']
            total_cost += body["cost_usd"]

            for f in STRING_FIELDS:
                field_correct[f] += int(fuzzy_match(item["expected"][f], actual.get(f)))
            for f in ENUM_FIELDS:
                # Enum fields require an EXACT match — no leniency
                field_correct[f] += int(item["expected"][f] == actual.get(f))

    n = len(items)
    print("\n--- Field accuracy ---")
    scores = []
    for f, correct in field_correct.items():
        pct = 100 * correct / n
        scores.append(pct)
        print(f"  {f:<20} {correct}/{n}  ({pct:.0f}%)")
    print(f"\nOverall: {sum(scores)/len(scores):.1f}%")
    print(f"Total cost for {n} extractions: ${total_cost:.5f}")


if __name__ == "__main__":
    main()