"""Deterministic, read-only evidence audit for partitioned CSV banking data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

VERSION = "2.0"
ID_RE = re.compile(r"(^|_)id$", re.I)
TIME_RE = re.compile(r"date|time|timestamp", re.I)
PII_RE = re.compile(r"email|phone|address|name|document|birth|text|description|comment|secret|token", re.I)
EVENT_TABLES = {"transactions", "call_center_interactions", "call_transcripts", "complaints", "digital_events", "satisfaction_surveys", "campaign_sends"}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--reports-root", type=Path, default=Path("reports"))
    return parser.parse_args()


def parse_time(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None


def table_name(data_root: Path, path: Path) -> str:
    relative = path.relative_to(data_root)
    return relative.parts[0] if len(relative.parts) > 1 else path.stem


def partition_date(data_root: Path, path: Path):
    text = str(path.relative_to(data_root))
    match = re.search(r"year=(\d{4}).*?month=(\d{2}).*?(?:day=(\d{2}))?", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3) or '01'}" if match else None


def hash_files(files: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(str(path.stat().st_size).encode())
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    root = args.data_root.resolve()
    reports = args.reports_root.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    files = sorted(root.rglob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found under {root}")

    table_files: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        table_files[table_name(root, path)].append(path)
    table_stats: dict[str, dict] = {}
    key_values: dict[tuple[str, str], set[str]] = defaultdict(set)
    key_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    field_stats: dict[tuple[str, str], dict] = {}
    temporal: dict[str, Counter] = defaultdict(Counter)
    languages: Counter = Counter()
    language_by_country: Counter = Counter()
    workflow_counts = Counter()
    transcript_linked = Counter()

    for table, paths in sorted(table_files.items()):
        stats = {"rows": 0, "bytes": sum(path.stat().st_size for path in paths), "columns": [], "files": len(paths), "dates": [], "partition_dates": set(), "duplicate_rows": 0}
        row_fingerprints: set[bytes] = set()
        headers_seen: set[tuple[str, ...]] = set()
        for path in paths:
            stats["partition_dates"].add(partition_date(root, path))
            with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
                reader = csv.DictReader(handle)
                headers = tuple(reader.fieldnames or ())
                headers_seen.add(headers)
                if not stats["columns"]:
                    stats["columns"] = list(headers)
                for row in reader:
                    stats["rows"] += 1
                    # Exact duplicate counting is bounded to candidate-key duplicates;
                    # full-row fingerprints are intentionally not retained for huge tables.
                    event_date = None
                    for column in headers:
                        value = (row.get(column) or "").strip()
                        key = (table, column)
                        item = field_stats.setdefault(key, {"null": 0, "empty": 0, "distinct": set(), "invalid_time": 0, "min": None, "max": None, "examples": []})
                        if not value:
                            item["null"] += 1
                            item["empty"] += 1
                            continue
                        item["distinct"].add(value if not PII_RE.search(column) else hashlib.sha256(value.encode()).hexdigest())
                        if len(item["examples"]) < 3 and not PII_RE.search(column):
                            item["examples"].append(value[:80])
                        if TIME_RE.search(column):
                            parsed = parse_time(value)
                            if parsed is None:
                                item["invalid_time"] += 1
                            else:
                                item["min"] = parsed.isoformat() if item["min"] is None else min(item["min"], parsed.isoformat())
                                item["max"] = parsed.isoformat() if item["max"] is None else max(item["max"], parsed.isoformat())
                                event_date = parsed.date().isoformat()
                    for column in headers:
                        if ID_RE.search(column):
                            value = (row.get(column) or "").strip()
                            if value:
                                key_values[(table, column)].add(value)
                                key_counts[(table, column)][value] += 1
                    if event_date:
                        temporal[table][event_date] += 1
                        stats["dates"].append(event_date)
                    if table == "call_transcripts":
                        language = (row.get("detected_language") or "UNKNOWN").strip() or "UNKNOWN"
                        languages[language] += 1
                    if table == "call_center_interactions":
                        reason = (row.get("reason_category") or row.get("contact_reason") or "UNKNOWN").strip() or "UNKNOWN"
                        workflow_counts[reason] += 1
                    if table == "customers":
                        language_by_country[(row.get("country") or "UNKNOWN", row.get("detected_accent") or "UNKNOWN")] += 1
        stats["schema_consistent"] = len(headers_seen) == 1
        candidate_columns = [column for column in stats["columns"] if ID_RE.search(column)]
        if candidate_columns:
            stats["duplicate_rows"] = sum(max(0, count - 1) for column in candidate_columns for count in key_counts[(table, column)].values())
        stats["date_min"] = min(stats["dates"]) if stats["dates"] else None
        stats["date_max"] = max(stats["dates"]) if stats["dates"] else None
        stats["partition_coverage"] = sorted(value for value in stats["partition_dates"] if value)
        table_stats[table] = stats

    inventory = []
    quality = []
    for table, stats in sorted(table_stats.items()):
        candidate_keys = []
        for column in stats["columns"]:
            values = key_values.get((table, column), set())
            if values and stats["rows"] and len(values) == stats["rows"]:
                candidate_keys.append(column)
            item = field_stats[(table, column)]
            null_pct = round(item["null"] / stats["rows"] * 100, 4) if stats["rows"] else 0
            quality.append({"dataset": table, "column": column, "rows": stats["rows"], "null_count": item["null"], "null_pct": null_pct, "distinct_count": len(item["distinct"]), "invalid_timestamp_count": item["invalid_time"], "severity": "CRITICAL" if ID_RE.search(column) and null_pct > 0 else ("HIGH" if null_pct >= 10 else "MEDIUM" if null_pct > 0 else "LOW"), "representative_values": json.dumps(item["examples"], ensure_ascii=False)})
        inventory.append({"logical_name": table, "physical_path_pattern": str(root / "**" / f"{table}*.csv"), "file_format": "CSV", "partition_columns": "year,month,day" if stats["partition_coverage"] else "", "rows": stats["rows"], "columns": len(stats["columns"]), "column_names": json.dumps(stats["columns"], ensure_ascii=False), "min_timestamp": min((field_stats[(table, c)]["min"] for c in stats["columns"] if field_stats[(table, c)]["min"]), default=None), "max_timestamp": max((field_stats[(table, c)]["max"] for c in stats["columns"] if field_stats[(table, c)]["max"]), default=None), "bytes": stats["bytes"], "partition_coverage": json.dumps(stats["partition_coverage"]), "event_like": table in EVENT_TABLES, "candidate_primary_key": ",".join(candidate_keys), "duplicate_row_count": stats["duplicate_rows"], "duplicate_key_rate": round(1 - len(key_values[(table, candidate_keys[0])]) / stats["rows"], 6) if candidate_keys else None})

    relationships = [("transactions", "customer_id", "customers", "customer_id"), ("transactions", "product_id", "products", "product_id"), ("call_center_interactions", "customer_id", "customers", "customer_id"), ("call_center_interactions", "agent_id", "service_agents", "agent_id"), ("call_transcripts", "interaction_id", "call_center_interactions", "interaction_id"), ("call_transcripts", "customer_id", "customers", "customer_id"), ("complaints", "customer_id", "customers", "customer_id"), ("complaints", "origin_interaction_id", "call_center_interactions", "interaction_id"), ("complaints", "assigned_agent_id", "service_agents", "agent_id"), ("complaints", "affected_product_id", "products", "product_id"), ("satisfaction_surveys", "interaction_id", "call_center_interactions", "interaction_id"), ("satisfaction_surveys", "customer_id", "customers", "customer_id"), ("digital_events", "customer_id", "customers", "customer_id"), ("digital_events", "transaction_id", "transactions", "transaction_id")]
    joins = []
    for child, child_key, parent, parent_key in relationships:
        child_values = key_values.get((child, child_key), set())
        parent_values = key_values.get((parent, parent_key), set())
        if not child_values and not parent_values:
            continue
        matched = child_values & parent_values
        joins.append({"child_dataset": child, "child_key": child_key, "parent_dataset": parent, "parent_key": parent_key, "parent_rows": table_stats.get(parent, {}).get("rows", 0), "child_rows": table_stats.get(child, {}).get("rows", 0), "matched_child_keys": len(matched), "unmatched_child_keys": len(child_values - parent_values), "match_rate_pct": round(len(matched) / len(child_values) * 100, 4) if child_values else 0, "orphan_rate_pct": round(len(child_values - parent_values) / len(child_values) * 100, 4) if child_values else 0, "duplicate_join_key_rate_pct": round(sum(v > 1 for v in key_counts[(child, child_key)].values()) / len(child_values) * 100, 4) if child_values else 0, "status": "VERIFIED RELATIONSHIP" if child_values and parent_values and len(matched) / len(child_values) >= 0.95 else "LIKELY RELATIONSHIP"})

    temporal_rows = []
    for table, counts in sorted(temporal.items()):
        for day, count in sorted(counts.items()):
            temporal_rows.append({"dataset": table, "event_date": day, "year": day[:4], "month": day[:7], "rows": count})
    language_rows = [{"language": language, "transcript_count": count, "percentage": round(count / sum(languages.values()) * 100, 4), "source": "call_transcripts.detected_language", "confidence": "OBSERVED FACT"} for language, count in languages.most_common()]
    Portuguese = sum(count for language, count in languages.items() if re.search(r"portugu", language, re.I))
    transaction_rows = table_stats.get("transactions", {}).get("rows", 0)
    complaint_rows = table_stats.get("complaints", {}).get("rows", 0)
    interaction_rows = table_stats.get("call_center_interactions", {}).get("rows", 0)
    transcript_rows = table_stats.get("call_transcripts", {}).get("rows", 0)
    relevant_a = sum(count for reason, count in workflow_counts.items() if re.search(r"trans|fraud|dispute|payment|withdraw|transfer", reason, re.I))
    relevant_b = sum(count for reason, count in workflow_counts.items() if re.search(r"complaint|queja|reclamo", reason, re.I))
    feasibility_a = feasibility("A", [("transaction records", transaction_rows, ">0"), ("transaction/customer join", next((j["match_rate_pct"] for j in joins if j["child_dataset"] == "transactions" and j["child_key"] == "customer_id"), None), ">=95%"), ("transaction-related interactions", relevant_a, ">=1000"), ("transaction timestamps/status/amount", ", ".join(c for c in ("transaction_date", "transaction_status", "amount") if c in table_stats.get("transactions", {}).get("columns", [])), "all present")])
    feasibility_b = feasibility("B", [("complaint records", complaint_rows, ">0"), ("complaint/customer join", next((j["match_rate_pct"] for j in joins if j["child_dataset"] == "complaints" and j["child_key"] == "customer_id"), None), ">=95%"), ("complaint-related interactions", relevant_b, ">=1000"), ("complaint lifecycle/status", ", ".join(c for c in ("status", "creation_date", "resolution_date", "closing_date") if c in table_stats.get("complaints", {}).get("columns", [])), "status and timestamps present")])
    evaluation = [{"workflow": "A", "relevant_interactions": relevant_a, "threshold": 1000, "status": "PASS" if relevant_a >= 1000 else "FAIL", "transcripts": transcript_rows, "customer_level_leakage": "REQUIRES REVIEW", "golden_set_required": "YES"}, {"workflow": "B", "relevant_interactions": relevant_b, "threshold": 1000, "status": "PASS" if relevant_b >= 1000 else "FAIL", "transcripts": transcript_rows, "customer_level_leakage": "REQUIRES REVIEW", "golden_set_required": "YES"}]

    write_csv(reports / "data_inventory.csv", inventory)
    write_csv(reports / "data_quality.csv", quality)
    write_csv(reports / "join_quality.csv", joins)
    write_csv(reports / "temporal_coverage.csv", temporal_rows)
    write_csv(reports / "language_coverage.csv", language_rows)
    write_csv(reports / "workflow_A_feasibility.csv", feasibility_a)
    write_csv(reports / "workflow_B_feasibility.csv", feasibility_b)
    write_csv(reports / "evaluation_feasibility.csv", evaluation)
    evidence = {"audit_version": VERSION, "audit_timestamp": datetime.now(timezone.utc).isoformat(), "dataset_root": str(root), "files_scanned": len(files), "logical_datasets": len(table_stats), "row_counts": {table: stats["rows"] for table, stats in table_stats.items()}, "input_fingerprint": hash_files(files, root), "portuguese_transcript_count": Portuguese, "transaction_related_interactions": relevant_a, "complaint_related_interactions": relevant_b, "warnings": ["Full-text content is not emitted.", "Workflow relevance uses deterministic reason-category token matching and requires validation."], "errors": []}
    (reports / "audit_manifest.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    (reports / "data_inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    (reports / "data_quality.json").write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    (reports / "DATA_QUALITY.md").write_text("# Data Quality\n\nMachine-readable results are in `data_quality.csv` and `data_quality.json`. Nulls are counted as empty values; raw data was not cleaned or modified.\n", encoding="utf-8")
    (reports / "LANGUAGE_COVERAGE.md").write_text(f"# Language Coverage\n\nTranscript rows: {transcript_rows:,}. Portuguese transcript rows: {Portuguese:,}. This is an observed detected-language field, not independent validation.\n\n{('PORTUGUESE COVERAGE = VERIFIED OBSERVED FIELD' if Portuguese else 'PORTUGUESE COVERAGE = UNKNOWN')}\n", encoding="utf-8")
    (reports / "JOIN_GRAPH.md").write_text("# Join Graph\n\n```mermaid\ngraph TD\n" + "\n".join(f"  {j['parent_dataset']} -->|{j['parent_key']}| {j['child_dataset']}" for j in joins if j["status"] == "VERIFIED RELATIONSHIP") + "\n```\n\nSee `join_quality.csv` for exact rates and status.\n", encoding="utf-8")
    (reports / "TEMPORAL_ANALYSIS.md").write_text("# Temporal Analysis\n\nDaily coverage is in `temporal_coverage.csv`. Partition/event timestamp mismatch requires partition-level comparison and is marked UNKNOWN where partition granularity is coarser than event timestamps.\n", encoding="utf-8")
    (reports / "WORKFLOW_A_FEASIBILITY.md").write_text(markdown_feasibility("A", feasibility_a), encoding="utf-8")
    (reports / "WORKFLOW_B_FEASIBILITY.md").write_text(markdown_feasibility("B", feasibility_b), encoding="utf-8")
    (reports / "EVALUATION_FEASIBILITY.md").write_text("# Evaluation Feasibility\n\n" + json.dumps(evaluation, indent=2) + "\n\nTime-based split construction is feasible in principle, but customer overlap and golden-label validity require review.\n", encoding="utf-8")
    (reports / "SECURITY_DATA_REVIEW.md").write_text(security_review(table_stats), encoding="utf-8")
    (reports / "DATA_AUDIT_EXECUTIVE_SUMMARY.md").write_text(summary(evidence, joins, table_stats, languages, feasibility_a, feasibility_b, evaluation), encoding="utf-8")
    return 0


def feasibility(name, checks):
    rows = []
    for criterion, value, threshold in checks:
        if value is None:
            status = "UNKNOWN"
        elif isinstance(value, (int, float)) and ((threshold == ">=95%" and value >= 95) or (threshold == ">=1000" and value >= 1000) or (threshold == ">0" and value > 0)):
            status = "PASS"
        elif isinstance(value, str) and value:
            status = "PASS"
        else:
            status = "PARTIAL"
        rows.append({"workflow": name, "criterion": criterion, "metric": criterion, "value": value, "threshold": threshold, "status": status, "evidence": "observed schema and deterministic scan", "limitations": "reason matching is exploratory"})
    return rows


def markdown_feasibility(name, rows):
    lines = [f"# Workflow {name} Feasibility", "", "| Criterion | Value | Threshold | Status |", "|---|---:|---:|---|"]
    lines.extend(f"| {row['criterion']} | {row['value']} | {row['threshold']} | {row['status']} |" for row in rows)
    return "\n".join(lines) + "\n"


def security_review(table_stats):
    lines = ["# Security and Privacy Data Review", "", "No sensitive values are emitted.", "", "| Dataset | Column pattern | Risk | Handling |", "|---|---|---|---|"]
    for table, stats in sorted(table_stats.items()):
        for column in stats["columns"]:
            if PII_RE.search(column):
                risk = "PII or free-text" if re.search(r"email|phone|address|name|document|birth", column, re.I) else "sensitive free text"
                lines.append(f"| {table} | {column} | {risk} | Restrict access; hash or redact in derived artifacts |")
    return "\n".join(lines) + "\n"


def summary(evidence, joins, stats, languages, fa, fb, evaluation):
    verified = [f"{j['child_dataset']}.{j['child_key']} -> {j['parent_dataset']}.{j['parent_key']} ({j['match_rate_pct']}%)" for j in joins if j["status"] == "VERIFIED RELATIONSHIP"]
    return f"""# Data Audit Executive Summary

## Audit Status
EXECUTED: {evidence['audit_timestamp']}; files scanned: {evidence['files_scanned']}; logical datasets: {evidence['logical_datasets']}.

## Evidence
- Total rows: {sum(evidence['row_counts'].values()):,} across {len(stats)} logical datasets.
- Date coverage: see `data_inventory.csv` and `temporal_coverage.csv`; no equal-population assumption is made.
- Verified joins: {', '.join(verified) if verified else 'NONE VERIFIED'}.
- Transaction evidence: {stats.get('transactions', {}).get('rows', 0):,} transaction rows; {evidence['transaction_related_interactions']:,} interaction rows matched by exploratory reason tokens.
- Complaint evidence: {stats.get('complaints', {}).get('rows', 0):,} complaint rows; {evidence['complaint_related_interactions']:,} interaction rows matched by exploratory reason tokens.
- Transcript evidence: {stats.get('call_transcripts', {}).get('rows', 0):,} transcript rows.
- Languages: {json.dumps(dict(languages), ensure_ascii=False)}.
- Portuguese status: {'VERIFIED OBSERVED TRANSCRIPT VALUE' if evidence['portuguese_transcript_count'] else 'PORTUGUESE COVERAGE = UNKNOWN'}.
- Workflow A feasibility: see `WORKFLOW_A_FEASIBILITY.md`; no ranking assigned.
- Workflow B feasibility: see `WORKFLOW_B_FEASIBILITY.md`; no ranking assigned.
- Evaluation: A and B threshold rows are in `evaluation_feasibility.csv`; customer leakage and golden-label validity remain review items.

## Critical Blockers and Unknowns
- Exploratory reason-category matching is not a validated workflow label.
- Outcome fields do not establish correctness without manual or adjudicated labels.
- Raw free text and PII require restricted handling.
- No final workflow decision is made.
"""


if __name__ == "__main__":
    raise SystemExit(main())