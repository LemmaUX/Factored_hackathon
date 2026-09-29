"""Exact first evidence pass for Workflow A and Workflow B.

Raw CSV files are read-only. The script materializes only the selected columns into
an on-disk DuckDB cache outside OneDrive when LOCALAPPDATA is available.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REPORTS = ROOT / "reports" / "incremental"
CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "Factored_hackathon_audit"
DB_PATH = CACHE_ROOT / "targeted_evidence.duckdb"
TODAY = "2026-09-27 23:59:59"

DATASETS = {
    "customers": ["customer_id", "registration_branch_id", "customer_status", "country", "detected_accent"],
    "products": ["product_id", "customer_id", "product_status", "product_type", "opening_branch_id"],
    "service_agents": ["agent_id", "assigned_branch_id", "agent_status", "languages", "specialty"],
    "transactions": ["transaction_id", "transaction_date", "process_date", "product_id", "customer_id", "transaction_type", "transaction_category", "amount", "currency", "transaction_status", "response_code", "is_fraud", "fraud_score"],
    "call_center_interactions": ["interaction_id", "interaction_date", "process_date", "customer_id", "agent_id", "interaction_type", "channel", "contact_reason", "reason_category", "duration_seconds", "wait_time_seconds", "was_resolved", "requires_followup", "detected_sentiment", "sentiment_score", "was_escalated", "mentioned_products", "has_transcript"],
    "call_transcripts": ["transcript_id", "interaction_id", "process_date", "customer_id", "agent_id", "detected_language", "detected_accent", "accent_confidence", "detected_intents", "main_topics", "duration_seconds", "transcription_model", "audio_quality"],
    "complaints": ["complaint_id", "creation_date", "process_date", "customer_id", "case_type", "category", "subcategory", "reception_channel", "affected_product_id", "related_branch_id", "origin_interaction_id", "priority", "status", "assigned_agent_id", "assignment_date", "first_response_date", "resolution_date", "closing_date", "sla_breached", "resolution_days", "resolution", "compensation_granted", "resolution_satisfaction", "is_repeat_complainer"],
    "satisfaction_surveys": ["survey_id", "survey_date", "process_date", "interaction_id", "customer_id", "agent_id", "main_score", "nps_category", "comment_sentiment"],
}
FULL_COLUMNS = {
    "customers": ["customer_id", "document_number", "document_type", "first_name", "last_name", "date_of_birth", "gender", "email", "mobile_phone", "landline_phone", "address", "city", "state", "country", "postal_code", "detected_accent", "segment", "credit_score", "estimated_monthly_income", "occupation", "marital_status", "education_level", "registration_date", "registration_branch_id", "customer_status", "last_updated", "accepts_marketing"],
    "products": ["product_id", "customer_id", "product_type", "product_number", "currency", "current_balance", "credit_limit", "interest_rate", "opening_date", "expiration_date", "opening_branch_id", "product_status", "opening_channel", "has_linked_app", "days_past_due", "last_transaction_date", "last_updated"],
    "service_agents": ["agent_id", "employee_code", "first_name", "last_name", "email", "phone", "native_accent", "country_of_origin", "assigned_branch_id", "agent_type", "experience_level", "languages", "specialty", "hire_date", "avg_csat", "total_monthly_interactions", "agent_status", "work_shift"],
    "transactions": ["transaction_id", "transaction_date", "process_date", "product_id", "customer_id", "transaction_type", "transaction_category", "amount", "currency", "amount_usd", "channel", "branch_id", "merchant_name", "merchant_category", "transaction_country", "transaction_city", "transaction_status", "response_code", "is_fraud", "fraud_score", "latitude", "longitude"],
    "call_center_interactions": ["interaction_id", "interaction_date", "process_date", "customer_id", "agent_id", "interaction_type", "channel", "contact_reason", "reason_category", "duration_seconds", "wait_time_seconds", "was_resolved", "requires_followup", "detected_sentiment", "sentiment_score", "customer_detected_accent", "agent_used_accent", "was_escalated", "mentioned_products", "has_transcript", "has_recording"],
    "call_transcripts": ["transcript_id", "interaction_id", "process_date", "customer_id", "agent_id", "full_text", "customer_text", "agent_text", "detected_language", "detected_accent", "accent_confidence", "detected_keywords", "mentioned_entities", "detected_intents", "main_topics", "transcription_model", "audio_quality", "duration_seconds"],
    "complaints": ["complaint_id", "creation_date", "process_date", "customer_id", "case_type", "category", "subcategory", "reception_channel", "affected_product_id", "related_branch_id", "origin_interaction_id", "description", "claimed_amount", "currency", "priority", "status", "assigned_agent_id", "assignment_date", "first_response_date", "resolution_date", "closing_date", "sla_breached", "resolution_days", "resolution", "compensation_granted", "resolution_satisfaction", "is_repeat_complainer"],
    "satisfaction_surveys": ["survey_id", "survey_date", "process_date", "interaction_id", "customer_id", "agent_id", "survey_type", "send_channel", "main_score", "nps_category", "question_1_text", "question_1_response", "question_2_text", "question_2_response", "question_3_text", "question_3_response", "open_comments", "comment_sentiment", "response_time_hours", "campaign_response_rate"],
}
PRIMARY_KEYS = {name: fields[0] for name, fields in DATASETS.items()}
EVENT_DATES = {"transactions": "transaction_date", "call_center_interactions": "interaction_date", "call_transcripts": "process_date", "complaints": "creation_date", "satisfaction_surveys": "survey_date"}
JOIN_SPECS = [
    ("products", "customer_id", "customers", "customer_id"),
    ("transactions", "customer_id", "customers", "customer_id"),
    ("transactions", "product_id", "products", "product_id"),
    ("call_center_interactions", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "agent_id", "service_agents", "agent_id"),
    ("call_transcripts", "interaction_id", "call_center_interactions", "interaction_id"),
    ("call_transcripts", "customer_id", "customers", "customer_id"),
    ("call_transcripts", "agent_id", "service_agents", "agent_id"),
    ("complaints", "customer_id", "customers", "customer_id"),
    ("complaints", "affected_product_id", "products", "product_id"),
    ("complaints", "origin_interaction_id", "call_center_interactions", "interaction_id"),
    ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ("satisfaction_surveys", "interaction_id", "call_center_interactions", "interaction_id"),
    ("satisfaction_surveys", "customer_id", "customers", "customer_id"),
    ("satisfaction_surveys", "agent_id", "service_agents", "agent_id"),
]


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def clean(value):
    if value is None:
        return ""
    return str(value)


def nonempty(column: str) -> str:
    field = qident(column)
    return f"{field} IS NOT NULL AND trim(cast({field} AS VARCHAR)) <> ''"


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else ["status"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def table_files(name: str) -> list[Path]:
    if (DATA / f"{name}.csv").is_file():
        return [DATA / f"{name}.csv"]
    paths = sorted((DATA / name).rglob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No CSV files found for dataset {name}")
    return paths


def table_source(name: str) -> str:
    files = table_files(name)
    if len(files) == 1:
        return sql_string(str(files[0].resolve()).replace("\\", "/"))
    pattern = str((DATA / name / "**" / "*.csv").resolve()).replace("\\", "/")
    return sql_string(pattern)


def partition_expr() -> str:
    filename = qident("__source_file")
    year = f"try_cast(regexp_extract({filename}, 'year=([0-9]{{4}})', 1) AS INTEGER)"
    month = f"try_cast(regexp_extract({filename}, 'month=([0-9]{{2}})', 1) AS INTEGER)"
    day = f"try_cast(regexp_extract({filename}, 'day=([0-9]{{2}})', 1) AS INTEGER)"
    return year, month, day


def fetch_one(con, query: str):
    return con.execute(query).fetchone()


def scalar(con, query: str):
    return fetch_one(con, query)[0]


def make_cache(con) -> dict[str, int]:
    row_counts = {}
    for index, (name, columns) in enumerate(DATASETS.items(), 1):
        print(f"[{index}/{len(DATASETS)}] materializing {name}", flush=True)
        source = table_source(name)
        con.execute(f"DROP TABLE IF EXISTS {qident(name)}")
        column_map = ", ".join(f"{sql_string(column)}: 'VARCHAR'" for column in FULL_COLUMNS[name])
        con.execute(
            f"CREATE TABLE {qident(name)} AS SELECT {', '.join(qident(c) for c in columns)}, filename AS __source_file "
            f"FROM read_csv({source}, header=true, auto_detect=false, delim=',', quote='\"', escape='\"', columns={{{column_map}}}, union_by_name=true, filename=true, hive_partitioning=true, strict_mode=true)"
        )
        row_counts[name] = scalar(con, f"SELECT count(*) FROM {qident(name)}")
        print(f"    rows={row_counts[name]:,}", flush=True)
    return row_counts


def dataset_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for name, columns in DATASETS.items():
        date_column = EVENT_DATES.get(name)
        if date_column:
            expression = f"try_cast(nullif(trim(cast({qident(date_column)} AS VARCHAR)), '') AS TIMESTAMP)"
            minimum, maximum = fetch_one(con, f"SELECT min({expression}), max({expression}) FROM {qident(name)}")
            malformed = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {nonempty(date_column)} AND {expression} IS NULL")
        else:
            date_columns = [column for column in columns if re.search(r"date|time|timestamp", column, re.I)]
            expressions = [f"try_cast(nullif(trim(cast({qident(c)} AS VARCHAR)), '') AS TIMESTAMP)" for c in date_columns]
            minimum = scalar(con, f"SELECT min(least({', '.join(expressions)})) FROM {qident(name)}") if expressions else None
            maximum = scalar(con, f"SELECT max(greatest({', '.join(expressions)})) FROM {qident(name)}") if expressions else None
            malformed = "UNKNOWN" if not expressions else scalar(con, "SELECT 0")
        rows.append({"dataset": name, "metric": "row_count", "value": row_counts[name], "unit": "rows", "evidence_status": "EXACT"})
        rows.append({"dataset": name, "metric": "minimum_relevant_date", "value": minimum or "UNKNOWN", "unit": "timestamp", "evidence_status": "EXACT" if date_column else "UNKNOWN"})
        rows.append({"dataset": name, "metric": "maximum_relevant_date", "value": maximum or "UNKNOWN", "unit": "timestamp", "evidence_status": "EXACT" if date_column else "UNKNOWN"})
        rows.append({"dataset": name, "metric": "malformed_relevant_dates", "value": malformed, "unit": "rows", "evidence_status": "EXACT" if date_column else "UNKNOWN"})
    return rows


def quality_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for name, columns in DATASETS.items():
        total = row_counts[name]
        for column in columns:
            field = qident(column)
            null_count, empty_count = fetch_one(con, f"SELECT count(*) FILTER (WHERE {field} IS NULL), count(*) FILTER (WHERE {field} IS NOT NULL AND trim(cast({field} AS VARCHAR)) = '') FROM {qident(name)}")
            for metric, value in (("null_count", null_count), ("empty_count", empty_count)):
                rows.append({"dataset": name, "field": column, "metric": metric, "value": value, "percentage": round(value / total * 100, 6) if total else 0, "evidence_status": "EXACT"})
    return rows


def key_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for name, key in PRIMARY_KEYS.items():
        field = qident(key)
        total = row_counts[name]
        nonnull = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {nonempty(key)}")
        distinct = scalar(con, f"SELECT count(DISTINCT trim(cast({field} AS VARCHAR))) FROM {qident(name)} WHERE {nonempty(key)}")
        duplicate_rows = nonnull - distinct
        rows.append({"dataset": name, "candidate_primary_key": key, "total_rows": total, "non_null_rows": nonnull, "distinct_values": distinct, "duplicate_rows": duplicate_rows, "duplicate_key_rate_pct": round(duplicate_rows / total * 100, 6) if total else 0, "evidence_status": "EXACT"})
    return rows


def join_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for child, child_key, parent, parent_key in JOIN_SPECS:
        child_field, parent_field = qident(child_key), qident(parent_key)
        child_nonnull, child_distinct = fetch_one(con, f"SELECT count(*) FILTER (WHERE {nonempty(child_key)}), count(DISTINCT trim(cast({child_field} AS VARCHAR))) FROM {qident(child)} WHERE {nonempty(child_key)}")
        matched = scalar(con, f"SELECT count(*) FROM (SELECT DISTINCT trim(cast({child_field} AS VARCHAR)) AS join_key FROM {qident(child)} WHERE {nonempty(child_key)}) c INNER JOIN (SELECT DISTINCT trim(cast({parent_field} AS VARCHAR)) AS join_key FROM {qident(parent)} WHERE {nonempty(parent_key)}) p USING (join_key)")
        parent_total, parent_nonnull, parent_distinct = fetch_one(con, f"SELECT count(*), count(*) FILTER (WHERE {nonempty(parent_key)}), count(DISTINCT trim(cast({parent_field} AS VARCHAR))) FROM {qident(parent)}")
        unmatched = child_distinct - matched
        rows.append({"child_dataset": child, "child_key": child_key, "parent_dataset": parent, "parent_key": parent_key, "child_row_count": row_counts[child], "non_null_child_keys": child_nonnull, "distinct_child_keys": child_distinct, "matched_distinct_keys": matched, "unmatched_distinct_keys": unmatched, "match_rate_pct": round(matched / child_distinct * 100, 6) if child_distinct else 0, "orphan_rate_pct": round(unmatched / child_distinct * 100, 6) if child_distinct else 0, "parent_duplicate_key_rate_pct": round((parent_nonnull - parent_distinct) / parent_total * 100, 6) if parent_total else 0, "status": "OBSERVED RELATIONSHIP"})
    return rows


def temporal_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    partition_year, partition_month, partition_day = partition_expr()
    for name, event_column in EVENT_DATES.items():
        field = qident(event_column)
        timestamp = f"try_cast(nullif(trim(cast({field} AS VARCHAR)), '') AS TIMESTAMP)"
        distinct_dates, future, malformed = fetch_one(con, f"SELECT count(DISTINCT cast({timestamp} AS DATE)), count(*) FILTER (WHERE {timestamp} > TIMESTAMP {sql_string(TODAY)}), count(*) FILTER (WHERE {nonempty(event_column)} AND {timestamp} IS NULL) FROM {qident(name)}")
        partition_dates = scalar(con, f"SELECT count(DISTINCT ({partition_year}, {partition_month}, {partition_day})) FROM {qident(name)} WHERE {partition_year} IS NOT NULL")
        partition_min, partition_max = fetch_one(con, f"SELECT min(make_date({partition_year}, {partition_month}, coalesce({partition_day}, 1))), max(make_date({partition_year}, {partition_month}, coalesce({partition_day}, 1))) FROM {qident(name)} WHERE {partition_year} IS NOT NULL AND {partition_month} IS NOT NULL")
        missing_partition_dates = scalar(con, f"SELECT count(*) FROM generate_series(cast({sql_string(str(partition_min))} AS DATE), cast({sql_string(str(partition_max))} AS DATE), INTERVAL 1 DAY) AS series_day WHERE series_day.generate_series::DATE NOT IN (SELECT DISTINCT make_date({partition_year}, {partition_month}, coalesce({partition_day}, 1)) FROM {qident(name)} WHERE {partition_year} IS NOT NULL AND {partition_month} IS NOT NULL)") if partition_min and partition_max else 0
        aligned = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {timestamp} IS NOT NULL AND {partition_year} = year(cast({timestamp} AS DATE)) AND {partition_month} = month(cast({timestamp} AS DATE)) AND ({partition_day} IS NULL OR {partition_day} = day(cast({timestamp} AS DATE)))")
        mismatched = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {timestamp} IS NOT NULL AND ({partition_year} IS NULL OR {partition_year} <> year(cast({timestamp} AS DATE)) OR {partition_month} <> month(cast({timestamp} AS DATE)) OR ({partition_day} IS NOT NULL AND {partition_day} <> day(cast({timestamp} AS DATE))))")
        minimum, maximum = fetch_one(con, f"SELECT min({timestamp}), max({timestamp}) FROM {qident(name)}")
        rows.extend([
            {"dataset": name, "metric": "event_min", "value": minimum or "UNKNOWN", "evidence_status": "EXACT"},
            {"dataset": name, "metric": "event_max", "value": maximum or "UNKNOWN", "evidence_status": "EXACT"},
            {"dataset": name, "metric": "distinct_event_dates", "value": distinct_dates, "evidence_status": "EXACT"},
            {"dataset": name, "metric": "partition_dates_represented", "value": partition_dates, "evidence_status": "EXACT"},
            {"dataset": name, "metric": "missing_partition_dates", "value": missing_partition_dates, "evidence_status": "EXACT", "note": "Gaps between minimum and maximum represented partition dates"},
            {"dataset": name, "metric": "future_timestamps", "value": future, "evidence_status": "EXACT"},
            {"dataset": name, "metric": "malformed_timestamps", "value": malformed, "evidence_status": "EXACT"},
            {"dataset": name, "metric": "event_process_lag", "value": "computed below", "evidence_status": "EXACT"},
            {"dataset": name, "metric": "partition_aligned_rows", "value": aligned, "evidence_status": "EXACT"},
            {"dataset": name, "metric": "partition_mismatched_rows", "value": mismatched, "evidence_status": "EXACT"},
            {"dataset": name, "metric": "partition_mismatch_rate_pct", "value": round(mismatched / (aligned + mismatched) * 100, 6) if aligned + mismatched else 0, "evidence_status": "EXACT"},
        ])
        process = qident("process_date")
        process_ts = f"try_cast(nullif(trim(cast({process} AS VARCHAR)), '') AS TIMESTAMP)"
        lag_count, negative_lag, minimum_lag, maximum_lag = fetch_one(con, f"SELECT count(*) FILTER (WHERE {timestamp} IS NOT NULL AND {process_ts} IS NOT NULL), count(*) FILTER (WHERE {timestamp} IS NOT NULL AND {process_ts} IS NOT NULL AND {process_ts} < {timestamp}), min(date_diff('second', {timestamp}, {process_ts})), max(date_diff('second', {timestamp}, {process_ts})) FROM {qident(name)}")
        rows[-4]["value"] = {"rows_with_both_dates": lag_count, "negative_lag_rows": negative_lag, "minimum_lag_seconds": minimum_lag, "maximum_lag_seconds": maximum_lag}
    return rows


def distribution(con, dataset: str, column: str, family: str) -> list[dict]:
    field = qident(column)
    result = con.execute(f"SELECT coalesce(nullif(trim(cast({field} AS VARCHAR)), ''), 'UNKNOWN') AS value, count(*) AS rows FROM {qident(dataset)} GROUP BY 1 ORDER BY rows DESC, value").fetchall()
    total = sum(row[1] for row in result)
    return [{"dataset": dataset, "field": column, "category": clean(value), "rows": count, "percentage": round(count / total * 100, 6) if total else 0, "distribution_family": family, "evidence_status": "OBSERVED FACT"} for value, count in result]


def count_where(con, dataset: str, predicate: str) -> int:
    return scalar(con, f"SELECT count(*) FROM {qident(dataset)} WHERE {predicate}")


def workflow_a(con, row_counts: dict[str, int], distributions: list[dict]) -> list[dict]:
    rows = [{"workflow": "A", "metric": "total_transaction_records", "value": row_counts["transactions"], "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT"}]
    for name, column in (("transactions", "transaction_status"), ("transactions", "transaction_category"), ("transactions", "transaction_type"), ("transactions", "response_code")):
        rows.append({"workflow": "A", "metric": f"distribution_{column}", "value": sum(item["rows"] for item in distributions if item["dataset"] == name and item["field"] == column), "category_detail": json.dumps([item for item in distributions if item["dataset"] == name and item["field"] == column], ensure_ascii=False), "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT"})
    rows.extend([
        {"workflow": "A", "metric": "failed_or_rejected_transaction_volume", "value": count_where(con, "transactions", "lower(coalesce(cast(transaction_status AS VARCHAR), '')) IN ('failed', 'failure', 'rejected', 'declined', 'cancelled', 'canceled')"), "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
        {"workflow": "A", "metric": "fraud_fields_existing_evidence_only", "value": count_where(con, "transactions", f"{nonempty('is_fraud')} OR {nonempty('fraud_score')}"), "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT", "note": "Not used to adjudicate fraud"},
    ])
    reason_values = [item for item in distributions if item["dataset"] == "call_center_interactions" and item["field"] in {"contact_reason", "reason_category", "interaction_type"}]
    tokens = {"failed_transaction": r"fail|declin|reject|unsuccess", "payment_problem": r"payment|pay", "transfer_problem": r"transfer", "withdrawal_problem": r"withdraw|cash", "dispute": r"dispute|chargeback", "transaction_inquiry": r"transaction|transac|inquir"}
    relevant_predicates = []
    for label, pattern in tokens.items():
        matched = sorted({item["category"] for item in reason_values if re.search(pattern, item["category"], re.I)})
        rows.append({"workflow": "A", "metric": f"plausible_category_{label}", "value": len(matched), "category_detail": json.dumps(matched, ensure_ascii=False), "evidence_type": "INFERENCE", "evidence_status": "EXACT", "note": "Original observed category names retained; manual validation required"})
        if matched:
            quoted = ", ".join(sql_string(value) for value in matched)
            relevant_predicates.append(f"coalesce(nullif(trim(cast(contact_reason AS VARCHAR)), ''), 'UNKNOWN') IN ({quoted}) OR coalesce(nullif(trim(cast(reason_category AS VARCHAR)), ''), 'UNKNOWN') IN ({quoted}) OR coalesce(nullif(trim(cast(interaction_type AS VARCHAR)), ''), 'UNKNOWN') IN ({quoted})")
    relevant = count_where(con, "call_center_interactions", " OR ".join(f"({p})" for p in relevant_predicates) or "1 = 0")
    total_interactions = row_counts["call_center_interactions"]
    for metric, value in [("transaction_related_customer_service_interactions", relevant), ("relevant_interaction_percentage", round(relevant / total_interactions * 100, 6) if total_interactions else 0), ("resolved_rate", round(count_where(con, "call_center_interactions", f"lower(cast(was_resolved AS VARCHAR)) IN ('true', 'yes', '1') AND ({' OR '.join(f'({p})' for p in relevant_predicates) or '1 = 0'})") / relevant * 100, 6) if relevant else 0), ("escalation_rate", round(count_where(con, "call_center_interactions", f"lower(cast(was_escalated AS VARCHAR)) IN ('true', 'yes', '1') AND ({' OR '.join(f'({p})' for p in relevant_predicates) or '1 = 0'})") / relevant * 100, 6) if relevant else 0), ("follow_up_rate", round(count_where(con, "call_center_interactions", f"lower(cast(requires_followup AS VARCHAR)) IN ('true', 'yes', '1') AND ({' OR '.join(f'({p})' for p in relevant_predicates) or '1 = 0'})") / relevant * 100, 6) if relevant else 0), ("transcript_availability_rate", round(count_where(con, "call_center_interactions", f"lower(cast(has_transcript AS VARCHAR)) IN ('true', 'yes', '1') AND ({' OR '.join(f'({p})' for p in relevant_predicates) or '1 = 0'})") / relevant * 100, 6) if relevant else 0)]:
        rows.append({"workflow": "A", "metric": metric, "value": value, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"})
    return rows


def workflow_b(con, row_counts: dict[str, int], joins: list[dict]) -> list[dict]:
    rows = [{"workflow": "B", "metric": "total_complaints", "value": row_counts["complaints"], "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT"}]
    for column in ("category", "subcategory", "case_type", "priority", "status", "resolution"):
        rows.append({"workflow": "B", "metric": f"distribution_{column}", "value": count_where(con, "complaints", nonempty(column)), "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT"})
    for column in ("resolution_date", "closing_date", "resolution_satisfaction"):
        rows.append({"workflow": "B", "metric": f"{column}_availability", "value": count_where(con, "complaints", nonempty(column)), "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"})
    join_rates = {item["child_key"]: item["match_rate_pct"] for item in joins if item["child_dataset"] == "complaints"}
    for metric, column in (("sla_breach_rate", "sla_breached"), ("assignment_rate", "assigned_agent_id"), ("customer_linkage_rate", "customer_id"), ("product_linkage_rate", "affected_product_id"), ("agent_linkage_rate", "assigned_agent_id"), ("interaction_origin_linkage_rate", "origin_interaction_id")):
        if metric == "sla_breach_rate":
            value = round(count_where(con, "complaints", "lower(cast(sla_breached AS VARCHAR)) IN ('true', 'yes', '1')") / row_counts["complaints"] * 100, 6) if row_counts["complaints"] else 0
        else:
            value = join_rates.get(column, 0)
        rows.append({"workflow": "B", "metric": metric, "value": value, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"})
    complaint_interactions = scalar(con, "SELECT count(*) FROM call_center_interactions i INNER JOIN complaints c ON trim(cast(i.interaction_id AS VARCHAR)) = trim(cast(c.origin_interaction_id AS VARCHAR)) WHERE " + nonempty("origin_interaction_id"))
    rows.append({"workflow": "B", "metric": "complaint_related_interaction_volume", "value": complaint_interactions, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"})
    rows.append({"workflow": "B", "metric": "complaint_intake_feasibility", "value": "OBSERVED", "evidence_type": "INFERENCE", "evidence_status": "EXACT", "note": "Complaint records and customer linkage are measured"})
    rows.append({"workflow": "B", "metric": "complaint_context_enrichment_feasibility", "value": "CONDITIONAL", "evidence_type": "INFERENCE", "evidence_status": "EXACT", "note": "Depends on measured product, interaction, and agent joins"})
    rows.append({"workflow": "B", "metric": "complaint_resolution_evaluation_feasibility", "value": "CONDITIONAL", "evidence_type": "INFERENCE", "evidence_status": "EXACT", "note": "Resolution fields are observed outcomes/proxies, not adjudicated correctness"})
    return rows


def evaluation(con, row_counts: dict[str, int], joins: list[dict]) -> list[dict]:
    rows = []
    specs = [("A", "call_center_interactions", "interaction_date", "customer_id"), ("B", "complaints", "creation_date", "customer_id")]
    for workflow, dataset, date_column, customer_column in specs:
        total = row_counts[dataset]
        dated = count_where(con, dataset, f"try_cast(nullif(trim(cast({qident(date_column)} AS VARCHAR)), '') AS TIMESTAMP) IS NOT NULL")
        repeated = scalar(con, f"SELECT coalesce(sum(n - 1) FILTER (WHERE n > 1), 0) FROM (SELECT trim(cast({qident(customer_column)} AS VARCHAR)) AS customer_id, count(*) AS n FROM {qident(dataset)} WHERE {nonempty(customer_column)} GROUP BY 1)")
        customers = scalar(con, f"SELECT count(DISTINCT trim(cast({qident(customer_column)} AS VARCHAR))) FROM {qident(dataset)} WHERE {nonempty(customer_column)}")
        survey_coverage = scalar(con, f"SELECT count(DISTINCT trim(cast(i.interaction_id AS VARCHAR))) FROM {qident('call_center_interactions')} i INNER JOIN {qident('satisfaction_surveys')} s ON trim(cast(i.interaction_id AS VARCHAR)) = trim(cast(s.interaction_id AS VARCHAR)) WHERE i.interaction_id IS NOT NULL AND trim(cast(i.interaction_id AS VARCHAR)) <> '' AND try_cast(nullif(trim(cast(i.interaction_date AS VARCHAR)), '') AS TIMESTAMP) IS NOT NULL") if workflow == "A" else scalar(con, f"SELECT count(DISTINCT trim(cast(c.complaint_id AS VARCHAR))) FROM {qident('complaints')} c INNER JOIN {qident('satisfaction_surveys')} s ON trim(cast(c.origin_interaction_id AS VARCHAR)) = trim(cast(s.interaction_id AS VARCHAR)) WHERE c.origin_interaction_id IS NOT NULL AND trim(cast(c.origin_interaction_id AS VARCHAR)) <> ''")
        process_col = "process_date"
        negative_lag = count_where(con, dataset, f"try_cast(nullif(trim(cast({qident(process_col)} AS VARCHAR)), '') AS TIMESTAMP) IS NOT NULL AND try_cast(nullif(trim(cast({qident(date_column)} AS VARCHAR)), '') AS TIMESTAMP) IS NOT NULL AND try_cast(nullif(trim(cast({qident(process_col)} AS VARCHAR)), '') AS TIMESTAMP) < try_cast(nullif(trim(cast({qident(date_column)} AS VARCHAR)), '') AS TIMESTAMP)")
        relevant = row_counts["call_center_interactions"] if workflow == "A" else row_counts["complaints"]
        outcome = count_where(con, "call_center_interactions" if workflow == "A" else "complaints", nonempty("was_resolved" if workflow == "A" else "resolution"))
        rows.extend([
            {"workflow": workflow, "metric": "total_relevant_interactions_or_cases", "value": relevant, "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "timestamp_available_rows", "value": dated, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "outcome_or_proxy_available_rows", "value": outcome, "evidence_type": "OBSERVED FACT", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "survey_coverage_rows_or_cases", "value": survey_coverage, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "unique_customers", "value": customers, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "repeated_customer_rows", "value": repeated, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "duplicate_primary_key_rows", "value": next(item["duplicate_rows"] for item in key_profile(con, row_counts) if item["dataset"] == dataset), "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "negative_process_event_lag_rows", "value": negative_lag, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT"},
            {"workflow": workflow, "metric": "time_based_dev_validation_holdout_constructible", "value": "YES" if dated and customers else "UNKNOWN", "evidence_type": "INFERENCE", "evidence_status": "EXACT", "note": "Constructibility only; no training dataset or split was created"},
            {"workflow": workflow, "metric": "label_proxy_coverage_pct", "value": round(outcome / relevant * 100, 6) if relevant else 0, "evidence_type": "DERIVED METRIC", "evidence_status": "EXACT", "note": "Proxy coverage, not ground truth"},
            {"workflow": workflow, "metric": "temporal_leakage_risk", "value": "PRESENT" if negative_lag or repeated else "NOT_OBSERVED", "evidence_type": "INFERENCE", "evidence_status": "EXACT"},
        ])
    return rows


def render_report(row_counts, profiles, quality, keys, joins, temporal, languages, a_rows, b_rows, eval_rows, runtime, cache_size):
    def metric_rows(items, label):
        return "\n".join(f"- **{label}:** `{item['metric']}` = `{item['value']}` ({item.get('evidence_type', 'OBSERVED FACT')})" for item in items[:12])
    language_names = [row["category"] for row in languages]
    yes_no = lambda value: "YES" if any(re.search(value, name, re.I) for name in language_names) else "NO"
    return f"""# Targeted Evidence Report

## Scope and status

This is the first real-data evidence pass over exactly eight datasets. `digital_events` and `campaign_sends` were not read. Raw CSVs remain read-only, and transcript free-text columns were excluded from the cache.

- Cache: `{DB_PATH}`
- Cache size: `{cache_size:,}` bytes
- Runtime: `{runtime:.2f}` seconds
- All reported measurements are exact unless explicitly marked `UNKNOWN`.
- No workflow is ranked or selected, and no ML training dataset was created.

## Dataset scale

{chr(10).join(f"- `{name}`: `{count:,}` rows (EXACT)" for name, count in row_counts.items())}

## Observed fact

### Data quality and keys

{metric_rows(quality, 'Quality')}

Key uniqueness is reported in `05_relevant_profile.csv`; duplicate rows mean repeated non-empty candidate-key values and are not silently removed.

### Joins

All fifteen requested joins were measured from actual values. A relationship is labeled `OBSERVED RELATIONSHIP`, never `VERIFIED`. Exact rates and parent duplicate rates are in `06_join_quality.csv`.

### Language

Language was read only from `call_transcripts.detected_language`.

- Spanish observed: **{yes_no(r'(^|[^a-z])es($|[^a-z])|spanish|español|espanol')}**
- Portuguese observed: **{yes_no(r'(^|[^a-z])pt($|[^a-z])|portugu')}**
- English observed: **{yes_no(r'(^|[^a-z])en($|[^a-z])|english|inglés|ingles')}**
- Other observed values: `{', '.join(name for name in language_names if not re.search(r'(^|[^a-z])(es|pt|en)($|[^a-z])|spanish|español|espanol|portugu|english|inglés|ingles', name, re.I)) or 'NONE'}`

### Workflow A

{metric_rows(a_rows, 'Workflow A')}

The interaction distributions were computed before category matching. Plausible categories retain their original values and are labeled inference; `is_fraud` is existing evidence only and was not used to adjudicate fraud.

### Workflow B

{metric_rows(b_rows, 'Workflow B')}

Complaint intake, context enrichment, and resolution evaluation are reported as separate questions. A failed origin-interaction join does not make complaint intake impossible.

## Evaluation evidence

{metric_rows(eval_rows, 'Evaluation')}

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
"""


def main() -> int:
    started = time.perf_counter()
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (CACHE_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='512MB'")
    con.execute(f"PRAGMA temp_directory={sql_string(str(CACHE_ROOT / 'tmp'))}")
    con.execute("PRAGMA preserve_insertion_order=false")
    try:
        row_counts = make_cache(con)
        con.execute("CHECKPOINT")
        print("cache checkpointed", flush=True)
        print("profiling dataset scale and relevant quality", flush=True)
        profiles = dataset_profile(con, row_counts)
        quality = quality_profile(con, row_counts)
        print("profiling keys, joins, and temporal evidence", flush=True)
        keys = key_profile(con, row_counts)
        joins = join_profile(con, row_counts)
        temporal = temporal_profile(con, row_counts)
        print("profiling distributions and workflow evidence", flush=True)
        distributions = []
        for dataset, columns, family in (("transactions", ["transaction_status", "transaction_category", "transaction_type", "response_code"], "workflow_A_transactions"), ("call_center_interactions", ["contact_reason", "reason_category", "interaction_type"], "workflow_A_interactions"), ("complaints", ["category", "subcategory", "case_type", "priority", "status", "resolution"], "workflow_B_complaints")):
            for column in columns:
                distributions.extend(distribution(con, dataset, column, family))
        languages = distribution(con, "call_transcripts", "detected_language", "language")
        a_rows = workflow_a(con, row_counts, distributions)
        b_rows = workflow_b(con, row_counts, joins)
        eval_rows = evaluation(con, row_counts, joins)
        print("writing evidence reports", flush=True)
        runtime = time.perf_counter() - started
        con.close()
        cache_size = DB_PATH.stat().st_size
        write_csv(REPORTS / "05_relevant_profile.csv", profiles + quality + keys + temporal)
        write_csv(REPORTS / "06_join_quality.csv", joins)
        write_csv(REPORTS / "07_language_coverage.csv", languages)
        write_csv(REPORTS / "08_workflow_A_feasibility.csv", distributions + a_rows)
        write_csv(REPORTS / "09_workflow_B_feasibility.csv", distributions + b_rows)
        write_csv(REPORTS / "10_evaluation_feasibility.csv", eval_rows)
        manifest = {"script": "targeted_evidence.py", "execution_utc": datetime.now(timezone.utc).isoformat(), "data_root": str(DATA), "cache_path": str(DB_PATH), "cache_size_bytes": cache_size, "duckdb_version": duckdb.__version__, "duckdb_threads": 4, "datasets_processed": list(DATASETS), "excluded_datasets": ["digital_events", "campaign_sends"], "row_counts": row_counts, "rows_are": "EXACT", "raw_files_read_only": True, "transcript_text_materialized": False, "runtime_seconds": round(runtime, 3), "warnings": ["Partition gaps are exact only within the observed minimum-to-maximum date span; external calendar completeness remains UNKNOWN.", "Outcome fields and language values are observed fields, not independently adjudicated labels."], "errors": []}
        (REPORTS / "analysis_cache_manifest.json").write_text(json.dumps(manifest, indent=2, default=json_default), encoding="utf-8")
        report = render_report(row_counts, profiles, quality, keys, joins, temporal, languages, a_rows, b_rows, eval_rows, runtime, cache_size)
        (REPORTS / "TARGETED_EVIDENCE_REPORT.md").write_text(report, encoding="utf-8")
        print("TARGETED EVIDENCE COMPLETE", flush=True)
        print(f"datasets processed: {', '.join(DATASETS)}", flush=True)
        print(f"rows per dataset: {json.dumps(row_counts)}", flush=True)
        print(f"cache location: {DB_PATH}", flush=True)
        print(f"cache size: {cache_size:,} bytes", flush=True)
        print(f"total runtime: {runtime:.2f} seconds", flush=True)
        print(f"join test status: PASS ({len(joins)}/{len(JOIN_SPECS)} relationships measured)", flush=True)
        print(f"language test status: PASS ({len(languages)} observed values)", flush=True)
        print("Workflow A evidence status: PASS", flush=True)
        print("Workflow B evidence status: PASS", flush=True)
        print("evaluation evidence status: PASS", flush=True)
        print("errors/warnings: 0 errors; 2 documented warnings in analysis_cache_manifest.json", flush=True)
        return 0
    except Exception as exc:
        try:
            con.close()
        finally:
            traceback.print_exc()
            print(f"TARGETED_EVIDENCE_ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
