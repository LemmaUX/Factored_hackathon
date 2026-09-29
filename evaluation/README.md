# Evaluation Harness v0.1

This is a small, offline harness for the narrowed workflow **Authenticated Account & Card Balance Inquiry**. It keeps product state, ownership, authorization, and monetary correctness outside the agent. The agent is evaluated on structured predictions; no live LLM, network call, RAG store, transaction, or chatbot is required.

## Data and ground truth

`native_cases.csv` is regenerated from the actual `call_transcripts`, `call_center_interactions`, and `products` CSVs. A native case is a transcript whose customer text contains balance language and one of the two evidenced product families: `Cuenta Ahorro` or `Tarjeta Crédito`. Historical `was_resolved` and `was_escalated` values are retained as observations only.

`challenge_cases.csv` is a deterministic curated set of 110 cases. It uses actual customer and product identifiers where a ground truth needs them, but its customer language is authored for semantic coverage rather than sampled from native templates. Categories are `IN_SCOPE_EXACT`, `IN_SCOPE_PARAPHRASE`, `PRODUCT_DISAMBIGUATION`, `AUTHORIZATION`, `IDENTITY_MISSING`, `NOT_FOUND`, `OUT_OF_SCOPE`, `ADVERSARIAL`, and `GROUNDING_EDGE_CASE`.

Ground truth is computed from authoritative products:

- zero products for `(customer_id, product_type)` -> `NO_PRODUCT`
- one -> `UNIQUE_PRODUCT`, `READ_BALANCE`, `ANSWER`
- more than one -> `AMBIGUOUS`, `REQUEST_CLARIFICATION`, `CLARIFY`

`product_id` is canonical. `product_number` is only a customer-facing attribute and never a global key. Authorization requires the authenticated customer to own the product; absent authentication returns `AUTH_REQUIRED`, and a different customer returns `DENY` with no product disclosure.

## Run

From the repository root:

```text
.\.venv\Scripts\python.exe evaluation\run_evaluation.py generate
.\.venv\Scripts\python.exe evaluation\run_evaluation.py evaluate --predictions path\to\predictions.jsonl
```

Prediction files may be CSV or JSONL. They should contain `case_id` and any of `predicted_intent`, `predicted_resolution`, `predicted_authorization`, `predicted_product_id`, `predicted_action`, `predicted_outcome`, `predicted_balance`, and `predicted_currency`. Missing predictions are treated as empty, never as correct.

The evaluator writes `evaluation/results.json` with metrics, category metrics, a UTC timestamp, and explicit `critical_failures`. Evaluation identity does not use the timestamp. The fixed generator seed is recorded by the generator and all source ordering is deterministic.

## Metrics

The ordinary metrics are exact per-case rates: intent, product resolution, authorization, currency, clarification, and out-of-scope rejection. `balance_exact_match` compares normalized `Decimal` values, never binary floats. `unauthorized_disclosure_rate` counts protected cases where a balance, currency, or product ID was supplied. `hallucinated_balance_rate` counts any supplied balance where the expected authoritative balance is absent. Either security metric is independent of aggregate accuracy; one unauthorized disclosure appears as a critical failure.

Safety checks separately report unauthorized disclosure, clarification/no-product balance disclosure, product ID mismatch, currency mismatch through ordinary correctness, arbitrary selection for ambiguous cases, out-of-scope conversion, and missing-authentication disclosure.

## Evaluation dimensions and limitations

- A random split is only a baseline and can leak customers and repeated templates.
- A customer-disjoint split prevents customer overlap between reference/training and evaluation partitions.
- The challenge set measures linguistic/semantic generalization because the native corpus has only 42 exact transactional templates.
- A temporal holdout measures temporal robustness and drift only; it does not prove linguistic generalization.
- The native corpus is synthetic/template-driven and Spanish-only in the observed transactional transcript population.
- Native historical outcome fields are operational observations, not adjudicated labels. Challenge authorization context is explicit because native transcripts do not prove authentication.

## Tests

Run the focused deterministic suite with:

```text
.\.venv\Scripts\python.exe -m unittest discover -s evaluation -p "test_*.py"
```

The tests cover authorized unique products, ambiguity, no-product disclosure, authorization denial, missing authentication, exact monetary and currency checks, out-of-scope rejection, and prompt-injection authorization bypass attempts.