"""Reproducible, read-only audit of the synthetic banking dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
AUDIT_VERSION = "1.1"


def files_by_table() -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = defaultdict(list)
    for path in DATA.rglob("*.csv"):
        relative = path.relative_to(DATA)
        table = relative.parts[0] if len(relative.parts) > 1 else path.stem
        result[table].append(path)
    return {key: sorted(value) for key, value in sorted(result.items())}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return None


def number(value: str):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def read_rows(paths: list[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
            for row in csv.DictReader(handle):
                yield row


def profile_table(table: str, paths: list[Path]) -> dict:
    columns: list[str] = []
    stats: dict[str, dict] = {}
    seen_rows: set[str] = set()
    duplicate_rows = 0
    row_count = 0
    time_values: list[datetime] = []
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
            reader = csv.DictReader(handle)
            if not columns:
                columns = reader.fieldnames or []
                for column in columns:
                    stats[column] = {"null": 0, "unique": set(), "numbers": [], "times": [], "examples": []}
            for row in reader:
                row_count += 1
                fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=True)
                if fingerprint in seen_rows:
                    duplicate_rows += 1
                else:
                    seen_rows.add(fingerprint)
                for column in columns:
                    value = (row.get(column) or "").strip()
                    item = stats[column]
                    if not value:
                        item["null"] += 1
                        continue
                    item["unique"].add(value)
                    if len(item["examples"]) < 5 and not re.search(r"(email|phone|address|name|text|document)", column, re.I):
                        item["examples"].append(value[:80])
                    parsed_number = number(value)
                    if parsed_number is not None:
                        item["numbers"].append(parsed_number)
                    parsed_time = parse_time(value)
                    if parsed_time is not None and re.search(r"date|time", column, re.I):
                        item["times"].append(parsed_time)
                        time_values.append(parsed_time)
    output_columns = {}
    for column, item in stats.items():
        values = item["unique"]
        numeric = item["numbers"]
        times = item["times"]
        output_columns[column] = {
            "null_count": item["null"],
            "null_pct": round(item["null"] / row_count * 100, 4) if row_count else 0,
            "unique_count": len(values),
            "cardinality_ratio": round(len(values) / row_count, 6) if row_count else 0,
            "inferred_type": "numeric" if numeric and len(numeric) >= max(1, len(values) * 0.9) else ("timestamp" if times else "text"),
            "semantic_hints": [hint for hint, pattern in (("identifier", r"(^|_)id$|_id$"), ("timestamp", r"date|time"), ("PII-like", r"email|phone|address|name|document"), ("categorical", r"status|type|category|channel|country|language|accent")) if re.search(pattern, column, re.I)],
            "representative_values": item["examples"],
            "min": min(numeric) if numeric else (min(times).isoformat() if times else None),
            "max": max(numeric) if numeric else (max(times).isoformat() if times else None),
        }
    candidate_keys = []
    for column, item in output_columns.items():
        if re.search(r"(^|_)id$", column, re.I) and item["null_count"] == 0:
            candidate_keys.append({"column": column, "unique_count": item["unique_count"], "unique_pct": round(item["unique_count"] / row_count * 100, 4) if row_count else 0})
    return {"table": table, "files": len(paths), "rows": row_count, "columns": output_columns, "candidate_keys": candidate_keys, "exact_duplicate_rows": duplicate_rows, "time_min": min(time_values).isoformat() if time_values else None, "time_max": max(time_values).isoformat() if time_values else None}


def values(paths: list[Path], column: str) -> set[str]:
    return {(row.get(column) or "").strip() for row in read_rows(paths) if (row.get(column) or "").strip()}


def join_result(child: str, child_paths: list[Path], child_column: str, parent: str, parent_values: set[str]) -> dict:
    total = matched = 0
    multiplicity = Counter()
    for row in read_rows(child_paths):
        value = (row.get(child_column) or "").strip()
        if not value:
            continue
        total += 1
        if value in parent_values:
            matched += 1
            multiplicity[value] += 1
    counts = Counter(multiplicity.values())
    return {"child": child, "child_key": child_column, "parent": parent, "parent_rows": len(parent_values), "child_nonempty": total, "matched": matched, "unmatched": total - matched, "join_success_pct": round(matched / total * 100, 4) if total else 0, "child_per_parent": {str(k): v for k, v in sorted(counts.items())}, "relationship": "one-to-many" if any(key > 1 for key in multiplicity.values()) else "one-to-one-or-sparse"}


def distribution(paths: list[Path], column: str) -> dict[str, int]:
    counter = Counter()
    for row in read_rows(paths):
        value = (row.get(column) or "").strip() or "UNKNOWN"
        counter[value] += 1
    return dict(counter.most_common(50))


def table_columns(paths: list[Path]) -> list[str]:
    if not paths:
        return []
    with paths[0].open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
        return csv.DictReader(handle).fieldnames or []


def inferred_joins(table_paths: dict[str, list[Path]]) -> list[dict]:
    """Measure exact *_id overlaps without assuming a business relationship."""
    key_sets: dict[tuple[str, str], set[str]] = {}
    for table, paths in table_paths.items():
        columns = [column for column in table_columns(paths) if re.search(r"(^|_)id$", column, re.I)]
        if not columns:
            continue
        collected = {column: set() for column in columns}
        for row in read_rows(paths):
            for column in columns:
                value = (row.get(column) or "").strip()
                if value:
                    collected[column].add(value)
        for column, column_values in collected.items():
            key_sets[(table, column)] = column_values
    results = []
    for (child, child_key), child_values in key_sets.items():
        if not child_values:
            continue
        for (parent, parent_key), parent_values in key_sets.items():
            if child == parent or child_key != parent_key or not parent_values:
                continue
            overlap = child_values & parent_values
            if overlap:
                results.append({
                    "child": child,
                    "child_key": child_key,
                    "parent": parent,
                    "parent_key": parent_key,
                    "child_distinct": len(child_values),
                    "parent_distinct": len(parent_values),
                    "matched_distinct": len(overlap),
                    "unmatched_distinct": len(child_values - parent_values),
                    "join_success_pct": round(len(overlap) / len(child_values) * 100, 4),
                    "evidence": "exact value overlap; semantic relationship requires review",
                })
    return sorted(results, key=lambda item: (-item["join_success_pct"], item["child"], item["child_key"], item["parent"]))


def language_results(table_paths: dict[str, list[Path]]) -> dict:
    result = {}
    for table in ("call_transcripts", "call_center_interactions"):
        paths = table_paths.get(table, [])
        if not paths:
            continue
        language_column = "detected_language" if table == "call_transcripts" else "customer_detected_accent"
        counts = distribution(paths, language_column)
        total = sum(counts.values())
        portuguese = sum(value for key, value in counts.items() if re.search(r"portugu|brasil|brazil", key, re.I))
        result[table] = {
            "source_field": language_column,
            "counts": counts,
            "total": total,
            "portuguese_observed_count": portuguese,
            "portuguese_observed_pct": round(portuguese / total * 100, 4) if total else 0,
            "classification": "observed field; not independently validated",
        }
    return result


def evaluation_results(table_paths: dict[str, list[Path]], profiles: dict) -> dict:
    paths = table_paths.get("call_center_interactions", [])
    if not paths:
        return {"status": "MISSING EVIDENCE"}
    dates = []
    customer_ids = []
    for row in read_rows(paths):
        timestamp = parse_time((row.get("interaction_date") or "").strip())
        if timestamp:
            dates.append(timestamp)
        customer_id = (row.get("customer_id") or "").strip()
        if customer_id:
            customer_ids.append(customer_id)
    if not dates:
        return {"status": "MISSING EVIDENCE", "reason": "no parseable interaction_date"}
    dates.sort()
    first, last = dates[0], dates[-1]
    span = (last - first).total_seconds()
    cutoffs = {}
    for name, fraction in (("development", 0.70), ("validation", 0.85)):
        cutoff = first + (last - first) * fraction
        cutoffs[name] = cutoff.isoformat()
    customer_counts = Counter(customer_ids)
    return {
        "status": "candidate temporal split only",
        "interaction_rows": len(dates),
        "first_interaction": first.isoformat(),
        "last_interaction": last.isoformat(),
        "candidate_cutoffs": cutoffs,
        "repeated_customer_rows": sum(count - 1 for count in customer_counts.values() if count > 1),
        "unique_customers": len(customer_counts),
        "customer_overlap_requires_grouped_split": any(count > 1 for count in customer_counts.values()),
        "final_split_selected": False,
    }


def workflow_results(table_paths: dict[str, list[Path]]) -> dict:
    reasons = Counter()
    languages = Counter()
    total = 0
    for row in read_rows(table_paths.get("call_center_interactions", [])):
        total += 1
        reason = (row.get("reason_category") or row.get("contact_reason") or "UNKNOWN").strip() or "UNKNOWN"
        reasons[reason] += 1
        languages[(row.get("customer_detected_accent") or "UNKNOWN").strip() or "UNKNOWN"] += 1
    mapping = {
        "A Transaction Issue Triage and Safe Resolution": ["Transaccional", "Transaction", "Fraud", "Dispute"],
        "B Complaint Status, Intake, and Escalation": ["Queja", "Complaint", "Reclamo"],
        "C Digital Failure Recovery": ["Técnico", "Tecnico", "Digital", "Login"],
        "D Routine Account or Product Inquiry": ["Producto", "Cuenta", "Información", "Informacion"],
    }
    result = {}
    for workflow, tokens in mapping.items():
        count = sum(value for key, value in reasons.items() if any(token.lower() in key.lower() for token in tokens))
        result[workflow] = {"interaction_volume": count, "share_pct": round(count / total * 100, 4) if total else 0, "evidence": "deterministic reason_category/contact_reason match; requires manual validation", "confidence": "medium"}
    result["Observed reason distribution"] = dict(reasons.most_common())
    result["Accent distribution"] = dict(languages.most_common())
    return result


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    table_paths = files_by_table()
    inventory = []
    file_hashes = {}
    for table, paths in table_paths.items():
        for path in paths:
            stat = path.stat()
            file_hashes[str(path.relative_to(ROOT))] = {"bytes": stat.st_size, "sha256": sha256(path)}
        inventory.append({"table": table, "files": len(paths), "bytes": sum(path.stat().st_size for path in paths), "rows": "profiled below", "time_range": "profiled below"})
    profiles = {table: profile_table(table, paths) for table, paths in table_paths.items()}
    customer_ids = values(table_paths.get("customers", []), "customer_id")
    agent_ids = values(table_paths.get("service_agents", []), "agent_id")
    interaction_ids = values(table_paths.get("call_center_interactions", []), "interaction_id")
    joins = []
    candidates = [("call_center_interactions", "customer_id", "customers", customer_ids), ("call_center_interactions", "agent_id", "service_agents", agent_ids), ("call_transcripts", "interaction_id", "call_center_interactions", interaction_ids), ("call_transcripts", "customer_id", "customers", customer_ids), ("products", "customer_id", "customers", customer_ids)]
    for child, key, parent, parent_values in candidates:
        if table_paths.get(child):
            joins.append(join_result(child, table_paths[child], key, parent, parent_values))
    inferred = inferred_joins(table_paths)
    joins.extend(inferred)
    languages = language_results(table_paths)
    evaluation = evaluation_results(table_paths, profiles)
    workflow = workflow_results(table_paths)
    evidence = {"audit_version": AUDIT_VERSION, "execution_utc": datetime.utcnow().isoformat() + "Z", "python": sys.version, "raw_file_count": len(file_hashes), "raw_files": file_hashes, "inventory": inventory, "profiles": profiles, "joins": joins, "inferred_joins": inferred, "language_results": languages, "evaluation_feasibility": evaluation, "workflow_results": workflow, "distributions": {table: {column: distribution(paths, column) for column in ("status", "product_type", "reason_category", "detected_language", "event_type", "error_code", "channel") if paths} for table, paths in table_paths.items()}}
    (REPORTS / "DATA_PROFILE.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (REPORTS / "JOIN_RESULTS.json").write_text(json.dumps(joins, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "LANGUAGE_RESULTS.json").write_text(json.dumps(languages, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "WORKFLOW_RESULTS.json").write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    write_reports(evidence)
    return 0


def write_reports(evidence: dict) -> None:
    profiles = evidence["profiles"]
    joins = evidence["joins"]
    inferred = evidence["inferred_joins"]
    languages = evidence["language_results"]
    evaluation = evidence["evaluation_feasibility"]
    workflow = evidence["workflow_results"]
    inventory_lines = ["| Asset | Files | Bytes | Rows | Time range |", "|---|---:|---:|---:|---|"]
    for item in evidence["inventory"]:
        profile = profiles[item["table"]]
        inventory_lines.append(f"| `{item['table']}` | {item['files']} | {item['bytes']:,} | {profile['rows']:,} | {profile['time_min'] or 'UNKNOWN'} to {profile['time_max'] or 'UNKNOWN'} |")
    join_lines = ["| Child | Key | Parent | Matched | Unmatched | Success | Relationship |", "|---|---|---|---:|---:|---:|---|"]
    for item in joins:
        join_lines.append(f"| {item['child']} | `{item['child_key']}` | {item['parent']} | {item['matched']:,} | {item['unmatched']:,} | {item['join_success_pct']}% | {item['relationship']} |")
    workflow_lines = ["| Candidate | Volume | Share | Confidence |", "|---|---:|---:|---|"]
    for name, item in workflow.items():
        if isinstance(item, dict) and "interaction_volume" in item:
            workflow_lines.append(f"| {name} | {item['interaction_volume']:,} | {item['share_pct']}% | {item['confidence']} |")
    report = f"""# Data Audit

## 1. Executive Summary
Generated by `scripts/audit/run_audit.py` from read-only raw CSV files. No workflow is selected. Candidate volumes are deterministic matches against observed interaction reason fields and are evidence for architecture review, not ground-truth labels.

## 2. Dataset Inventory
{chr(10).join(inventory_lines)}

Raw immutability: inputs are only read. SHA-256 hashes and execution metadata are stored in `DATA_PROFILE.json`.

## 3. Schema Findings
The machine-readable profile records columns, null counts, cardinality, inferred physical type, timestamps, examples with PII-like columns excluded, and semantic hints. Candidate identifiers are reported per table. No fields were invented.

## 4. Data Quality
Null counts, exact duplicate row counts, numeric ranges, and timestamp ranges are in `DATA_PROFILE.json`. Empty values are counted as missing; no coercion, deduplication, normalization, or orphan filtering is applied.

## 5. Duplicate Analysis
Exact duplicate rows are counted per table. Candidate key uniqueness is reported but no survivorship rule is applied. Fuzzy duplicate detection is **MISSING EVIDENCE**.

## 6. Referential Integrity
{chr(10).join(join_lines)}

Unmatched records remain in the raw source and are unresolved for dependent workflows; they are not silently discarded.

## 7. Join Graph
```mermaid
graph TD
{chr(10).join(f"  {item['parent']} -->|{item['parent_key']}| {item['child']}" for item in inferred[:30])}
```
Only exact-overlap edges are shown; they remain relationship hypotheses until semantic and temporal validation.

## 8. Temporal Analysis
Minimum and maximum detected timestamps are reported per table. Event/ingestion latency, temporal gaps, daily rates, and a final cutoff are **MISSING EVIDENCE** where source fields do not support them. A temporal split must be selected only after volume and customer-overlap review.

## 9. Language Analysis
{json.dumps(languages, indent=2, ensure_ascii=False)}
Language counts come from observed fields. Accent is not equivalent to language; Portuguese support is not claimed without an explicit observed Portuguese value.

## 10. Transcript Analysis
Transcript linkage, text-field null rates, model-derived fields, and duration ranges are in the profile. Full text is not emitted. Intent/topic fields require validation.

## 11. Interaction/Intent Analysis
Observed reason distributions and workflow matching are in `WORKFLOW_RESULTS.json`. Candidate categories are exploratory string matches, not validated intent labels; a reproducible annotation study is still required.

## 12. Transaction Analysis
Transaction schema, statuses, amounts, currencies, timestamps, and customer linkage are profiled when present. Relevance of a transaction to a customer complaint is **MISSING EVIDENCE** unless an explicit interaction/complaint transaction key exists.

## 13. Complaint Analysis
Complaint fields and linkage are profiled when present. Complaint resolution correctness and escalation success are **MISSING EVIDENCE** unless explicit outcome fields are populated.

## 14. Digital Event Analysis
Event/error distributions and available keys are profiled. Temporal correlation to interactions is **MISSING EVIDENCE** in this baseline because it requires a controlled window analysis over both timestamp columns.

## 15. Outcome/Label Analysis
`was_resolved`, `was_escalated`, `requires_followup`, and satisfaction fields, where present, are observed or proxy outcomes. They are not treated as correctness ground truth. Direct outcome labels and annotation counts are **MISSING EVIDENCE**.

## 16. Workflow Discovery
{chr(10).join(workflow_lines)}

No new workflow is proposed without a validated, significant cluster outside these exploratory matches. The complete observed reason distribution is in `WORKFLOW_RESULTS.json`.

## 17. Candidate Comparison
Demand evidence is available above. Scores for business relevance, AI applicability, tool feasibility, multilingual feasibility, security testability, and ten-day feasibility remain **UNKNOWN** until ownership, outcome, and annotation evidence are reviewed.

## 18. Evaluation Feasibility
{json.dumps(evaluation, indent=2, ensure_ascii=False)}
These are candidate temporal boundaries only. No final split is created, and repeated customers require leakage review or grouped splitting.

## 19. Security/Safety Findings
PII-like columns are flagged in the profile without exposing representative values. Missing identity, unmatched ownership, contradictory states, malformed text, and injection-like text require explicit safety fixtures; full adversarial analysis is **MISSING EVIDENCE**.

## 20. Critical Unknowns
- Whether interaction reasons are human-validated or generated.
- Whether transaction, complaint, digital-event, campaign, survey, and interaction keys overlap at useful rates.
- Portuguese language count among relevant interactions, independently of accent.
- Whether resolution/escalation fields measure correct outcomes.
- Whether temporal and customer-grouped evaluation splits avoid leakage.
- Fuzzy duplicates, injection-like text, contradictory records, and safe ownership evidence.

## 21. Recommended Next Gate
Review `DATA_PROFILE.json`, `JOIN_RESULTS.json`, and `WORKFLOW_RESULTS.json`; then run targeted linkage, temporal correlation, and manual annotation checks before architecture chooses a workflow.

FINAL WORKFLOW SELECTION: PENDING ARCHITECTURE REVIEW
"""
    (REPORTS / "DATA_AUDIT.md").write_text(report, encoding="utf-8")
    graph = "\n".join(f"  {item['parent']} -->|{item['parent_key']}| {item['child']}" for item in inferred[:30])
    (REPORTS / "JOIN_GRAPH.md").write_text(f"# Join Graph\n\nMeasured exact-overlap edges are in `JOIN_RESULTS.json`; they are relationship hypotheses, not guaranteed business joins.\n\n```mermaid\ngraph TD\n{graph}\n```\n", encoding="utf-8")
    (REPORTS / "WORKFLOW_DISCOVERY.md").write_text("# Workflow Discovery\n\nCandidate volumes, observed reason distributions, language coverage, and unknowns are in `DATA_PROFILE.json` and `WORKFLOW_RESULTS.json`. These are exploratory evidence, not a final selection.\n\nFINAL WORKFLOW SELECTION: PENDING ARCHITECTURE REVIEW\n", encoding="utf-8")
    (REPORTS / "EVALUATION_FEASIBILITY.md").write_text(f"# Evaluation Feasibility\n\n```json\n{json.dumps(evaluation, indent=2, ensure_ascii=False)}\n```\n\nNo final split was created. Customer overlap and label validity require review before evaluation.\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
