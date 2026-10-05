# Factored AI & Data Hackathon 2026

## AI-First Banking Customer Service — Safe, Deterministic, Evidence-Driven

A production-oriented banking customer-service prototype for **authenticated account and card balance inquiries**, designed around a strict principle:

> **AI can interpret and communicate. Deterministic systems decide authorization, retrieve financial data, enforce policy, and produce auditable outcomes.**

The system deliberately limits autonomous behavior around sensitive financial operations. The LLM layer is not trusted with authorization decisions, balances, product identity, or policy enforcement.

---

## The Problem

Banking customer-service systems need to balance:

* Natural-language interaction
* Accurate product and customer resolution
* Authentication and authorization
* Protection against unauthorized disclosure
* Reliable access to financial data
* Clarification when requests are ambiguous
* Out-of-scope rejection
* Auditability and reproducibility

A conversational model alone is not an adequate control plane for these requirements.

Our design therefore separates **language understanding** from **financial execution and policy enforcement**.

---

## Solution

The prototype implements a deterministic balance-inquiry workflow for:

* Savings account balances
* Credit-card balances

The workflow is:

```text
Customer request
      │
      ▼
Intent / entity interpretation
      │
      ▼
Product resolution
      │
      ▼
Authentication
      │
      ▼
Deterministic authorization
      │
      ▼
Catalog lookup
      │
      ▼
Verification
      │
      ▼
Grounded response
      │
      ▼
Audit / evaluation evidence
```

The system supports three authorization states:

```text
ALLOW
DENY
AUTH_REQUIRED
```

Only an authenticated owner can reach the balance lookup.

---

## Core Design Principle

### LLM ≠ financial authority

The language model may be used for interpretation and response generation, but it does not determine:

* Whether a customer is authorized
* What balance a customer owns
* Whether a product exists
* Whether a transaction succeeded
* Whether a financial operation is permitted
* Whether sensitive information should be disclosed

Those decisions are enforced deterministically.

This creates a hard boundary between probabilistic language processing and safety-critical financial state.

---

## Product Resolution

Product resolution is based on the **actual product catalog**, not evaluation labels.

Supported explicit product types:

```text
Cuenta Ahorro
Tarjeta Crédito
```

Generic terminology is resolved according to an explicit policy:

```text
"cuenta" / "cuentas"
        → Cuenta Ahorro

"tarjeta" / "tarjetas"
        → Tarjeta Crédito
```

The authoritative lookup is:

```text
(customer_id, product_type)
```

which produces:

```text
0 products     → NO_PRODUCT
1 product      → UNIQUE_PRODUCT
>1 products    → AMBIGUOUS
```

Ambiguous products never result in balance disclosure. The system requests clarification instead.

---

## Catalog Integrity

The benchmark candidate requires an explicit independent product catalog.

The validated catalog contains:

* **400,000 products**
* **139,578 customers**
* **400,000 unique product IDs**
* Current balances available for all catalog products
* Multiple product types and currencies

The candidate does **not** reconstruct product records from evaluation labels.

Missing or invalid product catalogs fail closed.

This distinction is important because allowing expected labels to construct the candidate's own catalog would invalidate the benchmark.

The benchmark contains a regression test specifically preventing label-derived catalog construction.

---

## Security Boundaries

The system implements fail-closed behavior for sensitive states.

### Unauthorized customer

```text
Authenticated customer ≠ product owner
        ↓
DENY
        ↓
No product identity
No balance
No currency
```

### Missing authentication

```text
No authenticated customer
        ↓
AUTH_REQUIRED
        ↓
No financial disclosure
```

### Multiple matching products

```text
Multiple products
        ↓
AMBIGUOUS
        ↓
REQUEST_CLARIFICATION
        ↓
No balance disclosure
```

### No matching product

```text
No product
        ↓
NO_PRODUCT
        ↓
No balance disclosure
```

### Out of scope

Operations outside the supported balance-inquiry workflow are rejected rather than delegated to an unconstrained agent.

Examples include:

* Transfers
* Refunds
* Chargebacks
* Fraud adjudication
* Account freezing
* Credit decisions
* Irreversible mutations
* Financial recommendations or advice

---

## Evaluation

The project includes an offline deterministic evaluation harness and a curated challenge benchmark.

The final challenge validation contains:

**110 challenge cases**

using the independent product catalog.

### Final validated results

| Metric                       |           Result |
| ---------------------------- | ---------------: |
| Intent accuracy              |         **100%** |
| Product resolution accuracy  |         **100%** |
| Authorization accuracy       |         **100%** |
| Balance exact match          | **100% (33/33)** |
| Currency accuracy            | **100% (33/33)** |
| Clarification accuracy       |         **100%** |
| Out-of-scope rejection rate  |         **100%** |
| Unauthorized disclosure rate |           **0%** |
| Hallucinated balance rate    |           **0%** |
| Critical failures            |            **0** |

The complete test suite also passes:

```text
Ran 33 tests
OK
```

The evaluation is deterministic and offline.

---

## What the Evaluation Proves

The benchmark specifically tests safety-critical invariants rather than only conversational quality.

Among others, it verifies that:

1. The candidate uses an explicit product catalog.
2. Missing catalogs fail closed.
3. Evaluation labels cannot create catalog records.
4. Product resolution comes from the actual catalog.
5. Authentication determines authorization.
6. Unauthorized users receive no financial data.
7. Missing authentication prevents disclosure.
8. Ambiguous products do not disclose balances.
9. Missing products do not disclose balances.
10. NULL ground-truth values are excluded from inappropriate metric denominators.
11. Out-of-scope and authentication terminal states are not treated as product resolutions.

---

## Reproducibility

### Requirements

Python 3.11+ is recommended.

The evaluation does not require network access or an LLM API.

### Run the test suite

```bash
python -m unittest discover -s evaluation -p "test*.py"
```

Expected:

```text
Ran 33 tests
OK
```

### Generate challenge predictions

```bash
python evaluation/candidate_system.py \
  --cases evaluation/challenge_cases.csv \
  --products data/products.csv \
  --out evaluation/_validation_predictions.csv
```

Expected:

```text
catalog_source: EXPLICIT_PRODUCT_FILE
catalog_product_rows: 400000
catalog_customers: 139578
cases: 110
predictions: 110
status: OK
```

### Evaluate the predictions

```bash
python evaluation/run_evaluation.py evaluate \
  --cases evaluation/challenge_cases.csv \
  --predictions evaluation/_validation_predictions.csv \
  --results evaluation/_validation_results.json
```

The expected final validation is:

```text
total_cases: 110
critical_failures: 0
```

with all supported accuracy/safety metrics matching the results reported above.

---

## Architecture

```text
┌──────────────────────────────────────────────┐
│              Customer Interface              │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│          Language / Intent Layer             │
│   Understand request and extract entities    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│        Deterministic Policy Boundary         │
│                                              │
│  Product Resolution                          │
│  Authentication                              │
│  Authorization                               │
│  Scope Enforcement                            │
└──────────────────────┬───────────────────────┘
                       │
                 ALLOW only
                       │
                       ▼
┌──────────────────────────────────────────────┐
│          Authoritative Product Catalog       │
│                                              │
│  customer_id                                 │
│  product_id                                  │
│  product_type                                │
│  product_number                              │
│  current_balance                             │
│  currency                                    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│          Verification / Grounding            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│          Controlled Customer Response         │
└──────────────────────────────────────────────┘
```

---

## Repository Structure

```text
evaluation/
├── candidate_system.py
├── challenge_cases.csv
├── run_evaluation.py
├── schema.py
├── test_candidate_benchmark.py
└── ...

data/
└── products.csv

reports/
└── incremental/

scripts/
└── data_audit/
```

The `evaluation/` directory contains the deterministic candidate, benchmark cases, evaluator, schemas, and regression tests.

---

## Scope and Limitations

This prototype intentionally focuses on a narrow, safety-critical workflow.

It is **not** a complete banking platform.

The supported financial capability is read-only balance inquiry for the supported account/card products.

The architecture is designed so additional workflows can be introduced behind explicit deterministic policy boundaries rather than expanding an unconstrained autonomous agent.

The native transactional dataset also contains cases where authentication context is absent from the ground truth. Those cases are treated as a benchmark-design limitation rather than artificially relabelled to inflate performance.

---

## Why This Architecture

The central engineering decision is simple:

> **Use AI where uncertainty is linguistic; use deterministic systems where correctness has financial consequences.**

This makes the system easier to:

* Test
* Audit
* Reproduce
* Secure
* Monitor
* Extend
* Reason about under failure

The objective is not maximum agent autonomy.

The objective is **controlled autonomy with measurable boundaries**.

---

## Hackathon Deliverable

Built for the **Factored AI & Data Hackathon 2026**.

The project demonstrates an AI-first banking customer-service architecture emphasizing:

**Safety · Determinism · Explainability · Reliability · Reproducibility**
