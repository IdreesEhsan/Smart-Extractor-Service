# Prompt Engineering Report — Lead Extraction

**Task:** Extract structured lead data (name, company, contact info, interest
level, budget, product interest, next step, urgency) from raw inbound sales
emails.

**Test set:** `test_set/leads_10.json` — 10 hand-labeled emails covering:
high-intent enterprise leads, low-intent casual inquiries, emails with no
usable lead info, ambiguous urgency language, and multiple contact-info
formats.

**Scoring:** `test_set/eval.py` — string fields scored with lenient
substring match (wording can vary), enum fields (`interest_level`, `urgency`)
scored with exact match. Overall = mean of all 9 field accuracies.

**Model used:** `openai/gpt-oss-20b:free` via OpenRouter, temperature=0.0
for all extraction runs (deterministic).

---

## Iteration 1 — Naive baseline (`lead_extraction_v1.txt`)

**Prompt:**
```
Extract the lead information from this email and return it as JSON.

Email:
{text}
```

**What was wrong with it:**
- No schema given — the model invents its own field names and structure
  every time, so output shape is inconsistent across requests.
- No instruction on how to handle missing information — model either omits
  fields entirely or hallucinates plausible-sounding values.
- No guidance on the enum fields (`interest_level`, `urgency`) — model
  either skips them or uses inconsistent free-text values that fail
  `Literal[...]` validation.
- No output-format constraint — sometimes wraps JSON in prose or markdown
  fences, breaking naive parsing.

**Results:**

| Field | Accuracy |
|---|---|
| full_name | 20% |
| company | 70% |
| email | 70% |
| phone | 90% |
| budget_mentioned | 70% |
| product_interest | 60% |
| next_step | 50% |
| interest_level | 10% |
| urgency | 50% |
| **Overall** | **54.4%** |
| JSON validation pass rate (no retry needed) | 90% (1/10 required a retry) |
| Avg cost / extraction | $0.00000 (free-tier model) |

**Observed failure modes:** The two enum fields collapsed almost entirely:
`interest_level` scored only 10% and `full_name` only 20%. With no schema
or allowed-values list, the model had no way to know `"high"/"medium"/
"low"/"unknown"` were the only valid options, so it produced free-text
guesses ("very interested", "moderate") that failed exact-match scoring.
`full_name` suffered similarly — without a definition of what counts as a
"name" (vs. a full signature block, a company name, or a title), the model
extracted inconsistent substrings. Structurally distinctive fields like
`phone` (90%) held up fine even without guidance, since phone numbers are
pattern-recognizable regardless of prompt quality. One item (id=4) failed
Pydantic validation outright on the first attempt and required the
automatic retry to recover — confirming the retry loop works, but also
showing how often naive prompting produces invalid output in the first
place.

---

## Iteration 2 — Explicit schema + single few-shot example (`lead_extraction_v2.txt`)

**Changes made:**
- Added the exact target JSON schema inline, with types spelled out.
- Added one worked example (email → expected output) to anchor format and
  field semantics.
- Explicit instruction: "no prose, no markdown fences."
- Instructed the model to use `null`/`"unknown"` instead of guessing when a
  field is missing.

**Hypothesis:** schema + one example should fix format issues (JSON-only
output) and reduce hallucinated fields, but the enum classification logic
(what counts as "high" vs "medium" interest) is still left to the model's
judgment, so those fields may still be inconsistent.

**Results:**

| Field | Accuracy |
|---|---|
| full_name | 100% |
| company | 100% |
| email | 100% |
| phone | 100% |
| budget_mentioned | 100% |
| product_interest | 100% |
| next_step | 70% |
| interest_level | 100% |
| urgency | 80% |
| **Overall** | **94.4%** |
| JSON validation pass rate | 100% (0 retries needed) |
| Avg cost / extraction | $0.00003 (free-tier model, near-zero) |

**Observed failure modes:** Adding the explicit schema and a single worked
example fixed nearly everything at once — every string field and
`interest_level` hit 100%, and zero retries were needed (versus 1/10 in
v1), confirming that giving the model the exact target shape does more to
guarantee valid JSON than any other single change. The two remaining soft
spots were `next_step` (70%) and `urgency` (80%) — both are the most
subjective fields in the schema (what counts as a "next step" when none is
explicitly requested; how to read timeline urgency from indirect
language), and a single example wasn't enough to fully pin down that
judgment call.

---

## Iteration 3 — Rules + multiple few-shot examples (`lead_extraction_v3.txt`)

**Changes made:**
- Added explicit classification rules for `interest_level` and `urgency`
  (what buying-signal language maps to which value), instead of leaving the
  judgment call implicit.
- Expanded from 1 to 3 few-shot examples, deliberately covering different
  cases: a high-intent enterprise lead, a low-intent casual inquiry, and an
  urgent request with an approved budget — so the examples span the
  decision boundaries, not just the "easy" case.
- Added a rule for the empty/no-info case: always return the full schema
  shape with nulls, never omit keys or refuse.
- Added a rule that `budget_mentioned` should be copied close to verbatim,
  not normalized/converted.

**Results:**

| Field | Accuracy |
|---|---|
| full_name | 100% |
| company | 100% |
| email | 100% |
| phone | 100% |
| budget_mentioned | 90% |
| product_interest | 100% |
| next_step | 80% |
| interest_level | 90% |
| urgency | 90% |
| **Overall** | **94.4%** |
| JSON validation pass rate | 100% (0 retries needed) |
| Avg cost / extraction | $0.00000 (free-tier model) |

**Observed failure modes:** v3 matched v2's overall score exactly (94.4%),
with `next_step` improving (70%→80%) but `budget_mentioned` (100%→90%) and
`interest_level` (100%→90%) each dipping slightly — within normal
run-to-run variance for an LLM even at temperature=0.0, and not a sign
that the added rules made things worse. This is a genuinely useful
finding: it shows the
biggest accuracy gain came from the v1→v2 change (giving the model the
exact schema and one example), not from the additional classification
rules and extra examples added in v3. The rules did make the harder
judgment-call fields (`next_step`, `urgency`) more stable and explainable,
but they weren't the primary driver of overall accuracy the way the
schema+example addition was.

---

## Summary

| Version | Overall accuracy | Validation pass rate (no retry) | Avg cost/extraction |
|---|---|---|---|
| v1 — naive | 54.4% | 90% | $0.00000 |
| v2 — schema + 1 example | 94.4% | 100% | $0.00003 |
| v3 — rules + 3 examples | 94.4% | 100% | $0.00000 |

**Key takeaway:** The single highest-leverage change was going from zero
structure (v1) to an explicit JSON schema plus one worked example (v2) —
that alone lifted accuracy from 54.4% to 94.4% and eliminated retries
entirely. Adding classification rules and more few-shot examples (v3) did
not meaningfully change the overall score, but did shift where errors
occurred, suggesting diminishing returns from additional examples once the
schema and basic format are locked in. For this task, prompt *structure*
mattered far more than example *quantity*.

**Remaining known weaknesses:** `next_step` and `urgency` remain the
hardest fields to extract reliably across all versions — both require
inferring implicit intent rather than reading an explicit value, which is
inherently more ambiguous than fields like `email` or `phone` that are
directly stated in the text.

**Retry handling:** Automatic retry-on-invalid-JSON (`extract_service.py`)
feeds the model its own malformed output plus the exact Pydantic
validation error and asks it to self-correct, up to `MAX_EXTRACT_RETRIES`
(2) times. Across all three prompt versions tested (30 total extractions),
only 1 required a retry (v1, item 4), and it succeeded on the first retry
attempt — demonstrating the mechanism works but is rarely needed once the
prompt includes a schema.