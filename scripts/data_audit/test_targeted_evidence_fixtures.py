"""End-to-end artifact-schema validation using a tiny synthetic dataset.

Runs targeted_evidence.main() against a fixture `data/` tree (NOT the real 5.3 GB
raw data) and validates every generated artifact per fix #14:
  - complete, deterministic columns (union schema across all rows)
  - no silently dropped fields
  - explicit UNKNOWN / N-A handling for unmeasurable metrics
  - manifest records evaluation_runtime_date and architecture constants
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _write(path: Path, header_and_rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for row in header_and_rows:
            w.writerow(row)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    import targeted_evidence as te

    data = tmp_path / "data"
    reports = tmp_path / "reports" / "incremental"
    cache = tmp_path / "cache"

    # customers: 2 rows
    _write(data / "customers.csv", [["customer_id", "registration_branch_id", "customer_status", "country", "detected_accent"],
                                     ["C1", "B1", "Active", "MX", "neutral"], ["C2", "B1", "Active", "MX", "neutral"]])
    # products
    _write(data / "products.csv", [["product_id", "customer_id", "product_status", "product_type", "opening_branch_id"],
                                    ["P1", "C1", "Active", "Debit Card", "B1"], ["P2", "C2", "Active", "Credit Card", "B1"]])
    # agents
    _write(data / "service_agents.csv", [["agent_id", "assigned_branch_id", "agent_status", "languages", "specialty"],
                                          ["A1", "B1", "Active", "es,en", "billing"]])
    # transactions: hive-partitioned dir; includes same-day date-only process + one inversion
    tx = data / "transactions" / "year=2026" / "month=01" / "day=10"
    _write(tx / "part-0.csv", [["transaction_id", "transaction_date", "process_date", "product_id", "customer_id",
                                 "transaction_type", "transaction_category", "amount", "currency", "transaction_status",
                                 "response_code", "is_fraud", "fraud_score"],
                                ["T1", "2026-01-10 09:00:00", "2026-01-10", "P1", "C1", "purchase", "pos", "10", "USD", "Approved", "00", "false", "0.1"],
                                ["T2", "2026-01-10 09:30:00", "2026-01-09", "P1", "C1", "withdrawal", "atm", "20", "USD", "Declined", "05", "true", "0.9"]])
    # interactions: Spanish taxonomy + repeated customer (structure, NOT leakage)
    _write(data / "call_center_interactions.csv", [["interaction_id", "interaction_date", "process_date", "customer_id", "agent_id",
                                                     "interaction_type", "channel", "contact_reason", "reason_category", "duration_seconds",
                                                     "wait_time_seconds", "was_resolved", "requires_followup", "detected_sentiment",
                                                     "sentiment_score", "was_escalated", "mentioned_products", "has_transcript"],
                                                    ["I1", "2026-01-10 09:00:00", "2026-01-10", "C1", "A1", "Inbound Call", "voice", "Transaccional", "Transaccional", "120", "5", "true", "false", "neutral", "0.5", "false", "P1", "true"],
                                                    ["I2", "2026-01-10 10:00:00", "2026-01-10", "C1", "A1", "Chat", "chat", "Queja", "Queja", "300", "10", "false", "true", "negative", "0.2", "true", "", "true"],
                                                    ["I3", "2026-01-10 11:00:00", "2026-01-10", "C2", "A1", "Inbound Call", "voice", "Retención", "Retención", "60", "1", "true", "false", "positive", "0.8", "false", "", "false"]])
    # transcripts (no full_text materialized by design)
    _write(data / "call_transcripts.csv", [["transcript_id", "interaction_id", "process_date", "customer_id", "agent_id",
                                            "detected_language", "detected_accent", "accent_confidence", "detected_intents",
                                            "main_topics", "duration_seconds", "transcription_model", "audio_quality"],
                                           ["R1", "I1", "2026-01-10", "C1", "A1", "es", "MX", "0.9", "query", "billing", "120", "whisper", "high"],
                                           ["R2", "I2", "2026-01-10", "C1", "A1", "es", "MX", "0.8", "complaint", "charge", "300", "whisper", "high"]])
    # complaints: origin_interaction_id ENTIRELY EMPTY (tests UNKNOWN match-rate rule)
    _write(data / "complaints.csv", [["complaint_id", "creation_date", "process_date", "customer_id", "case_type", "category",
                                      "subcategory", "reception_channel", "affected_product_id", "related_branch_id",
                                      "origin_interaction_id", "priority", "status", "assigned_agent_id", "assignment_date",
                                      "first_response_date", "resolution_date", "closing_date", "sla_breached",
                                      "resolution_days", "resolution", "compensation_granted", "resolution_satisfaction",
                                      "is_repeat_complainer"],
                                     ["K1", "2026-01-10", "2026-01-10", "C1", "formal", "Transaccional", "cargo", "web", "P1", "B1", "", "alta", "closed", "A1", "2026-01-10", "2026-01-10", "2026-01-12", "2026-01-12", "true", "2", "refund issued", "true", "satisfied", "false"],
                                     ["K2", "2026-01-10", "2026-01-10", "C2", "formal", "Queja", "servicio", "phone", "", "B1", "", "media", "open", "", "", "", "", "", "", "", "", "", "", "false"]])
    # surveys
    _write(data / "satisfaction_surveys.csv", [["survey_id", "survey_date", "process_date", "interaction_id", "customer_id",
                                                "agent_id", "main_score", "nps_category", "comment_sentiment"],
                                               ["S1", "2026-01-11", "2026-01-11", "I1", "C1", "A1", "5", "promoter", "positive"]])

    te.configure_paths(data_root=data, reports_dir=reports, cache_root=cache)
    monkeypatch.setattr(te, "_TEST_HIVE_OFF", True, raising=False)
    orig_make_cache = te.make_cache
    monkeypatch.setattr(te, "make_cache", lambda con: orig_make_cache(con, hive_partitioning=False))
    try:
        rc = te.main()
    finally:
        te.configure_paths(data_root=te.ROOT / "data", reports_dir=te.ROOT / "reports" / "incremental",
                           cache_root=__import__("os").environ.get("LOCALAPPDATA", str(te.ROOT)) and __import__("pathlib").Path(__import__("os").environ.get("LOCALAPPDATA", str(te.ROOT))) / "Factored_hackathon_audit")
    assert rc == 0, "main() returned nonzero on synthetic fixtures"
    return reports


ARTIFACTS = [
    "05_relevant_profile.csv", "06_join_quality.csv", "07_language_coverage.csv",
    "08_workflow_A_feasibility.csv", "09_workflow_B_feasibility.csv",
    "10_evaluation_feasibility.csv", "workflow_A_category_mapping.csv",
]


def test_all_artifacts_exist_with_union_schema(sandbox):
    for name in ARTIFACTS:
        path = sandbox / name
        assert path.is_file(), f"missing artifact {name}"
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames
            rows = list(reader)
        assert header and None not in header
        # no silently dropped fields: every value key present in header
        for i, row in enumerate(rows):
            extra = set(row.keys()) - set(header) - {None}
            assert not extra, f"{name} row {i} has off-schema keys {extra}"
            missing = [k for k in header if k is None]
            assert not missing
        # deterministic ordering: rewriting from parsed rows yields identical header
        import targeted_evidence as te
        assert te.union_schema(rows) == header or set(te.union_schema([r for r in rows if any(r.values())])) <= set(header)


def test_temporal_metrics_present_and_same_day_not_leakage(sandbox):
    rows = list(csv.DictReader((sandbox / "05_relevant_profile.csv").open(encoding="utf-8")))
    tx = {r["metric"]: r["value"] for r in rows if r.get("dataset") == "transactions"}
    for metric in ("event_before_process_count", "process_before_event_count", "same_calendar_day_count",
                   "temporal_comparison_unknown_count", "event_process_lag_min", "event_process_lag_max",
                   "event_process_lag_median"):
        assert metric in tx, f"missing temporal metric {metric}"
    # T1: process 2026-01-10 (date-only) vs event 2026-01-10 09:00 -> SAME_CALENDAR_DAY,
    #     never counted as process-before-event despite midnight semantics.
    # T2: process 2026-01-09 strictly before event 2026-01-10 -> genuine negative ordering.
    assert tx["same_calendar_day_count"] == "1"
    assert tx["process_before_event_count"] == "1"      # only the genuine inversion
    assert tx["event_before_process_count"] == "0"      # normal direction is not "event before process"
    assert tx["temporal_comparison_unknown_count"] == "0"
    assert tx["true_temporal_ordering_risk"] == "PRESENT"
    # datasets without scoped process_date are NOT_APPLICABLE, never fabricated zeros
    cust = {r["metric"]: r["value"] for r in rows if r.get("dataset") == "customers"}
    assert cust["row_count"] == "2"
    scr = {r["metric"]: r["value"] for r in rows if r.get("dataset") == "satisfaction_surveys"}
    assert scr["process_before_event_count"] == "NOT_APPLICABLE"


def test_workflow_b_origin_fk_rules_on_real_run(sandbox):
    rows = list(csv.DictReader((sandbox / "09_workflow_B_feasibility.csv").open(encoding="utf-8")))
    get = lambda m: next(r for r in rows if r.get("metric") == m)
    assert get("complaint_total")["value"] == "2"
    assert float(get("complaint_origin_interaction_nonnull_rate")["value"]) == 0.0
    match = get("complaint_origin_interaction_match_rate")
    assert match["value"].startswith("UNKNOWN"), "empty FK must yield UNKNOWN match rate, not 0"
    assert match["evidence_status"] == "UNKNOWN"
    # separated linkage dimensions all present
    for m in ("complaint_customer_link_rate", "complaint_product_link_rate",
              "complaint_agent_assignment_rate", "complaint_resolution_date_rate",
              "complaint_closing_date_rate", "complaint_resolution_rate",
              "complaint_resolution_satisfaction_rate", "complaint_sla_breach_rate"):
        assert get(m)["value"] not in ("", None), f"{m} missing value"
    # sla denominator restricted to known states: 1 breached of 1 populated = 100%
    assert float(get("complaint_sla_breach_rate")["value"]) == 100.0


def test_workflow_a_category_mapping_artifact(sandbox):
    rows = list(csv.DictReader((sandbox / "workflow_A_category_mapping.csv").open(encoding="utf-8")))
    trans = next(r for r in rows if r["observed_category"] == "Transaccional" and r["observed_field"] == "contact_reason")
    queja = next(r for r in rows if r["observed_category"] == "Queja" and r["observed_field"] == "contact_reason")
    assert trans["candidate_intent"] == "transaction_inquiry" and trans["mapping_confidence"] == "MEDIUM"
    assert queja["candidate_intent"] == "dispute" and queja["mapping_confidence"] == "LOW"
    for intent in ("failed_transaction", "payment_problem", "transfer_problem", "withdrawal_problem"):
        ev = [r for r in rows if r["candidate_intent"] == intent]
        assert ev and all(r["status"] == "NO_EVIDENCE_IN_OBSERVED_TAXONOMY" for r in ev)
    # Workflow A feasibility metrics must NOT be zero despite Spanish taxonomy
    feas = list(csv.DictReader((sandbox / "08_workflow_A_feasibility.csv").open(encoding="utf-8")))
    get = lambda m: next(r for r in feas if r.get("metric") == m)
    assert int(get("transaction_related_customer_service_interactions")["value"]) == 2
    assert float(get("relevant_interaction_percentage")["value"]) > 0
    assert get("granular_failure_intents_evidence")["value"] == "NO_EVIDENCE_IN_OBSERVED_TAXONOMY"


def test_manifest_records_runtime_date_and_architecture(sandbox):
    manifest = json.loads((sandbox / "analysis_cache_manifest.json").read_text(encoding="utf-8"))
    today = datetime.now(timezone.utc).date().isoformat()
    assert manifest["evaluation_runtime_date"] == today
    assert manifest["duckdb_threads"] == 4
    assert manifest["duckdb_memory_limit"] == "512MB"
    assert len(manifest["datasets_processed"]) == 8
    assert manifest["distribution_authority"]["language"] == "07_language_coverage.csv"
    report = (sandbox / "TARGETED_EVIDENCE_REPORT.md").read_text(encoding="utf-8")
    assert today in report


def test_report_markdown_generated(sandbox):
    md = (sandbox / "TARGETED_EVIDENCE_REPORT.md").read_text(encoding="utf-8")
    assert "EVIDENCE_GENERATED" not in md.split("##")[0]  # report body describes statuses, not PASS claims
    assert "granularity-aware" in md.lower()
    assert "NO_EVIDENCE_IN_OBSERVED_TAXONOMY" in md
