# Targeted Evidence Report

## Scope and status

This is the first real-data evidence pass over exactly eight datasets. `digital_events` and `campaign_sends` were not read. Raw CSVs remain read-only, and transcript free-text columns were excluded from the cache.

- Cache: `C:\Users\anali\AppData\Local\Factored_hackathon_audit\targeted_evidence.duckdb`
- Cache size: `783,560,704` bytes
- Runtime: `140.52` seconds
- All reported measurements are exact unless explicitly marked `UNKNOWN`.
- No workflow is ranked or selected, and no ML training dataset was created.

## Dataset scale

- `customers`: `150,000` rows (EXACT)
- `products`: `400,000` rows (EXACT)
- `service_agents`: `1,200` rows (EXACT)
- `transactions`: `4,425,008` rows (EXACT)
- `call_center_interactions`: `686,296` rows (EXACT)
- `call_transcripts`: `171,321` rows (EXACT)
- `complaints`: `67,095` rows (EXACT)
- `satisfaction_surveys`: `212,759` rows (EXACT)

## Observed fact

### Data quality and keys

- **Quality:** `null_count` = `0` (OBSERVED FACT)
- **Quality:** `empty_count` = `0` (OBSERVED FACT)
- **Quality:** `null_count` = `0` (OBSERVED FACT)
- **Quality:** `empty_count` = `0` (OBSERVED FACT)
- **Quality:** `null_count` = `0` (OBSERVED FACT)
- **Quality:** `empty_count` = `0` (OBSERVED FACT)
- **Quality:** `null_count` = `0` (OBSERVED FACT)
- **Quality:** `empty_count` = `0` (OBSERVED FACT)
- **Quality:** `null_count` = `44817` (OBSERVED FACT)
- **Quality:** `empty_count` = `0` (OBSERVED FACT)
- **Quality:** `null_count` = `0` (OBSERVED FACT)
- **Quality:** `empty_count` = `0` (OBSERVED FACT)

Key uniqueness is reported in `05_relevant_profile.csv`; duplicate rows mean repeated non-empty candidate-key values and are not silently removed.

### Joins

All fifteen requested joins were measured from actual values. A relationship is labeled `OBSERVED RELATIONSHIP`, never `VERIFIED`. Exact rates and parent duplicate rates are in `06_join_quality.csv`.

### Language

Language was read only from `call_transcripts.detected_language`.

- Spanish observed: **YES**
- Portuguese observed: **NO**
- English observed: **NO**
- Other observed values: `NONE`

### Workflow A

- **Workflow A:** `total_transaction_records` = `4425008` (OBSERVED FACT)
- **Workflow A:** `distribution_transaction_status` = `4425008` (OBSERVED FACT)
- **Workflow A:** `distribution_transaction_category` = `4425008` (OBSERVED FACT)
- **Workflow A:** `distribution_transaction_type` = `4425008` (OBSERVED FACT)
- **Workflow A:** `distribution_response_code` = `4425008` (OBSERVED FACT)
- **Workflow A:** `failed_or_rejected_transaction_volume` = `221234` (DERIVED METRIC)
- **Workflow A:** `fraud_fields_existing_evidence_only` = `4425008` (OBSERVED FACT)
- **Workflow A:** `plausible_category_failed_transaction` = `0` (INFERENCE)
- **Workflow A:** `plausible_category_payment_problem` = `0` (INFERENCE)
- **Workflow A:** `plausible_category_transfer_problem` = `0` (INFERENCE)
- **Workflow A:** `plausible_category_withdrawal_problem` = `0` (INFERENCE)
- **Workflow A:** `plausible_category_dispute` = `0` (INFERENCE)

The interaction distributions were computed before category matching. Plausible categories retain their original values and are labeled inference; `is_fraud` is existing evidence only and was not used to adjudicate fraud.

### Workflow B

- **Workflow B:** `total_complaints` = `67095` (OBSERVED FACT)
- **Workflow B:** `distribution_category` = `67095` (OBSERVED FACT)
- **Workflow B:** `distribution_subcategory` = `60397` (OBSERVED FACT)
- **Workflow B:** `distribution_case_type` = `67095` (OBSERVED FACT)
- **Workflow B:** `distribution_priority` = `67095` (OBSERVED FACT)
- **Workflow B:** `distribution_status` = `67095` (OBSERVED FACT)
- **Workflow B:** `distribution_resolution` = `15310` (OBSERVED FACT)
- **Workflow B:** `resolution_date_availability` = `15349` (DERIVED METRIC)
- **Workflow B:** `closing_date_availability` = `2481` (DERIVED METRIC)
- **Workflow B:** `resolution_satisfaction_availability` = `2484` (DERIVED METRIC)
- **Workflow B:** `sla_breach_rate` = `20.113272` (DERIVED METRIC)
- **Workflow B:** `assignment_rate` = `100.0` (DERIVED METRIC)

Complaint intake, context enrichment, and resolution evaluation are reported as separate questions. A failed origin-interaction join does not make complaint intake impossible.

## Evaluation evidence

- **Evaluation:** `total_relevant_interactions_or_cases` = `686296` (OBSERVED FACT)
- **Evaluation:** `timestamp_available_rows` = `686296` (DERIVED METRIC)
- **Evaluation:** `outcome_or_proxy_available_rows` = `686296` (OBSERVED FACT)
- **Evaluation:** `survey_coverage_rows_or_cases` = `212759` (DERIVED METRIC)
- **Evaluation:** `unique_customers` = `148443` (DERIVED METRIC)
- **Evaluation:** `repeated_customer_rows` = `537853` (DERIVED METRIC)
- **Evaluation:** `duplicate_primary_key_rows` = `0` (DERIVED METRIC)
- **Evaluation:** `negative_process_event_lag_rows` = `686296` (DERIVED METRIC)
- **Evaluation:** `time_based_dev_validation_holdout_constructible` = `YES` (INFERENCE)
- **Evaluation:** `label_proxy_coverage_pct` = `100.0` (DERIVED METRIC)
- **Evaluation:** `temporal_leakage_risk` = `PRESENT` (INFERENCE)
- **Evaluation:** `total_relevant_interactions_or_cases` = `67095` (OBSERVED FACT)

Exact evaluation metrics, repeated-customer counts, proxy coverage, survey coverage, timestamp coverage, and leakage indicators are in `10_evaluation_feasibility.csv`. Time-based split constructibility is an inference about available timestamps, not a selected split.

## Derived metric, inference, and unknown

- **Derived metric:** percentages and rates are calculated from exact cache counts.
- **Inference:** plausible workflow categories, feasibility statements, and leakage flags are explicitly marked in the CSV outputs.
- **Unknown:** missing partition calendar dates are not declared without an external calendar contract; adjudicated labels, label correctness, and independent language validation are not present in this pass.

## Output files

- `05_relevant_profile.csv`: scale, relevant-field quality, key uniqueness, and temporal metrics.
- `06_join_quality.csv`: exact requested join measurements.
- `07_language_coverage.csv`: exact transcript language distribution.
- `08_workflow_A_feasibility.csv`: Workflow A evidence.
- `09_workflow_B_feasibility.csv`: Workflow B evidence.
- `10_evaluation_feasibility.csv`: evaluation evidence.
- `analysis_cache_manifest.json`: cache provenance and runtime metadata.
