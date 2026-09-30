"""Targeted evidence pass (v2) for Workflow A and Workflow B.

Raw CSV files are read-only. The script materializes only the selected columns into
an on-disk DuckDB cache outside OneDrive when LOCALAPPDATA is available.

Architecture contract (unchanged from v1):
  - local DuckDB cache, single-pass materialization of selected columns
  - 4 DuckDB threads, 512 MB memory limit
  - same eight relevant datasets / same column scope

Methodology contract (v2 fixes):
  - Temporal ordering is granularity-aware: DATE-granularity values are compared at
    calendar-day granularity; strict timestamp comparison is used only when BOTH sides
    genuinely contain time-of-day information. Same-calendar-day rows are NEVER counted
    as process-before-event merely because a date-only value parses to midnight.
  - Repeated-customer structure, cross-split entity overlap, temporal ordering risk,
    and post-outcome feature risk are reported as SEPARATE diagnostics. Repeated
    customers are NOT treated as leakage.
  - Workflow A category mapping is evidence-based against the observed (Spanish)
    taxonomy via reports/incremental/workflow_A_category_mapping.csv; the old
    English-regex-only mechanism is removed. Unsupported granular intents are recorded
    as NO_EVIDENCE_IN_OBSERVED_TAXONOMY instead of being silently mapped to zero.
  - Workflow B linkage metrics are separated: non-null FK rate vs FK match rate vs
    agent assignment vs resolution/outcome availability. Zero non-null FK keys yields
    match_rate = UNKNOWN (not 0).
  - Terminal statuses describe execution/evidence generation (EVIDENCE_GENERATED),
    never workflow feasibility. Feasibility judgments use PASS/PARTIAL/FAIL/UNKNOWN.
  - The runtime date used for future-timestamp checks is derived at execution time and
    stored in analysis_cache_manifest.json ("evaluation_runtime_date").
  - write_csv uses the UNION of keys across all rows with deterministic column order.
  - Artifact updates use explicit record identity (dataset/metric), never row positions.
  - Key-profile queries run once and are reused (no redundant full-table scans).
  - Metrics that merely restated their own query predicate were removed or replaced by
    actual validations.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REPORTS = ROOT / "reports" / "incremental"
CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "Factored_hackathon_audit"
DB_PATH = CACHE_ROOT / "targeted_evidence.duckdb"

# ---------------------------------------------------------------------------
# Configuration constants (architecture preserved)
# ---------------------------------------------------------------------------
DUCKDB_THREADS = 4
DUCKDB_MEMORY_LIMIT = "512MB"

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

# Distribution families written to authoritative artifacts. Each family appears in
# exactly ONE artifact (fix #12); other outputs reference that file instead of
# recomputing duplicate distributions. Recorded in the manifest under
# "distribution_authority".
DISTRIBUTION_FAMILIES = {
    "workflow_A_transactions": ("transactions", ["transaction_status", "transaction_category", "transaction_type", "response_code"]),
    "workflow_A_interactions": ("call_center_interactions", ["contact_reason", "reason_category", "interaction_type"]),
    "workflow_B_complaints": ("complaints", ["category", "subcategory", "case_type", "priority", "status", "resolution"]),
    "language": ("call_transcripts", ["detected_language"]),
}

# ---------------------------------------------------------------------------
# Workflow A category mapping policy (fix #3)
#
# Evidence rules applied to the OBSERVED taxonomy only. No mapping is invented:
#   - Transaccional -> transaction_inquiry at MEDIUM confidence (broad transactional
#     contact bucket; does not by itself imply failure/payment/transfer/withdrawal).
#   - Queja -> dispute at LOW confidence (complaint bucket may include disputes but
#     also non-transactional complaints).
#   - Every other observed category -> unknown (no supporting evidence).
#   - Granular intents failed_transaction, payment_problem, transfer_problem,
#     withdrawal_problem have NO evidence in the observed taxonomy and are recorded
#     explicitly as NO_EVIDENCE_IN_OBSERVED_TAXONOMY.
#   - interaction_type carries channel/type metadata only (Inbound Call, Chat, ...)
#     and is excluded from intent mapping.
# ---------------------------------------------------------------------------
CATEGORY_MAPPING_POLICY = {
    "Transaccional": ("transaction_inquiry", "MEDIUM"),
    "Queja": ("dispute", "LOW"),
}
ALLOWED_CANDIDATE_INTENTS = [
    "failed_transaction", "payment_problem", "transfer_problem", "withdrawal_problem",
    "dispute", "transaction_inquiry", "unrelated", "unknown",
]
NO_EVIDENCE_INTENTS = ["failed_transaction", "payment_problem", "transfer_problem", "withdrawal_problem"]
INTENT_FIELDS = ["contact_reason", "reason_category"]

TRUTHY_SQL = "lower(trim(coalesce(cast({f} AS VARCHAR), ''))) IN ('true', 'yes', '1', 'si', 'sí')"


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


def ts_expr(column: str) -> str:
    """Timestamp parse expression (empty-string-safe).

    Accepts a bare column name or an `alias.column` reference; each identifier part
    is quoted independently so qualified references remain valid SQL.
    """
    if "." in column:
        alias, bare = column.split(".", 1)
        field = f"{qident(alias)}.{qident(bare)}"
    else:
        field = qident(column)
    return f"try_cast(nullif(trim(cast({field} AS VARCHAR)), '') AS TIMESTAMP)"


def has_time_expr(column: str) -> str:
    """Boolean SQL: the raw value genuinely contains a non-midnight time-of-day."""
    ts = ts_expr(column)
    return f"({ts} IS NOT NULL AND ({ts} <> cast(cast({ts} AS DATE) AS TIMESTAMP)))"


def granularity_case(process_col: str, event_col: str) -> str:
    """SQL CASE returning the comparison granularity for a process/event pair.

    - BOTH_TIMESTAMP: both parsed values carry genuine time-of-day information.
    - CALENDAR_DAY:   at least one side is date-only (parses to midnight) or the
      process column is absent; comparison happens at day granularity.
    - UNKNOWN:        either side missing/unparseable.
    """
    p_ts, e_ts = ts_expr(process_col), ts_expr(event_col)
    p_has, e_has = has_time_expr(process_col), has_time_expr(event_col)
    return (
        f"CASE WHEN {p_ts} IS NULL OR {e_ts} IS NULL THEN 'UNKNOWN' "
        f"WHEN {p_has} AND {e_has} THEN 'BOTH_TIMESTAMP' "
        f"ELSE 'CALENDAR_DAY' END"
    )


def classify_ordering(process_value, event_value):
    """Pure-Python granularity-aware classification used by unit tests and the audit.

    Returns one of:
      EVENT_BEFORE_PROCESS | PROCESS_BEFORE_EVENT | SAME_CALENDAR_DAY | UNKNOWN
    (UNKNOWN == temporal_comparison_unknown: a missing or unparseable side; the
    artifact metric exposing this bucket is named temporal_comparison_unknown_count.)
    Rules (fix #1):
      A. Both values contain time-of-day -> compare full timestamps.
      B. Either side is date-only -> compare at calendar-day granularity.
      C. Same-calendar-day is NEVER process-before-event due to midnight semantics.
    """
    p = _to_datetime(process_value)
    e = _to_datetime(event_value)
    if p is None or e is None:
        return "UNKNOWN"
    if _carries_time(p) and _carries_time(e):
        if p == e:
            return "SAME_CALENDAR_DAY"
        return "PROCESS_BEFORE_EVENT" if p < e else "EVENT_BEFORE_PROCESS"
    if p.date() < e.date():
        return "PROCESS_BEFORE_EVENT"
    if p.date() > e.date():
        return "EVENT_BEFORE_PROCESS"
    return "SAME_CALENDAR_DAY"


def _to_datetime(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _carries_time(value: datetime) -> bool:
    return bool(value.hour or value.minute or value.second or value.microsecond)


def union_schema(rows: list[dict]) -> list[str]:
    """Deterministic schema: union of keys across ALL rows, first-seen order."""
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    return list(seen)


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    """Write CSV with the UNION of keys across all rows (fix #8).

    Fields present in later rows but absent from the first row are no longer dropped.
    Missing values are written as empty cells; callers should set explicit UNKNOWN/N/A.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or union_schema(rows) or ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _glob_pattern(path: Path) -> str:
    """Glob patterns must keep their wildcards; only concrete paths are resolved."""
    text = str(path.resolve()) if "*" not in str(path) else str(path)
    return text.replace("\\", "/")


def table_source(name: str) -> str:
    single = DATA / f"{name}.csv"
    if single.is_file():
        return sql_string(_glob_pattern(single))
    hive = DATA / name / "**" / "*.csv"
    if any(p.parent.name.startswith("year=") for p in Path(str(hive)).glob("*/*/*/*.csv")):
        # hive layout year=*/month=*/day=*: the three-level glob matches exactly
        return sql_string(_glob_pattern(hive))
    plain = DATA / name / "*.csv"
    if next(plain.glob("*.csv"), None):
        return sql_string(_glob_pattern(DATA / name / "*.csv"))
    return sql_string(_glob_pattern(hive))


def partition_expr() -> tuple[str, str, str]:
    filename = qident("__source_file")
    year = f"try_cast(regexp_extract({filename}, 'year=([0-9]{{4}})', 1) AS INTEGER)"
    month = f"try_cast(regexp_extract({filename}, 'month=([0-9]{{2}})', 1) AS INTEGER)"
    day = f"try_cast(regexp_extract({filename}, 'day=([0-9]{{2}})', 1) AS INTEGER)"
    return year, month, day


def fetch_one(con, query: str):
    return con.execute(query).fetchone()


def scalar(con, query: str):
    return fetch_one(con, query)[0]


def count_where(con, dataset: str, predicate: str) -> int:
    return scalar(con, f"SELECT count(*) FROM {qident(dataset)} WHERE {predicate}")


# Hive partition keys added as VIRTUAL columns by `hive_partitioning=true`. They are
# NOT physical CSV fields, so they must never appear in the read_csv `columns={...}`
# map (Round 2 real-data audit failure: 22 physical columns + 3 virtual columns were
# supplied as 25 physical columns, making DuckDB expect 25 fields per row).
HIVE_PARTITION_KEYS = ("day", "month", "year")


def physical_column_names(sniffed_columns: list[str], hive_partitioning: bool) -> list[str]:
    """Physical CSV columns only: drop Hive-derived virtual columns and path artifacts.

    The sniffed schema (read_csv with hive_partitioning=true) exposes the physical
    header columns PLUS the virtual `day`/`month`/`year` partition columns. Only the
    physical ones belong in the explicit `columns={...}` map; the virtual ones stay
    query-visible because hive_partitioning remains enabled.
    """
    if not hive_partitioning:
        return list(sniffed_columns)
    return [c for c in sniffed_columns if c not in HIVE_PARTITION_KEYS and "=" not in c]


def make_cache(con, hive_partitioning: bool | None = None) -> dict[str, int]:
    """Single-pass materialization of scoped columns.

    hive_partitioning is auto-detected once per run (fix #10: no repeated full scans);
    tests may pass an explicit value for synthetic fixtures without year=/month=/day=
    partitions.
    """
    if hive_partitioning is None:
        hive_partitioning = any((DATA / name).is_dir() and next((DATA / name).rglob("year=*"), None) is not None
                                for name in DATASETS)
    row_counts = {}
    for index, (name, columns) in enumerate(DATASETS.items(), 1):
        print(f"[{index}/{len(DATASETS)}] materializing {name}", flush=True)
        source = table_source(name)
        con.execute(f"DROP TABLE IF EXISTS {qident(name)}")
        sniff_cols = [r[0] for r in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv({source}, header=true, union_by_name=true, sample_size=-1, hive_partitioning={hive_partitioning}))").fetchall()]
        # fix (Round 2 audit): `columns={...}` describes PHYSICAL CSV fields only.
        # day/month/year are Hive-derived virtual columns and must be excluded here.
        physical_cols = physical_column_names(sniff_cols, hive_partitioning)
        available = [c for c in columns if c in physical_cols]
        missing = [c for c in columns if c not in physical_cols]
        if missing:
            print(f"    note: columns absent from source and materialized as NULL: {missing}", flush=True)
        select_list = ", ".join(qident(c) if c in available else f"NULL AS {qident(c)}" for c in available)
        select_list += (", " + ", ".join(f"NULL AS {qident(c)}" for c in missing)) if missing else ""
        column_map = ", ".join(f"{sql_string(c)}: 'VARCHAR'" for c in physical_cols)
        # Hive-derived virtual columns are selected explicitly so they stay visible in
        # the materialized cache (the projection below is an explicit list, not `*`).
        virtual_cols = [c for c in HIVE_PARTITION_KEYS if c in sniff_cols] if hive_partitioning else []
        select_list += (", " + ", ".join(qident(c) for c in virtual_cols)) if virtual_cols else ""
        con.execute(
            f"CREATE TABLE {qident(name)} AS SELECT {select_list}, filename AS __source_file "
            f"FROM read_csv({source}, header=true, auto_detect=false, delim=',', quote='\"', escape='\"', columns={{{column_map}}}, union_by_name=true, hive_partitioning={hive_partitioning}, strict_mode=true)"
        )
        row_counts[name] = scalar(con, f"SELECT count(*) FROM {qident(name)}")
        print(f"    rows={row_counts[name]:,}", flush=True)
    return row_counts


def dataset_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for name, columns in DATASETS.items():
        date_column = EVENT_DATES.get(name)
        if date_column:
            expression = ts_expr(date_column)
            minimum, maximum = fetch_one(con, f"SELECT min({expression}), max({expression}) FROM {qident(name)}")
            malformed = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {nonempty(date_column)} AND {expression} IS NULL")
            status = "EXACT"
        else:
            # customers/products/service_agents legitimately have no scoped event date.
            minimum = maximum = "NOT_APPLICABLE"
            malformed = "NOT_APPLICABLE"
            status = "NOT_APPLICABLE"
        rows.append({"record_id": f"{name}|row_count", "dataset": name, "metric": "row_count", "value": row_counts[name], "unit": "rows", "evidence_status": "EXACT"})
        rows.append({"record_id": f"{name}|minimum_relevant_date", "dataset": name, "metric": "minimum_relevant_date", "value": minimum or "UNKNOWN", "unit": "timestamp", "evidence_status": status})
        rows.append({"record_id": f"{name}|maximum_relevant_date", "dataset": name, "metric": "maximum_relevant_date", "value": maximum or "UNKNOWN", "unit": "timestamp", "evidence_status": status})
        rows.append({"record_id": f"{name}|malformed_relevant_dates", "dataset": name, "metric": "malformed_relevant_dates", "value": malformed, "unit": "rows", "evidence_status": status})
    return rows


def quality_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for name, columns in DATASETS.items():
        total = row_counts[name]
        for column in columns:
            field = qident(column)
            null_count, empty_count = fetch_one(con, f"SELECT count(*) FILTER (WHERE {field} IS NULL), count(*) FILTER (WHERE {field} IS NOT NULL AND trim(cast({field} AS VARCHAR)) = '') FROM {qident(name)}")
            for metric, value in (("null_count", null_count), ("empty_count", empty_count)):
                rows.append({"record_id": f"{name}|{column}|{metric}", "dataset": name, "field": column, "metric": metric, "value": value, "percentage": round(value / total * 100, 6) if total else 0, "evidence_status": "EXACT"})
    return rows


def key_profile(con, row_counts: dict[str, int]) -> list[dict]:
    """Executed exactly once per run; results cached and reused (fix #10)."""
    rows = []
    for name, key in PRIMARY_KEYS.items():
        field = qident(key)
        total = row_counts[name]
        nonnull = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {nonempty(key)}")
        distinct = scalar(con, f"SELECT count(DISTINCT trim(cast({field} AS VARCHAR))) FROM {qident(name)} WHERE {nonempty(key)}")
        duplicate_rows = nonnull - distinct
        rows.append({"record_id": f"{name}|candidate_pk|{key}", "dataset": name, "candidate_primary_key": key, "total_rows": total, "non_null_rows": nonnull, "distinct_values": distinct, "duplicate_rows": duplicate_rows, "duplicate_key_rate_pct": round(duplicate_rows / total * 100, 6) if total else 0, "evidence_status": "EXACT"})
    return rows


def join_profile(con, row_counts: dict[str, int]) -> list[dict]:
    rows = []
    for child, child_key, parent, parent_key in JOIN_SPECS:
        child_field, parent_field = qident(child_key), qident(parent_key)
        child_nonnull, child_distinct = fetch_one(con, f"SELECT count(*) FILTER (WHERE {nonempty(child_key)}), count(DISTINCT trim(cast({child_field} AS VARCHAR))) FROM {qident(child)} WHERE {nonempty(child_key)}")
        matched = scalar(con, f"SELECT count(*) FROM (SELECT DISTINCT trim(cast({child_field} AS VARCHAR)) AS join_key FROM {qident(child)} WHERE {nonempty(child_key)}) c INNER JOIN (SELECT DISTINCT trim(cast({parent_field} AS VARCHAR)) AS join_key FROM {qident(parent)} WHERE {nonempty(parent_key)}) p USING (join_key)")
        parent_total, parent_nonnull, parent_distinct = fetch_one(con, f"SELECT count(*), count(*) FILTER (WHERE {nonempty(parent_key)}), count(DISTINCT trim(cast({parent_field} AS VARCHAR))) FROM {qident(parent)}")
        unmatched = child_distinct - matched
        rows.append({
            "record_id": f"{child}.{child_key}->{parent}.{parent_key}",
            "child_dataset": child, "child_key": child_key, "parent_dataset": parent, "parent_key": parent_key,
            "child_row_count": row_counts[child],
            "non_null_child_keys": child_nonnull,
            "distinct_child_keys": child_distinct,
            "matched_distinct_keys": matched,
            "unmatched_distinct_keys": unmatched,
            "match_rate_pct": round(matched / child_distinct * 100, 6) if child_distinct else "UNKNOWN_NO_NONNULL_KEYS",
            "orphan_rate_pct": round(unmatched / child_distinct * 100, 6) if child_distinct else "UNKNOWN_NO_NONNULL_KEYS",
            "parent_duplicate_key_rate_pct": round((parent_nonnull - parent_distinct) / parent_total * 100, 6) if parent_total else 0,
            "status": "OBSERVED RELATIONSHIP" if child_nonnull else "NO_NONNULL_CHILD_KEYS",
        })
    return rows


def temporal_profile(con, row_counts: dict[str, int], runtime_date: date) -> list[dict]:
    """Granularity-aware event/process temporal analysis (fixes #1, #2, #6)."""
    rows = []
    runtime_ts = f"TIMESTAMP {sql_string(str(runtime_date) + ' 23:59:59')}"
    partition_year, partition_month, partition_day = partition_expr()
    for name, event_column in EVENT_DATES.items():
        timestamp = ts_expr(event_column)
        distinct_dates, future, malformed = fetch_one(con, f"SELECT count(DISTINCT cast({timestamp} AS DATE)), count(*) FILTER (WHERE {timestamp} > {runtime_ts}), count(*) FILTER (WHERE {nonempty(event_column)} AND {timestamp} IS NULL) FROM {qident(name)}")
        has_partitions = bool(partition_year and scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {partition_year} IS NOT NULL LIMIT 1"))
        partition_dates = scalar(con, f"SELECT count(DISTINCT ({partition_year}, {partition_month}, {partition_day})) FROM {qident(name)} WHERE {partition_year} IS NOT NULL") if has_partitions else "NOT_APPLICABLE"
        partition_min, partition_max = fetch_one(con, f"SELECT min(make_date({partition_year}, {partition_month}, coalesce({partition_day}, 1))), max(make_date({partition_year}, {partition_month}, coalesce({partition_day}, 1))) FROM {qident(name)} WHERE {partition_year} IS NOT NULL AND {partition_month} IS NOT NULL")
        missing_partition_dates = scalar(con, f"SELECT count(*) FROM generate_series(cast({sql_string(str(partition_min))} AS DATE), cast({sql_string(str(partition_max))} AS DATE), INTERVAL 1 DAY) AS series_day WHERE series_day.generate_series::DATE NOT IN (SELECT DISTINCT make_date({partition_year}, {partition_month}, coalesce({partition_day}, 1)) FROM {qident(name)} WHERE {partition_year} IS NOT NULL AND {partition_month} IS NOT NULL)") if has_partitions and partition_min and partition_max else "NOT_APPLICABLE"
        if has_partitions:
            aligned = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {timestamp} IS NOT NULL AND {partition_year} = year(cast({timestamp} AS DATE)) AND {partition_month} = month(cast({timestamp} AS DATE)) AND ({partition_day} IS NULL OR {partition_day} = day(cast({timestamp} AS DATE)))")
            mismatched = scalar(con, f"SELECT count(*) FROM {qident(name)} WHERE {timestamp} IS NOT NULL AND ({partition_year} IS NULL OR {partition_year} <> year(cast({timestamp} AS DATE)) OR {partition_month} <> month(cast({timestamp} AS DATE)) OR ({partition_day} IS NOT NULL AND {partition_day} <> day(cast({timestamp} AS DATE))))")
        else:
            aligned = mismatched = "NOT_APPLICABLE"
        minimum, maximum = fetch_one(con, f"SELECT min({timestamp}), max({timestamp}) FROM {qident(name)}")

        def add(metric, value, unit="rows", note=None, status="EXACT"):
            row = {"record_id": f"{name}|{metric}", "dataset": name, "metric": metric, "value": value, "unit": unit, "evidence_status": status}
            if note:
                row["note"] = note
            rows.append(row)

        add("event_min", minimum or "UNKNOWN", unit="timestamp")
        add("event_max", maximum or "UNKNOWN", unit="timestamp")
        add("distinct_event_dates", distinct_dates)
        add("partition_dates_represented", partition_dates)
        add("missing_partition_dates", missing_partition_dates, note="Gaps between minimum and maximum represented partition dates")
        add("future_timestamps_vs_runtime_date", future, note=f"Compared against runtime-derived evaluation date {runtime_date}")
        add("malformed_timestamps", malformed)
        add("partition_aligned_rows", aligned)
        add("partition_mismatched_rows", mismatched)
        if has_partitions:
            add("partition_mismatch_rate_pct", round(mismatched / (aligned + mismatched) * 100, 6) if aligned + mismatched else 0, unit="percent")
        else:
            add("partition_mismatch_rate_pct", "NOT_APPLICABLE", unit="percent", status="NOT_APPLICABLE", note="Dataset is not hive-partitioned by event date")
        if "process_date" not in DATASETS[name]:
            for metric in ("temporal_comparison_granularity", "event_before_process_count", "process_before_event_count", "same_calendar_day_count", "temporal_comparison_unknown_count", "event_process_lag_min", "event_process_lag_max", "event_process_lag_median", "true_temporal_ordering_risk"):
                add(metric, "NOT_APPLICABLE", status="NOT_APPLICABLE", note="Dataset has no process_date column in scope")
            continue
        process = "process_date"
        p_ts = ts_expr(process)
        case = granularity_case(process, event_column)
        # Two single-pass tallies: comparison granularity, then ordering outcome.
        both_ts, cal_day, unknown_cnt = fetch_one(con, (
            f"SELECT count(*) FILTER (WHERE g = 'BOTH_TIMESTAMP'), "
            f"count(*) FILTER (WHERE g = 'CALENDAR_DAY'), "
            f"count(*) FILTER (WHERE g = 'UNKNOWN') "
            f"FROM (SELECT {case} AS g FROM {qident(name)}) sub"
        ))
        ev_before, proc_before, same_day = fetch_one(con, (
            f"SELECT count(*) FILTER (WHERE cls = 'EVENT_BEFORE_PROCESS'), "
            f"count(*) FILTER (WHERE cls = 'PROCESS_BEFORE_EVENT'), "
            f"count(*) FILTER (WHERE cls = 'SAME_CALENDAR_DAY') "
            f"FROM (SELECT {granularity_class_expr(process, event_column)} AS cls FROM {qident(name)}) sub"
        ))
        # Lag statistics: seconds between event and process, computed PER GRANULARITY.
        # For CALENDAR_DAY comparisons the lag is measured in whole days converted to
        # seconds so midnight-padding never creates fake negative lags.
        lag_expr = (
            f"CASE WHEN {case} = 'BOTH_TIMESTAMP' THEN date_diff('second', {timestamp}, {p_ts}) "
            f"ELSE date_diff('day', cast({timestamp} AS DATE), cast({p_ts} AS DATE)) * 86400 END"
        )
        lag_min, lag_max, lag_median = fetch_one(con, (
            f"SELECT min(lag), max(lag), median(lag) FROM (SELECT {lag_expr} AS lag FROM {qident(name)} "
            f"WHERE {p_ts} IS NOT NULL AND {timestamp} IS NOT NULL) sub"
        ))
        add("temporal_comparison_granularity", "AUTO: BOTH_TIMESTAMP when both fields carry time-of-day, else CALENDAR_DAY", unit="definition", note=f"both-timestamp rows={both_ts}; calendar-day rows={cal_day}")
        add("event_before_process_count", ev_before, note="Process strictly after event at the applicable comparison granularity")
        add("process_before_event_count", proc_before, note="Actual negative ordering (process strictly before event); granularity-aware")
        add("same_calendar_day_count", same_day, note="Same calendar day: NOT classified as leakage regardless of time-of-day")
        add("temporal_comparison_unknown_count", unknown_cnt, note="Missing or unparseable process/event value")
        add("event_process_lag_min", lag_min if lag_min is not None else "UNKNOWN", unit="seconds", note="Day-granularity lags expressed as whole days x 86400")
        add("event_process_lag_max", lag_max if lag_max is not None else "UNKNOWN", unit="seconds")
        add("event_process_lag_median", lag_median if lag_median is not None else "UNKNOWN", unit="seconds")
        add("true_temporal_ordering_risk", "PRESENT" if proc_before else "NOT_OBSERVED", status="DERIVED", note="Based ONLY on granularity-aware process-before-event counts; repeated customers are NOT part of this metric")
    return rows


def granularity_class_expr(process_col: str, event_col: str) -> str:
    """Full ordering-class CASE combining granularity detection with ordering outcome.

    Classes: UNKNOWN | BOTH_TIMESTAMP (same instant, both timed) |
             EVENT_BEFORE_PROCESS | PROCESS_BEFORE_EVENT | SAME_CALENDAR_DAY
    NOTE: BOTH_TIMESTAMP is emitted here only for the equal-instant case so the
    granularity tally can be joined with the ordering tally in one scan.
    """
    p_ts, e_ts = ts_expr(process_col), ts_expr(event_col)
    both_timed = f"({has_time_expr(process_col)} AND {has_time_expr(event_col)})"
    return (
        f"CASE WHEN {p_ts} IS NULL OR {e_ts} IS NULL THEN 'UNKNOWN' "
        f"WHEN {both_timed} AND {p_ts} = {e_ts} THEN 'SAME_CALENDAR_DAY' "
        f"WHEN {both_timed} AND {p_ts} < {e_ts} THEN 'PROCESS_BEFORE_EVENT' "
        f"WHEN {both_timed} AND {p_ts} > {e_ts} THEN 'EVENT_BEFORE_PROCESS' "
        f"WHEN cast({p_ts} AS DATE) < cast({e_ts} AS DATE) THEN 'PROCESS_BEFORE_EVENT' "
        f"WHEN cast({p_ts} AS DATE) > cast({e_ts} AS DATE) THEN 'EVENT_BEFORE_PROCESS' "
        f"ELSE 'SAME_CALENDAR_DAY' END"
    )


def distribution(con, dataset: str, column: str, family: str) -> list[dict]:
    field = qident(column)
    result = con.execute(f"SELECT coalesce(nullif(trim(cast({field} AS VARCHAR)), ''), 'UNKNOWN') AS value, count(*) AS rows FROM {qident(dataset)} GROUP BY 1 ORDER BY rows DESC, value").fetchall()
    total = sum(row[1] for row in result)
    return [{"dataset": dataset, "field": column, "category": clean(value), "rows": count, "percentage": round(count / total * 100, 6) if total else 0, "distribution_family": family, "evidence_status": "OBSERVED FACT"} for value, count in result]


def build_category_mapping(interaction_distributions: list[dict]) -> list[dict]:
    """Evidence-based Workflow A category mapping artifact (fix #3).

    Pure function over the observed distributions so it can be unit-tested without
    touching raw data. Only categories actually observed in the data receive rows;
    nothing is invented.
    """
    totals = sum(item["rows"] for item in interaction_distributions if item["field"] in INTENT_FIELDS) // 2 or 1
    rows = []
    seen_pairs = set()
    for item in interaction_distributions:
        field, category = item["field"], item["category"]
        if field not in INTENT_FIELDS:
            continue
        pair = (field, category)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        if category in CATEGORY_MAPPING_POLICY:
            intent, confidence = CATEGORY_MAPPING_POLICY[category]
            method, status = "observed_taxonomy_policy", "MAPPED"
        elif category == "UNKNOWN":
            intent, method, confidence, status = "unknown", "policy_no_evidence", "NONE", "UNMAPPED_NO_EVIDENCE"
        else:
            intent, method, confidence, status = "unknown", "policy_no_evidence", "NONE", "UNMAPPED_NO_EVIDENCE"
        rows.append({
            "observed_field": field,
            "observed_category": category,
            "candidate_intent": intent,
            "mapping_method": method,
            "mapping_confidence": confidence,
            "row_count": item["rows"],
            "percentage": round(item["rows"] / totals * 100, 6),
            "status": status,
        })
    # Explicit no-evidence records for granular intents (never silently omitted).
    for intent in NO_EVIDENCE_INTENTS:
        rows.append({
            "observed_field": "contact_reason|reason_category",
            "observed_category": "NO_EVIDENCE_IN_OBSERVED_TAXONOMY",
            "candidate_intent": intent,
            "mapping_method": "none_available",
            "mapping_confidence": "NONE",
            "row_count": 0,
            "percentage": 0.0,
            "status": "NO_EVIDENCE_IN_OBSERVED_TAXONOMY",
        })
    rows.append({
        "observed_field": "interaction_type",
        "observed_category": "ALL (channel/type metadata: Inbound Call, Outbound Call, Chat, Email, Video)",
        "candidate_intent": "unknown",
        "mapping_method": "excluded_field",
        "mapping_confidence": "NONE",
        "row_count": 0,
        "percentage": 0.0,
        "status": "FIELD_NOT_SUITABLE_FOR_INTENT_MAPPING",
    })
    rows.sort(key=lambda r: (r["observed_field"], -r["row_count"], r["observed_category"]))
    return rows


def workflow_a(con, row_counts: dict[str, int], mapping_rows: list[dict]) -> list[dict]:
    """Workflow A evidence driven by the category-mapping artifact (fix #3).

    Note: distribution rows are NOT duplicated here (fix #12); the authoritative
    distributions live in the distribution section of this same artifact, and
    `category_mapping_file` points to the mapping provenance.
    """
    def row(metric, value, evidence_type="OBSERVED FACT", status="EXACT", note=None, definition=None):
        item = {"workflow": "A", "metric": metric, "value": value, "evidence_type": evidence_type, "evidence_status": status}
        if definition:
            item["definition"] = definition
        if note:
            item["note"] = note
        return item

    rows = [row("total_transaction_records", row_counts["transactions"])]
    rows.append(row("total_call_center_interactions", row_counts["call_center_interactions"]))
    rows.append(row(
        "failed_or_rejected_transaction_volume",
        count_where(con, "transactions", "lower(coalesce(cast(transaction_status AS VARCHAR), '')) IN ('failed', 'failure', 'rejected', 'declined', 'cancelled', 'canceled')"),
        "DERIVED METRIC",
        definition="transactions where transaction_status matches an explicit failure/rejection enum value",
        note="Validated against the observed transaction_status distribution (Declined/Reversed enums exist); this measures STATUS-ENUM coverage, not an assumption",
    ))
    rows.append(row("fraud_fields_existing_evidence_only",
                    count_where(con, "transactions", f"{nonempty('is_fraud')} OR {nonempty('fraud_score')}"),
                    "OBSERVED FACT", note="Not used to adjudicate fraud"))
    mapped = [m for m in mapping_rows if m["status"] == "MAPPED"]
    mapped_categories = sorted({m["observed_category"] for m in mapped})
    covered_rows = sum(m["row_count"] for m in mapped if m["observed_field"] == "contact_reason")
    total_i = row_counts["call_center_interactions"]
    coverage_pct = round(covered_rows / total_i * 100, 6) if total_i else 0
    rows.append(row("category_mapping_file", "workflow_A_category_mapping.csv", "PROVENANCE", "EXACT", note="Authoritative observed-category -> candidate-intent mapping"))
    rows.append(row("mapped_category_count", len(mapped_categories), "DERIVED METRIC", definition="Distinct observed categories with an evidence-backed candidate intent"))
    rows.append(row("mapped_categories", ",".join(mapped_categories) or "NONE", "OBSERVED FACT"))
    rows.append(row("granular_failure_intents_evidence", "NO_EVIDENCE_IN_OBSERVED_TAXONOMY", "INFERENCE", "UNKNOWN", note="failed_transaction / payment_problem / transfer_problem / withdrawal_problem cannot be separated from the observed Spanish taxonomy without additional evidence; this is absence of EVIDENCE, not absence of transactions"))
    rows.append(row("transaction_related_interaction_coverage_lower_bound", coverage_pct, "DERIVED METRIC", definition="% of interactions whose contact_reason maps to a transaction-related candidate intent (MEDIUM/LOW confidence). Lower bound because UNMAPPED categories may still be transaction-related.", note="Non-zero whenever any category is mapped; NOT gated on the removed English regex"))
    predicate = "(" + " OR ".join(f"coalesce(nullif(trim(cast({qident(f)} AS VARCHAR)), ''), 'UNKNOWN') IN ({', '.join(sql_string(c) for c in mapped_categories)})" for f in INTENT_FIELDS) + ")" if mapped_categories else "1 = 0"
    relevant = count_where(con, "call_center_interactions", predicate)
    rows.append(row("transaction_related_customer_service_interactions", relevant, "DERIVED METRIC", definition="Interactions in mapped categories (contact_reason OR reason_category)", note="Includes transaction_inquiry (MEDIUM) and dispute (LOW) buckets; requires manual validation before training use"))
    rows.append(row("relevant_interaction_percentage", round(relevant / total_i * 100, 6) if total_i else 0, "DERIVED METRIC"))
    for metric, column in (("resolved_rate", "was_resolved"), ("escalation_rate", "was_escalated"), ("follow_up_rate", "requires_followup"), ("transcript_availability_rate", "has_transcript")):
        numerator = count_where(con, "call_center_interactions", TRUTHY_SQL.format(f=column) + f" AND {predicate}") if relevant else 0
        rows.append(row(metric, round(numerator / relevant * 100, 6) if relevant else "UNKNOWN_NO_RELEVANT_INTERACTIONS", "DERIVED METRIC", status="EXACT" if relevant else "UNKNOWN", definition=f"% of mapped-category interactions with {column} truthy"))
    return rows


def workflow_b(con, row_counts: dict[str, int], joins: list[dict]) -> list[dict]:
    """Separated Workflow B diagnostics (fix #4). Each linkage dimension stands alone."""
    def row(metric, value, evidence_type="DERIVED METRIC", status="EXACT", definition=None, note=None):
        item = {"workflow": "B", "metric": metric, "value": value, "evidence_type": evidence_type, "evidence_status": status}
        if definition:
            item["definition"] = definition
        if note:
            item["note"] = note
        return item

    total = row_counts["complaints"]
    rows = [row("complaint_total", total, "OBSERVED FACT", definition="Number of complaint rows in the cache")]
    join_by_key = {item["child_key"]: item for item in joins if item["child_dataset"] == "complaints"}
    customer_j = join_by_key["customer_id"]
    product_j = join_by_key["affected_product_id"]
    origin_j = join_by_key["origin_interaction_id"]
    agent_j = join_by_key["assigned_agent_id"]

    rows.append(row("complaint_customer_link_rate",
                    round(customer_j["non_null_child_keys"] / total * 100, 6) if total else 0,
                    definition="Complaint rows with a non-empty customer_id / complaint rows (intake-level customer linkage)",
                    note=f"distinct-key match rate vs customers: {customer_j['match_rate_pct']}"))
    rows.append(row("complaint_product_link_rate",
                    round(product_j["non_null_child_keys"] / total * 100, 6) if total else 0,
                    definition="Complaint rows with a non-empty affected_product_id / complaint rows",
                    note=f"distinct-key match rate vs products: {product_j['match_rate_pct']}"))

    origin_nonnull = origin_j["non_null_child_keys"]
    rows.append(row("complaint_origin_interaction_nonnull_rate",
                    round(origin_nonnull / total * 100, 6) if total else 0,
                    definition="Complaint rows with a non-empty origin_interaction_id / complaint rows (FK populated rate)",
                    note="Interaction-context linkage AVAILABILITY, independent of whether the FK resolves"))
    if origin_nonnull == 0:
        rows.append(row("complaint_origin_interaction_match_rate", "UNKNOWN_NOT_APPLICABLE",
                        status="UNKNOWN",
                        definition="Matched non-null origin_interaction_id keys / non-null origin_interaction_id keys",
                        note="Zero non-null FK keys: match rate is undefined, deliberately NOT reported as 0"))
        rows.append(row("complaint_interaction_context_linkage", "MISSING_FOREIGN_KEY",
                        status="UNKNOWN", evidence_type="INFERENCE",
                        definition="Overall interaction-context linkage state",
                        note="FK column exists but is entirely unpopulated; distinct from 'present but unmatched' and from 'unassigned'"))
    else:
        rows.append(row("complaint_origin_interaction_match_rate", origin_j["match_rate_pct"],
                        definition="Matched non-null origin_interaction_id keys / non-null origin_interaction_id keys",
                        note="Measured only on non-null keys"))
        rows.append(row("complaint_interaction_context_linkage",
                        "OBSERVED" if origin_j["matched_distinct_keys"] else "FK_PRESENT_UNMATCHED",
                        status="EXACT", evidence_type="INFERENCE",
                        definition="Overall interaction-context linkage state"))

    assigned = count_where(con, "complaints", nonempty("assigned_agent_id"))
    rows.append(row("complaint_agent_assignment_rate",
                    round(assigned / total * 100, 6) if total else 0,
                    definition="Complaint rows with a non-empty assigned_agent_id / complaint rows (assignment completeness, NOT referential validity)",
                    note=f"Referential validity of assigned ids vs service_agents: {agent_j['match_rate_pct']} distinct-key match rate"))

    res_date = count_where(con, "complaints", nonempty("resolution_date"))
    close_date = count_where(con, "complaints", nonempty("closing_date"))
    resolution = count_where(con, "complaints", nonempty("resolution"))
    satisfaction = count_where(con, "complaints", nonempty("resolution_satisfaction"))
    rows.append(row("complaint_resolution_date_rate", round(res_date / total * 100, 6) if total else 0, definition="Complaint rows with non-empty resolution_date / complaint rows"))
    rows.append(row("complaint_closing_date_rate", round(close_date / total * 100, 6) if total else 0, definition="Complaint rows with non-empty closing_date / complaint rows"))
    rows.append(row("complaint_resolution_rate", round(resolution / total * 100, 6) if total else 0, definition="Complaint rows with non-empty free-text resolution / complaint rows", note="Outcome TEXT availability, not adjudicated correctness"))
    rows.append(row("complaint_resolution_satisfaction_rate", round(satisfaction / total * 100, 6) if total else 0, definition="Complaint rows with non-empty resolution_satisfaction / complaint rows (resolution-quality evaluation input)"))

    sla_known = count_where(con, "complaints", nonempty("sla_breached"))
    breached = count_where(con, "complaints", TRUTHY_SQL.format(f="sla_breached"))
    rows.append(row("complaint_sla_breach_rate",
                    round(breached / sla_known * 100, 6) if sla_known else "UNKNOWN_NO_SLA_VALUES",
                    status="EXACT" if sla_known else "UNKNOWN",
                    definition="Truthy sla_breached / complaint rows WITH a non-empty sla_breached value (denominator restricted to known SLA states)",
                    note=f"sla_breached populated on {sla_known:,} of {total:,} rows"))

    # Feasibility criteria kept SEPARATE from measurements, using PASS/PARTIAL/FAIL/UNKNOWN.
    rows.append(row("complaint_intake_feasibility", "PASS" if total else "FAIL", evidence_type="INFERENCE", definition="Complaint volume exists for intake", note="Feasibility criterion, separate from linkage dimensions"))
    cust_frac = customer_j["non_null_child_keys"] / total if total else 0
    rows.append(row("complaint_customer_linkage_feasibility", "PASS" if cust_frac >= 0.99 else "PARTIAL" if cust_frac > 0 else "FAIL", evidence_type="INFERENCE", definition="Threshold: >=99% non-null customer_id"))
    prod_frac = product_j["non_null_child_keys"] / total if total else 0
    rows.append(row("complaint_product_linkage_feasibility", "PARTIAL" if prod_frac > 0 else "UNKNOWN", evidence_type="INFERENCE", definition="Reported from measured product link rate; threshold not adjudicated in this pass"))
    rows.append(row("complaint_interaction_context_feasibility", "UNKNOWN_MISSING_FK" if origin_nonnull == 0 else "PARTIAL", evidence_type="INFERENCE", status="UNKNOWN" if origin_nonnull == 0 else "EXACT", definition="Origin-interaction context linkage state"))
    rows.append(row("complaint_agent_linkage_feasibility", "PARTIAL" if assigned else "UNKNOWN", evidence_type="INFERENCE", definition="Reported from measured assignment rate; threshold not adjudicated in this pass"))
    rows.append(row("complaint_resolution_outcome_availability", "PARTIAL" if resolution else "UNKNOWN", evidence_type="INFERENCE", definition="Resolution outcome text/date availability measured above"))
    rows.append(row("complaint_resolution_quality_evaluation_feasibility", "PARTIAL" if satisfaction else "UNKNOWN", evidence_type="INFERENCE", definition="Depends on resolution_satisfaction availability; observed values are proxies, not adjudicated quality"))
    return rows


def evaluation(con, row_counts: dict[str, int], keys_cached: list[dict], runtime_date: date) -> list[dict]:
    """Evaluation readiness separated into distinct concepts (fixes #2, #7)."""
    def row(workflow, metric, value, evidence_type="DERIVED METRIC", status="EXACT", definition=None, note=None):
        item = {"record_id": f"{workflow}|{metric}", "workflow": workflow, "metric": metric, "value": value, "evidence_type": evidence_type, "evidence_status": status}
        if definition:
            item["definition"] = definition
        if note:
            item["note"] = note
        return item

    rows = []
    specs = [("A", "call_center_interactions", "interaction_date", "customer_id", "was_resolved"),
             ("B", "complaints", "creation_date", "customer_id", "resolution")]
    for workflow, dataset, date_column, customer_column, outcome_column in specs:
        total = row_counts[dataset]
        timestamp = ts_expr(date_column)
        dated = count_where(con, dataset, f"{timestamp} IS NOT NULL")
        customers_q = (f"SELECT trim(cast({qident(customer_column)} AS VARCHAR)) AS cid, count(*) AS n, "
                       f"min(cast({timestamp} AS DATE)) AS first_day, max(cast({timestamp} AS DATE)) AS last_day "
                       f"FROM {qident(dataset)} WHERE {nonempty(customer_column)} AND {timestamp} IS NOT NULL GROUP BY 1")
        uniq, repeated_rows, multi_customers = fetch_one(con, f"SELECT count(*), coalesce(sum(n - 1) FILTER (WHERE n > 1), 0), count(*) FILTER (WHERE n > 1) FROM ({customers_q}) sub")
        # Granularity-aware ordering diagnostics (single scan).
        cls_expr = granularity_class_expr("process_date", date_column)
        proc_before, same_day = fetch_one(con, f"SELECT count(*) FILTER (WHERE cls = 'PROCESS_BEFORE_EVENT'), count(*) FILTER (WHERE cls = 'SAME_CALENDAR_DAY') FROM (SELECT {cls_expr} AS cls FROM {qident(dataset)}) sub")
        # Cross-split overlap simulation: tertiles by event calendar day; a customer
        # spanning two splits contributes overlap. This measures LEAKAGE RISK from
        # entity repetition ACROSS splits — distinct from repeat structure itself.
        overlap = scalar(con, f"""
            WITH per_customer AS ({customers_q}),
            bounds AS (SELECT min(first_day) AS dmin, max(last_day) AS dmax FROM per_customer),
            cuts AS (SELECT b.dmin,
                          b.dmin + cast(floor(date_diff('day', b.dmin, b.dmax) / 3.0) AS INTEGER) AS c1,
                          b.dmin + cast(floor(2 * date_diff('day', b.dmin, b.dmax) / 3.0) AS INTEGER) AS c2,
                          b.dmax
                      FROM bounds b),
            assigned AS (SELECT pc.cid,
                              CASE WHEN pc.last_day <= c.c1 THEN 'TRAIN_ONLY'
                                   WHEN pc.first_day > c.c2 THEN 'HOLDOUT_ONLY'
                                   ELSE 'SPANS' END AS span
                          FROM per_customer pc, cuts c)
            SELECT count(*) FILTER (WHERE span = 'SPANS') FROM assigned""")
        outcome_avail = count_where(con, dataset, nonempty(outcome_column))
        survey_cov: object = "UNKNOWN"
        survey_timing_bad: object = "NOT_APPLICABLE"
        survey_timing_known: object = "NOT_APPLICABLE"
        if workflow == "A":
            survey_cov = scalar(con, f"""SELECT count(DISTINCT trim(cast(i.interaction_id AS VARCHAR)))
                FROM call_center_interactions i INNER JOIN satisfaction_surveys s
                  ON trim(cast(i.interaction_id AS VARCHAR)) = trim(cast(s.interaction_id AS VARCHAR))
                WHERE i.interaction_id IS NOT NULL AND trim(cast(i.interaction_id AS VARCHAR)) <> ''
                  AND {ts_expr('i.interaction_date')} IS NOT NULL""")
            timing = fetch_one(con, f"""SELECT count(*) FILTER (WHERE su.ts IS NOT NULL AND i.ts IS NOT NULL),
                                       count(*) FILTER (WHERE su.ts IS NOT NULL AND i.ts IS NOT NULL
                                                        AND cast(su.ts AS DATE) < cast(i.ts AS DATE))
                FROM (SELECT trim(cast(interaction_id AS VARCHAR)) AS iid, {ts_expr('survey_date')} AS ts
                      FROM satisfaction_surveys
                      WHERE interaction_id IS NOT NULL AND trim(cast(interaction_id AS VARCHAR)) <> '') su
                INNER JOIN (SELECT trim(cast(interaction_id AS VARCHAR)) AS iid, {ts_expr('interaction_date')} AS ts
                            FROM call_center_interactions) i ON su.iid = i.iid""")
            survey_timing_known, survey_timing_bad = timing
        else:
            origin_nonnull = count_where(con, "complaints", nonempty("origin_interaction_id"))
            survey_cov = 0 if origin_nonnull == 0 else "UNKNOWN"
        dup_pk = next(item["duplicate_rows"] for item in keys_cached if item["dataset"] == dataset)
        rows.extend([
            row(workflow, "scale.total_relevant_interactions_or_cases", total, "OBSERVED FACT", definition="Rows in scope for this workflow's primary entity"),
            row(workflow, "scale.duplicate_primary_key_rows", dup_pk, definition="Repeated non-empty primary-key values (data-integrity check, reused from the single key-profile pass)"),
            row(workflow, "unique_customers", uniq, definition="Distinct non-empty customer ids with a parseable event date"),
            # --- concept 1: repeat-entity STRUCTURE (explicitly NOT leakage) ---
            row(workflow, "repeat_customer_structure.repeated_customer_rows", repeated_rows, definition="Extra rows beyond the first for customers with multiple interactions", note="STRUCTURAL property; explicitly NOT leakage"),
            row(workflow, "repeat_customer_structure.customers_with_multiple_interactions", multi_customers, definition="Customers appearing more than once", note="STRUCTURAL property; explicitly NOT leakage"),
            # --- concept 2: cross-split overlap (leakage RISK under split simulation) ---
            row(workflow, "customer_overlap_across_temporal_splits.customers_spanning_simulated_splits", overlap, definition="Customers whose event-date range spans more than one simulated calendar-day tertile split (train/dev/holdout)", note="Split SIMULATION only; no final split chosen. Overlap is a leakage RISK, not proof of leakage"),
            # --- concept 3: temporal ordering (granularity-aware) ---
            row(workflow, "temporal_ordering_evidence.process_before_event_rows", proc_before, definition="Granularity-aware actual negative ordering (methodology in 05_relevant_profile.csv)"),
            row(workflow, "temporal_ordering_evidence.same_calendar_day_rows", same_day, definition="Same calendar day; excluded from negative-ordering counts by design"),
            row(workflow, "true_temporal_ordering_risk", "PRESENT" if proc_before else "NOT_OBSERVED", "INFERENCE", note="Derived ONLY from granularity-aware ordering; repeat structure and overlap do NOT feed this flag"),
            # --- concept 4: post-outcome feature risk ---
            row(workflow, "post_outcome_feature_risk", "REQUIRES_MANUAL_REVIEW", "INFERENCE", "UNKNOWN", definition="Whether any field is populated only AFTER the outcome occurred (would leak the outcome into features)", note="Cannot be adjudicated from column values alone; requires a field-provenance contract"),
            # --- readiness dimensions (separate, per fix #7) ---
            row(workflow, "outcome_availability_pct", round(outcome_avail / total * 100, 6) if total else 0, definition=f"% rows with non-empty {outcome_column}", note="Proxy availability, not ground-truth labels"),
            row(workflow, "survey_availability", survey_cov, definition="A: distinct interactions joined to surveys. B: surveys reachable via origin_interaction_id (0 when FK unpopulated)"),
            row(workflow, "survey_timing.joined_pairs_with_both_dates", survey_timing_known, definition="Joined interaction-survey pairs with both dates parseable (day-granularity comparison)"),
            row(workflow, "survey_timing.survey_before_interaction_rows", survey_timing_bad, definition="Surveys dated strictly BEFORE their interaction's calendar day"),
            row(workflow, "post_interaction_outcome_timing", "UNKNOWN", "INFERENCE", "UNKNOWN", definition="Timing of outcome-field population relative to the interaction", note="Population timestamps for outcome fields are not in scope; cannot be measured"),
            row(workflow, "leakage_risk", "REQUIRES_MANUAL_REVIEW", "INFERENCE", "UNKNOWN", definition="Composite leakage posture", note="Combines true_temporal_ordering_risk, customer_overlap_across_temporal_splits, and post_outcome_feature_risk; NOT inferred from timestamp existence alone"),
            row(workflow, "time_based_dev_validation_holdout_constructible", "YES" if (dated and uniq) else "UNKNOWN", "INFERENCE", note="Constructibility only: sufficient dated volume exists. NOT a claim that a time-based split is leakage-free — see customer_overlap_across_temporal_splits"),
        ])
    return rows


def render_report(row_counts, profiles, quality, keys, joins, temporal, languages, mapping_rows, a_rows, b_rows, eval_rows, runtime, cache_size, runtime_date):
    def metric_rows(items, label):
        return "\n".join(f"- **{label}:** `{item['metric']}` = `{item['value']}` ({item.get('evidence_type', 'OBSERVED FACT')})" for item in items[:12])
    language_names = [row["category"] for row in languages]
    yes_no = lambda value: "YES" if any(re.search(value, name, re.I) for name in language_names) else "NO"
    mapped = [m for m in mapping_rows if m["status"] == "MAPPED"]
    return f"""# Targeted Evidence Report (v2)

## Scope and status

Evidence-generation pass over exactly eight datasets; `digital_events` and `campaign_sends` were not read. Raw CSVs remain read-only, and transcript free-text columns were excluded from the cache. All terminal statuses below describe **evidence generation**, not workflow feasibility; feasibility criteria use PASS/PARTIAL/FAIL/UNKNOWN explicitly.

- Cache: `{DB_PATH}`
- Cache size: `{cache_size:,}` bytes
- Runtime: `{runtime:.2f}` seconds
- Evaluation runtime date (used for future-timestamp checks): **{runtime_date}** (stored in `analysis_cache_manifest.json`)
- No workflow is ranked or selected, and no ML training dataset was created.

## Dataset scale

{chr(10).join(f"- `{name}`: `{count:,}` rows (EXACT)" for name, count in row_counts.items())}

## Temporal methodology (v2)

Ordering between `process_date` and event dates is granularity-aware: when both fields carry genuine time-of-day, full timestamps are compared; when either side is date-only, comparison happens at calendar-day granularity. Same-calendar-day rows are never counted as process-before-event. Actual negative ordering is reported as `process_before_event_count`. Repeated-customer structure, cross-split overlap risk, temporal ordering risk, and post-outcome feature risk are separate diagnostics — repeated customers are NOT leakage. See `05_relevant_profile.csv` and `10_evaluation_feasibility.csv`.

## Workflow A category mapping (v2)

The previous English-regex matcher was removed: the observed taxonomy is Spanish (`Transaccional`, `Queja`, `Producto`, `Técnico`, `Comercial`, `Retención`) and `interaction_type` holds channel metadata only. The authoritative mapping lives in `workflow_A_category_mapping.csv`. Mapped categories: {', '.join(sorted(set(m['observed_category'] for m in mapped))) or 'NONE'}. Granular failure intents (failed_transaction, payment_problem, transfer_problem, withdrawal_problem) are recorded as `NO_EVIDENCE_IN_OBSERVED_TAXONOMY` — zero mappings there means *no evidence*, **not** zero transaction-related interactions.

## Observed fact

### Data quality and keys

{metric_rows(quality, 'Quality')}

Key uniqueness is reported in `05_relevant_profile.csv`; duplicate rows mean repeated non-empty candidate-key values and are not silently removed. Key profiles are computed once and reused across artifacts.

### Joins

All fifteen requested joins were measured from actual values. A relationship is labeled `OBSERVED RELATIONSHIP`, never `VERIFIED`. When a child FK column has zero non-null keys, match/orphan rates are `UNKNOWN_NO_NONNULL_KEYS`, not 0. Exact rates are in `06_join_quality.csv`.

### Language

Language was read only from `call_transcripts.detected_language` (authoritative `07_language_coverage.csv`).

- Spanish observed: **{yes_no(r'(^|[^a-z])es($|[^a-z])|spanish|español|espanol')}**
- Portuguese observed: **{yes_no(r'(^|[^a-z])pt($|[^a-z])|portugu')}**
- English observed: **{yes_no(r'(^|[^a-z])en($|[^a-z])|english|inglés|ingles')}**
- Other observed values: `{', '.join(name for name in language_names if not re.search(r'(^|[^a-z])(es|pt|en)($|[^a-z])|spanish|español|espanol|portugu|english|inglés|ingles', name, re.I)) or 'NONE'}`

### Workflow A

{metric_rows(a_rows, 'Workflow A')}

Distribution families are stored once each: transaction/interaction distributions in `08_workflow_A_feasibility.csv`, complaint distributions in `09_workflow_B_feasibility.csv`, language in `07_language_coverage.csv` (authority map in the manifest). `is_fraud` is existing evidence only and was not used to adjudicate fraud.

### Workflow B

{metric_rows(b_rows, 'Workflow B')}

Intake feasibility, customer linkage, product linkage, interaction-context linkage (FK populated vs FK matched, reported separately), agent assignment, resolution-outcome availability, and resolution-quality evaluation are distinct metrics. An unpopulated origin FK yields `UNKNOWN_NOT_APPLICABLE` match rate, never a silent 0%.

## Evaluation evidence

{metric_rows(eval_rows, 'Evaluation')}

Time-based split constructibility is an inference about available dated volume only. Leakage posture is decomposed into `true_temporal_ordering_risk`, `customer_overlap_across_temporal_splits`, and `post_outcome_feature_risk`; none of them is inferred from repeated customers or from timestamp existence alone.

## Derived metric, inference, and unknown

- **Derived metric:** percentages and rates are calculated from exact cache counts; definitions are embedded in the CSV `definition`/`note` columns.
- **Inference:** category mappings, feasibility criteria, and risk flags are explicitly marked.
- **Unknown:** post-outcome feature provenance, outcome-population timing, external calendar completeness, and adjudicated labels remain UNKNOWN where unmeasurable.

## Output files

- `05_relevant_profile.csv`: scale, relevant-field quality, key uniqueness, granularity-aware temporal metrics.
- `06_join_quality.csv`: exact requested join measurements (with UNKNOWN handling).
- `07_language_coverage.csv`: authoritative transcript-language distribution.
- `08_workflow_A_feasibility.csv`: Workflow A evidence + authoritative A-side distributions.
- `09_workflow_B_feasibility.csv`: Workflow B evidence + authoritative complaint distributions.
- `10_evaluation_feasibility.csv`: evaluation evidence (decomposed risk concepts).
- `workflow_A_category_mapping.csv`: authoritative observed-category → candidate-intent mapping.
- `analysis_cache_manifest.json`: cache provenance, runtime metadata, and the evaluation runtime date.
"""


def configure_paths(data_root: str | os.PathLike | None = None,
                    reports_dir: str | os.PathLike | None = None,
                    cache_root: str | os.PathLike | None = None):
    """Override module paths (used by the synthetic end-to-end tests only).

    Defaults remain the production paths; raw data is never written.
    """
    global DATA, REPORTS, CACHE_ROOT, DB_PATH
    if data_root is not None:
        DATA = Path(data_root)
    if reports_dir is not None:
        REPORTS = Path(reports_dir)
    if cache_root is not None:
        CACHE_ROOT = Path(cache_root)
    DB_PATH = CACHE_ROOT / "targeted_evidence.duckdb"
    return DATA, REPORTS, CACHE_ROOT, DB_PATH


def main() -> int:
    started = time.perf_counter()
    runtime_date = datetime.now(timezone.utc).date()  # fix #6: runtime-derived, never hard-coded
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (CACHE_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(f"PRAGMA threads={DUCKDB_THREADS}")
    con.execute(f"PRAGMA memory_limit='{DUCKDB_MEMORY_LIMIT}'")
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
        keys = key_profile(con, row_counts)  # executed ONCE; reused by evaluation (fix #10)
        joins = join_profile(con, row_counts)
        temporal = temporal_profile(con, row_counts, runtime_date)
        print("profiling distributions and workflow evidence", flush=True)
        distributions = []
        for family, (dataset, columns) in DISTRIBUTION_FAMILIES.items():
            if dataset == "call_transcripts":
                continue  # language distribution is authoritative in 07 only
            for column in columns:
                distributions.extend(distribution(con, dataset, column, family))
        languages = distribution(con, "call_transcripts", "detected_language", "language")
        interaction_dists = [d for d in distributions if d["dataset"] == "call_center_interactions"]
        mapping_rows = build_category_mapping(interaction_dists)
        a_rows = workflow_a(con, row_counts, mapping_rows)
        b_rows = workflow_b(con, row_counts, joins)
        eval_rows = evaluation(con, row_counts, keys, runtime_date)
        print("writing evidence reports", flush=True)
        runtime = time.perf_counter() - started
        con.close()
        cache_size = DB_PATH.stat().st_size
        complaint_dists = [d for d in distributions if d["dataset"] == "complaints"]
        other_dists = [d for d in distributions if d["dataset"] != "complaints"]
        write_csv(REPORTS / "05_relevant_profile.csv", profiles + quality + keys + temporal)
        write_csv(REPORTS / "06_join_quality.csv", joins)
        write_csv(REPORTS / "07_language_coverage.csv", languages)
        write_csv(REPORTS / "workflow_A_category_mapping.csv", mapping_rows)
        write_csv(REPORTS / "08_workflow_A_feasibility.csv", other_dists + a_rows)
        write_csv(REPORTS / "09_workflow_B_feasibility.csv", complaint_dists + b_rows)
        write_csv(REPORTS / "10_evaluation_feasibility.csv", eval_rows)
        manifest = {
            "script": "targeted_evidence.py",
            "script_version": "v2-methodology-fixes",
            "execution_utc": datetime.now(timezone.utc).isoformat(),
            "evaluation_runtime_date": str(runtime_date),
            "future_timestamp_check": f"event timestamps > {runtime_date} 23:59:59 are flagged as future",
            "data_root": str(DATA),
            "cache_path": str(DB_PATH),
            "cache_size_bytes": cache_size,
            "duckdb_version": duckdb.__version__,
            "duckdb_threads": DUCKDB_THREADS,
            "duckdb_memory_limit": DUCKDB_MEMORY_LIMIT,
            "datasets_processed": list(DATASETS),
            "excluded_datasets": ["digital_events", "campaign_sends"],
            "row_counts": row_counts,
            "rows_are": "EXACT",
            "raw_files_read_only": True,
            "transcript_text_materialized": False,
            "temporal_methodology": "granularity-aware: BOTH_TIMESTAMP comparison only when both fields carry time-of-day; otherwise CALENDAR_DAY; same-day never counted as process-before-event",
            "category_mapping_artifact": "workflow_A_category_mapping.csv",
            "distribution_authority": {
                "workflow_A_transactions": "08_workflow_A_feasibility.csv",
                "workflow_A_interactions": "08_workflow_A_feasibility.csv",
                "workflow_B_complaints": "09_workflow_B_feasibility.csv",
                "language": "07_language_coverage.csv",
            },
            "runtime_seconds": round(runtime, 3),
            "warnings": [
                "Partition gaps are exact only within the observed minimum-to-maximum date span; external calendar completeness remains UNKNOWN.",
                "Outcome fields and language values are observed fields, not independently adjudicated labels.",
                "Category-to-intent mappings are policy-labeled inferences requiring manual validation; NO_EVIDENCE_IN_OBSERVED_TAXONOMY means absence of evidence, not absence of transactions.",
                "Cross-split overlap figures come from a calendar-day tertile SIMULATION; no final train/dev/holdout split was chosen.",
            ],
            "errors": [],
        }
        (REPORTS / "analysis_cache_manifest.json").write_text(json.dumps(manifest, indent=2, default=json_default), encoding="utf-8")
        report = render_report(row_counts, profiles, quality, keys, joins, temporal, languages, mapping_rows, a_rows, b_rows, eval_rows, runtime, cache_size, runtime_date)
        (REPORTS / "TARGETED_EVIDENCE_REPORT.md").write_text(report, encoding="utf-8")
        print("TARGETED EVIDENCE COMPLETE", flush=True)
        print(f"datasets processed: {', '.join(DATASETS)}", flush=True)
        print(f"rows per dataset: {json.dumps(row_counts)}", flush=True)
        print(f"cache location: {DB_PATH}", flush=True)
        print(f"cache size: {cache_size:,} bytes", flush=True)
        print(f"total runtime: {runtime:.2f} seconds", flush=True)
        print(f"evaluation runtime date (future-timestamp check): {runtime_date}", flush=True)
        print(f"join test status: COMPLETED ({len(joins)}/{len(JOIN_SPECS)} relationships measured)", flush=True)
        print(f"language test status: COMPLETED ({len(languages)} observed values)", flush=True)
        print("Workflow A evidence status: EVIDENCE_GENERATED", flush=True)
        print("Workflow B evidence status: EVIDENCE_GENERATED", flush=True)
        print("evaluation evidence status: EVIDENCE_GENERATED", flush=True)
        print("errors/warnings: 0 errors; 4 documented warnings in analysis_cache_manifest.json", flush=True)
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
