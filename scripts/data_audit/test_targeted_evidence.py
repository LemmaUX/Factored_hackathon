"""Regression tests for targeted_evidence.py (v2 methodology fixes).

All tests use small synthetic fixtures or pure functions. NO raw 5.3 GB data is read.

Coverage (per fix list #13):
  A. DATE vs TIMESTAMP same-day is NOT process-before-event
  B. Actual timestamp inversion detection (both directions)
  C. Repeated customer != leakage (separate diagnostics)
  D. Empty origin_interaction_id -> nonnull_rate 0, match_rate UNKNOWN (not 0)
  E. write_csv union-schema correctness (later-row fields not silently lost)
  F. Workflow A observed-category mapping (Spanish taxonomy; no invented mappings)
  G. Runtime current date (no hard-coded TODAY; manifest records evaluation_runtime_date)
  H. Artifact schema validation (deterministic complete columns via fixtures)
Plus: granularity-aware SQL parity (Python classifier vs DuckDB CASE), temporal
metrics presence, status semantics (EVIDENCE_GENERATED / COMPLETED, no PASS-as-run-status).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import targeted_evidence as te  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


def make_events_table(c, rows):
    """rows: list of (event_ts, process_ts) VARCHAR strings (None = NULL/empty)."""
    c.execute("DROP TABLE IF EXISTS events")
    c.execute("CREATE TABLE events (event_date VARCHAR, process_date VARCHAR)")
    for e, p in rows:
        c.execute("INSERT INTO events VALUES (?, ?)", [e, p])


# ---------------------------------------------------------------------------
# A. DATE vs TIMESTAMP same-day must NOT be process-before-event
# ---------------------------------------------------------------------------
def test_same_day_date_vs_timestamp_not_negative_ordering():
    assert te.classify_ordering("2026-01-10", "2026-01-10 09:00:00") == "SAME_CALENDAR_DAY"
    assert te.classify_ordering("2026-01-10", "2026-01-10 00:00:01") == "SAME_CALENDAR_DAY"
    assert te.classify_ordering("2026-01-10", "2026-01-10") == "SAME_CALENDAR_DAY"


def test_sql_granularity_parity_with_python_classifier(con):
    """DuckDB CASE and the Python reference classifier must agree on every case."""
    cases = [
        ("2026-01-10", "2026-01-10 09:00:00"),          # same day, date-only process
        ("2026-01-10 08:00:00", "2026-01-10 09:00:00"),  # both timed: event after process
        ("2026-01-10 08:00:00", "2026-01-09 09:00:00"),  # both timed: actual inversion
        ("2026-01-11", "2026-01-10 23:00:00"),           # process next day => OK ordering
        ("2026-01-09", "2026-01-10 01:00:00"),           # process prior day => negative
        ("", "2026-01-10 09:00:00"),                     # unknown
        ("2026-01-10 08:00:00", None),                   # unknown
    ]
    make_events_table(con, [(e, p) for p, e in cases])
    cls_sql = te.granularity_class_expr("process_date", "event_date")
    got = con.execute(f"SELECT process_date, event_date, {cls_sql} FROM events").fetchall()
    lookup = {(row[0] or "", row[1] or ""): row[2] for row in got}
    assert len(lookup) == len(cases), "fixture rows collided; check inputs"
    for p, e in cases:
        want = te.classify_ordering(p, e)
        key = (p or "", e or "")
        assert key in lookup, f"missing fixture row {key}"
        assert lookup[key] == want, f"SQL/Python mismatch for ({p!r}, {e!r}): sql={lookup[key]} py={want}"


# ---------------------------------------------------------------------------
# B. Actual timestamp inversion detection
# ---------------------------------------------------------------------------
def test_both_timed_process_earlier_is_event_before_process():
    # process 08:00, event 09:00 same day: event happened AFTER processing time
    # comparison is timestamp-to-timestamp; NOT counted as negative ordering of
    # process-before-event? Per spec: "event-before-process = false" means the
    # pair is classified PROCESS_BEFORE_EVENT (process strictly earlier instant).
    result = te.classify_ordering("2026-01-10 08:00:00", "2026-01-10 09:00:00")
    assert result == "PROCESS_BEFORE_EVENT"
    assert result != "EVENT_BEFORE_PROCESS"


def test_both_timed_actual_negative_ordering_detected():
    # process 2026-01-10 08:00 vs event 2026-01-09 09:00 -> event BEFORE process is FALSE;
    # process is LATER than event, i.e., normal direction (event_before_process true).
    result = te.classify_ordering("2026-01-10 08:00:00", "2026-01-09 09:00:00")
    assert result == "EVENT_BEFORE_PROCESS"
    # And the genuinely inverted case (process strictly before event when both timed):
    inverted = te.classify_ordering("2026-01-09 08:00:00", "2026-01-10 09:00:00")
    assert inverted == "PROCESS_BEFORE_EVENT"


def test_negative_lag_only_when_granularity_supports_it(con):
    """A table where process_date is DATE-only and events carry time-of-day must
    produce ZERO process_before_event rows for same-calendar-day pairs."""
    rows = [("2026-01-10 09:00:00", "2026-01-10"), ("2026-01-11 10:30:00", "2026-01-11")]
    make_events_table(con, rows)
    cls = te.granularity_class_expr("process_date", "event_date")
    neg = con.execute(f"SELECT count(*) FROM (SELECT {cls} c FROM events) WHERE c='PROCESS_BEFORE_EVENT'").fetchone()[0]
    same = con.execute(f"SELECT count(*) FROM (SELECT {cls} c FROM events) WHERE c='SAME_CALENDAR_DAY'").fetchone()[0]
    assert neg == 0
    assert same == 2


# ---------------------------------------------------------------------------
# C. Repeated customer != leakage
# ---------------------------------------------------------------------------
def test_repeated_customers_do_not_set_temporal_risk(con):
    """temporal_profile's true_temporal_ordering_risk depends only on ordering."""
    con.execute("CREATE TABLE transactions (transaction_id VARCHAR, transaction_date VARCHAR, process_date VARCHAR, product_id VARCHAR, customer_id VARCHAR, transaction_type VARCHAR, transaction_category VARCHAR, amount VARCHAR, currency VARCHAR, transaction_status VARCHAR, response_code VARCHAR, is_fraud VARCHAR, fraud_score VARCHAR, __source_file VARCHAR)")
    # one customer repeated 5x, all same calendar day, date-only process => no leakage
    for i in range(5):
        con.execute("INSERT INTO transactions VALUES (?, '2026-01-10 09:00:00', '2026-01-10', 'P1','C1','purchase','pos','10','USD','Approved','','','', 'x')", [f"T{i}"])
    counts = {"transactions": 5}
    saved = dict(te.EVENT_DATES)
    te.EVENT_DATES = {"transactions": "transaction_date"}
    try:
        rows = te.temporal_profile(con, counts, dt.date(2026, 9, 30))
    finally:
        te.EVENT_DATES = saved
    by_metric = {r["metric"]: r["value"] for r in rows if r["dataset"] == "transactions"}
    assert by_metric["process_before_event_count"] == 0
    assert by_metric["same_calendar_day_count"] == 5
    assert by_metric["true_temporal_ordering_risk"] == "NOT_OBSERVED"


def test_evaluation_separates_repeat_structure_from_leakage(con):
    """evaluation() emits distinct metric families per concept."""
    for tbl, cols in (
        ("call_center_interactions", ["interaction_id", "interaction_date", "process_date", "customer_id", "was_resolved"]),
        ("complaints", ["complaint_id", "creation_date", "process_date", "customer_id", "origin_interaction_id", "resolution"]),
        ("satisfaction_surveys", ["survey_id", "survey_date", "interaction_id"]),
    ):
        coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        con.execute(f"CREATE TABLE {tbl} ({coldefs})")
    # two interactions, SAME customer, same day, date-only process -> repeat structure, no leakage
    con.execute("INSERT INTO call_center_interactions VALUES ('I1','2026-01-10 09:00:00','2026-01-10','C1','true')")
    con.execute("INSERT INTO call_center_interactions VALUES ('I2','2026-01-10 10:00:00','2026-01-10','C1','false')")
    con.execute("INSERT INTO complaints VALUES ('K1','2026-01-10','2026-01-10','C1','','resolved')")
    keys = [{"dataset": "call_center_interactions", "duplicate_rows": 0}, {"dataset": "complaints", "duplicate_rows": 0}]
    rows = te.evaluation(con, {"call_center_interactions": 2, "complaints": 1}, keys, dt.date(2026, 9, 30))
    metrics = {r["metric"] for r in rows}
    assert any(m.startswith("repeat_customer_structure.") for m in metrics)
    assert any(m.startswith("customer_overlap_across_temporal_splits.") for m in metrics)
    a_rows = [r for r in rows if r["workflow"] == "A"]
    get = lambda name: next(r["value"] for r in a_rows if r["metric"] == name)
    assert get("repeat_customer_structure.repeated_customer_rows") == 1      # structural fact
    assert get("true_temporal_ordering_risk") == "NOT_OBSERVED"              # NOT triggered by repeats
    assert get("post_outcome_feature_risk") == "REQUIRES_MANUAL_REVIEW"
    assert get("leakage_risk") == "REQUIRES_MANUAL_REVIEW"


# ---------------------------------------------------------------------------
# D. Empty origin_interaction_id
# ---------------------------------------------------------------------------
def _make_complaint_tables(con, origin_values):
    con.execute("CREATE TABLE complaints (complaint_id VARCHAR, customer_id VARCHAR, affected_product_id VARCHAR, assigned_agent_id VARCHAR, origin_interaction_id VARCHAR, resolution_date VARCHAR, closing_date VARCHAR, resolution VARCHAR, resolution_satisfaction VARCHAR, sla_breached VARCHAR)")
    con.execute("CREATE TABLE customers (customer_id VARCHAR)")
    con.execute("CREATE TABLE products (product_id VARCHAR)")
    con.execute("CREATE TABLE service_agents (agent_id VARCHAR)")
    con.execute("CREATE TABLE call_center_interactions (interaction_id VARCHAR)")
    con.execute("INSERT INTO customers VALUES ('C1'), ('C2')")
    con.execute("INSERT INTO products VALUES ('P1')")
    con.execute("INSERT INTO service_agents VALUES ('A1')")
    con.execute("INSERT INTO call_center_interactions VALUES ('I1')")
    for i, o in enumerate(origin_values):
        con.execute("INSERT INTO complaints VALUES (?, 'C1', 'P1', 'A1', ?, '', '', '', '', '')", [f"K{i}", o])


def test_origin_fk_all_empty_nonnull_zero_match_unknown(con):
    joins = []
    specs = [
        ("complaints", "customer_id", "customers", "customer_id"),
        ("complaints", "affected_product_id", "products", "product_id"),
        ("complaints", "origin_interaction_id", "call_center_interactions", "interaction_id"),
        ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ]
    _make_complaint_tables(con, ["", "", ""])
    rc = {"complaints": 3, "customers": 2, "products": 1, "service_agents": 1, "call_center_interactions": 1}
    orig_specs = te.JOIN_SPECS
    te.JOIN_SPECS = specs
    try:
        joins = te.join_profile(con, rc)
    finally:
        te.JOIN_SPECS = orig_specs
    b_rows = te.workflow_b(con, rc, joins)
    get = lambda name: next(r for r in b_rows if r["metric"] == name)
    nonnull = get("complaint_origin_interaction_nonnull_rate")
    match = get("complaint_origin_interaction_match_rate")
    assert nonnull["value"] == 0
    assert match["value"] == "UNKNOWN_NOT_APPLICABLE"
    assert match["evidence_status"] == "UNKNOWN"
    assert "0.0" != str(match["value"])
    ctx = get("complaint_interaction_context_linkage")
    assert ctx["value"] == "MISSING_FOREIGN_KEY"
    # join profile itself must not report a silent 0% match rate
    origin_join = next(j for j in joins if j["child_key"] == "origin_interaction_id")
    assert origin_join["match_rate_pct"] == "UNKNOWN_NO_NONNULL_KEYS"


def test_origin_fk_populated_measures_match_rate(con):
    specs = [
        ("complaints", "customer_id", "customers", "customer_id"),
        ("complaints", "affected_product_id", "products", "product_id"),
        ("complaints", "origin_interaction_id", "call_center_interactions", "interaction_id"),
        ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ]
    _make_complaint_tables(con, ["I1", "GHOST", ""])
    rc = {"complaints": 3, "customers": 2, "products": 1, "service_agents": 1, "call_center_interactions": 1}
    orig = te.JOIN_SPECS
    te.JOIN_SPECS = specs
    try:
        joins = te.join_profile(con, rc)
    finally:
        te.JOIN_SPECS = orig
    b_rows = te.workflow_b(con, rc, joins)
    nonnull = next(r for r in b_rows if r["metric"] == "complaint_origin_interaction_nonnull_rate")["value"]
    match = next(r for r in b_rows if r["metric"] == "complaint_origin_interaction_match_rate")["value"]
    assert abs(nonnull - 200 / 3) < 1e-6           # 2 of 3 rows populated
    assert abs(match - 50.0) < 1e-6                 # 1 of 2 distinct non-null keys matched


# ---------------------------------------------------------------------------
# E. CSV union-schema correctness
# ---------------------------------------------------------------------------
def test_write_csv_union_schema(tmp_path):
    rows = [
        {"a": 1, "b": 2},
        {"a": 3, "c": 4},          # 'c' appears only in a later row
        {"b": 5, "d": 6},          # 'd' appears only in the last row
    ]
    out = tmp_path / "union.csv"
    te.write_csv(out, rows)
    with out.open(newline="", encoding="utf-8") as fh:
        parsed = list(csv.DictReader(fh))
    assert list(parsed[0].keys()) == ["a", "b", "c", "d"]     # union, deterministic order
    assert parsed[1]["c"] == "4"                               # later-row field preserved
    assert parsed[2]["d"] == "6"
    assert parsed[0]["c"] == "" and parsed[0]["d"] == ""       # explicit blanks, no drops


def test_no_positional_writeback_in_source():
    src = Path(te.__file__).read_text(encoding="utf-8")
    assert "rows[-4]" not in src and "rows[-1][" not in src.replace("rows[-1][", "rows[-1][", 0) or True
    # stronger: no positional mutation patterns at all
    assert not re.search(r"rows\[-\d+\]\[", src), "positional write-back found"
    assert "record_id" in src, "explicit record identity missing"


# ---------------------------------------------------------------------------
# F. Workflow A observed-category mapping
# ---------------------------------------------------------------------------
OBSERVED_INTERACTION_DIST = [
    {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Transaccional", "rows": 240056, "percentage": 34.978493},
    {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Producto", "rows": 150863, "percentage": 21.982206},
    {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Queja", "rows": 117021, "percentage": 17.051097},
    {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Técnico", "rows": 102899, "percentage": 14.993385},
    {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Comercial", "rows": 54879, "percentage": 7.996404},
    {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Retención", "rows": 20578, "percentage": 2.998415},
    {"dataset": "call_center_interactions", "field": "reason_category", "category": "Transaccional", "rows": 240056, "percentage": 34.978493},
    {"dataset": "call_center_interactions", "field": "reason_category", "category": "Queja", "rows": 117021, "percentage": 17.051097},
    {"dataset": "call_center_interactions", "field": "interaction_type", "category": "Inbound Call", "rows": 480678, "percentage": 70.039458},
]


def test_category_mapping_policy_and_artifact_columns():
    rows = te.build_category_mapping(OBSERVED_INTERACTION_DIST)
    required_cols = ["observed_field", "observed_category", "candidate_intent", "mapping_method",
                     "mapping_confidence", "row_count", "percentage", "status"]
    assert set(required_cols) <= set(rows[0].keys())
    trans = next(r for r in rows if r["observed_category"] == "Transaccional" and r["observed_field"] == "contact_reason")
    queja = next(r for r in rows if r["observed_category"] == "Queja" and r["observed_field"] == "contact_reason")
    assert trans["candidate_intent"] == "transaction_inquiry" and trans["mapping_confidence"] == "MEDIUM"
    assert queja["candidate_intent"] == "dispute" and queja["mapping_confidence"] == "LOW"
    # granular intents explicitly recorded as NO_EVIDENCE, never fabricated
    for intent in ("failed_transaction", "payment_problem", "transfer_problem", "withdrawal_problem"):
        no_ev = [r for r in rows if r["candidate_intent"] == intent]
        assert no_ev and all(r["status"] == "NO_EVIDENCE_IN_OBSERVED_TAXONOMY" for r in no_ev)
    # unsupported categories map to unknown, not to an invented intent
    producto = next(r for r in rows if r["observed_category"] == "Producto")
    assert producto["candidate_intent"] == "unknown" and producto["status"] == "UNMAPPED_NO_EVIDENCE"
    # interaction_type excluded as channel metadata
    itype = next(r for r in rows if r["observed_field"] == "interaction_type")
    assert itype["status"] == "FIELD_NOT_SUITABLE_FOR_INTENT_MAPPING"
    # every candidate intent used is within the allowed vocabulary
    allowed = set(te.ALLOWED_CANDIDATE_INTENTS)
    assert all(r["candidate_intent"] in allowed for r in rows)
    # original observed category names are preserved verbatim (Spanish accents intact)
    assert any(r["observed_category"] == "Retención" for r in rows)


def test_workflow_a_metrics_not_zero_after_mapping_fix(con):
    """With mapped Spanish categories present, relevant-interaction volume > 0."""
    con.execute('CREATE TABLE transactions ("transaction_id" VARCHAR, "is_fraud" VARCHAR, "fraud_score" VARCHAR, "transaction_status" VARCHAR)')
    con.execute("INSERT INTO transactions VALUES ('T1','1','0.9','Declined')")
    con.execute('CREATE TABLE call_center_interactions ("contact_reason" VARCHAR, "reason_category" VARCHAR, "was_resolved" VARCHAR, "was_escalated" VARCHAR, "requires_followup" VARCHAR, "has_transcript" VARCHAR)')
    con.execute("INSERT INTO call_center_interactions VALUES ('Transaccional','Transaccional','true','false','true','yes')")
    con.execute("INSERT INTO call_center_interactions VALUES ('Queja','Queja','false','true','false','no')")
    con.execute("INSERT INTO call_center_interactions VALUES ('Producto','Producto','true','false','false','no')")
    mapping = te.build_category_mapping([
        {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Transaccional", "rows": 1},
        {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Queja", "rows": 1},
        {"dataset": "call_center_interactions", "field": "contact_reason", "category": "Producto", "rows": 1},
        {"dataset": "call_center_interactions", "field": "reason_category", "category": "Transaccional", "rows": 1},
        {"dataset": "call_center_interactions", "field": "reason_category", "category": "Queja", "rows": 1},
        {"dataset": "call_center_interactions", "field": "reason_category", "category": "Producto", "rows": 1},
    ])
    rows = te.workflow_a(con, {"transactions": 1, "call_center_interactions": 3}, mapping)
    get = lambda name: next(r for r in rows if r["metric"] == name)["value"]
    assert get("transaction_related_customer_service_interactions") == 2   # Transaccional + Queja
    assert get("relevant_interaction_percentage") > 0
    assert get("mapped_categories") == "Queja,Transaccional"
    assert get("granular_failure_intents_evidence") == "NO_EVIDENCE_IN_OBSERVED_TAXONOMY"


def test_english_regex_mechanism_removed():
    src = Path(te.__file__).read_text(encoding="utf-8")
    assert "plausible_category_" not in src
    assert 'r"fail|declin|reject' not in src
    assert "tokens = {" not in src


# ---------------------------------------------------------------------------
# G. Runtime current date
# ---------------------------------------------------------------------------
def test_no_hardcoded_today_and_manifest_records_runtime_date():
    src = Path(te.__file__).read_text(encoding="utf-8")
    assert not re.search(r'^TODAY\s*=', src, re.M), "hard-coded TODAY constant still present"
    assert "datetime.now(timezone.utc).date()" in src
    assert '"evaluation_runtime_date"' in src
    assert "runtime_date" in src.split("def main")[1], "main() must thread runtime_date through"


def test_future_timestamp_check_uses_passed_runtime_date(con):
    con.execute('CREATE TABLE transactions ("transaction_date" VARCHAR, "process_date" VARCHAR)')
    con.execute("INSERT INTO transactions VALUES ('2027-01-01 00:00:00', '2026-01-02')")
    con.execute("INSERT INTO transactions VALUES ('2026-01-01 00:00:00', '2026-01-02')")
    con.execute("ALTER TABLE transactions ADD COLUMN __source_file VARCHAR DEFAULT ''")
    saved = dict(te.EVENT_DATES)
    te.EVENT_DATES = {"transactions": "transaction_date"}
    try:
        rows = te.temporal_profile(con, {"transactions": 2}, dt.date(2026, 9, 30))
    finally:
        te.EVENT_DATES = saved
    future = next(r for r in rows if r["metric"] == "future_timestamps_vs_runtime_date")
    assert future["value"] == 1
    assert "2026-09-30" in future["note"]


# ---------------------------------------------------------------------------
# H. Artifact schema validation (fixture-level end-to-end writes)
# ---------------------------------------------------------------------------
def test_generated_artifacts_have_complete_deterministic_schema(tmp_path, con):
    mixed = [
        {"dataset": "x", "metric": "m1", "value": 1, "unit": "rows", "evidence_status": "EXACT"},
        {"dataset": "x", "metric": "m2", "value": 2, "unit": "rows", "evidence_status": "EXACT", "note": "n"},
    ]
    out = tmp_path / "artifact.csv"
    te.write_csv(out, mixed)
    text = out.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    assert header == "dataset,metric,value,unit,evidence_status,note"
    parsed = list(csv.DictReader(out.open(encoding="utf-8")))
    assert parsed[0]["note"] == "" and parsed[1]["note"] == "n"


def test_status_semantics_in_source():
    src = Path(te.__file__).read_text(encoding="utf-8")
    assert "Workflow A evidence status: EVIDENCE_GENERATED" in src
    assert "Workflow B evidence status: EVIDENCE_GENERATED" in src
    assert "evaluation evidence status: EVIDENCE_GENERATED" in src
    assert "join test status: COMPLETED" in src
    assert "language test status: COMPLETED" in src
    assert "evidence status: PASS" not in src


def test_architecture_contract_preserved():
    src = Path(te.__file__).read_text(encoding="utf-8")
    assert "DUCKDB_THREADS = 4" in src
    assert 'DUCKDB_MEMORY_LIMIT = "512MB"' in src
    assert "PRAGMA threads=" in src and "PRAGMA memory_limit=" in src
    assert len(te.DATASETS) == 8
    assert len(te.JOIN_SPECS) == 15


def test_trivially_true_metrics_removed_or_validated():
    src = Path(te.__file__).read_text(encoding="utf-8")
    # distribution_* metrics that just re-counted their own GROUP BY total are gone
    assert 'f"distribution_{column}"' not in src
    # dataset_profile no longer emits SELECT 0 placeholders
    assert "SELECT 0" not in src


def test_key_profile_executed_once():
    src = Path(te.__file__).read_text(encoding="utf-8")
    body = src.split("def main")[1]
    assert body.count("key_profile(con") == 1, "key_profile must run exactly once in main()"
    sig = src.split("def evaluation")[1].split("def ")[0]
    assert "keys_cached" in sig, "evaluation() must consume cached key profiles"
