# Data Audit Executive Summary

## Audit Status
EXECUTED: 2026-09-27T19:39:26.273153+00:00; files scanned: 7671; logical datasets: 13.

## Evidence
- Total rows: 23,495,188 across 13 logical datasets.
- Date coverage: see `data_inventory.csv` and `temporal_coverage.csv`; no equal-population assumption is made.
- Verified joins: transactions.customer_id -> customers.customer_id (100.0%), transactions.product_id -> products.product_id (100.0%), call_center_interactions.customer_id -> customers.customer_id (100.0%), call_center_interactions.agent_id -> service_agents.agent_id (100.0%), call_transcripts.interaction_id -> call_center_interactions.interaction_id (100.0%), call_transcripts.customer_id -> customers.customer_id (100.0%), complaints.customer_id -> customers.customer_id (100.0%), complaints.assigned_agent_id -> service_agents.agent_id (100.0%), complaints.affected_product_id -> products.product_id (100.0%), satisfaction_surveys.interaction_id -> call_center_interactions.interaction_id (100.0%), satisfaction_surveys.customer_id -> customers.customer_id (100.0%), digital_events.customer_id -> customers.customer_id (100.0%).
- Transaction evidence: 4,425,008 transaction rows; 240,056 interaction rows matched by exploratory reason tokens.
- Complaint evidence: 67,095 complaint rows; 117,021 interaction rows matched by exploratory reason tokens.
- Transcript evidence: 171,321 transcript rows.
- Languages: {"es": 171321}.
- Portuguese status: PORTUGUESE COVERAGE = UNKNOWN.
- Workflow A feasibility: see `WORKFLOW_A_FEASIBILITY.md`; no ranking assigned.
- Workflow B feasibility: see `WORKFLOW_B_FEASIBILITY.md`; no ranking assigned.
- Evaluation: A and B threshold rows are in `evaluation_feasibility.csv`; customer leakage and golden-label validity remain review items.

## Critical Blockers and Unknowns
- Exploratory reason-category matching is not a validated workflow label.
- Outcome fields do not establish correctness without manual or adjudicated labels.
- Raw free text and PII require restricted handling.
- No final workflow decision is made.
