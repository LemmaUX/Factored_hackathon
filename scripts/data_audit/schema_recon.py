"""Cheap, prefix-only schema reconnaissance for the raw CSV dataset."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

DATASETS = [
    "branches", "customers", "daily_exchange_rates", "marketing_campaigns",
    "products", "service_agents", "call_center_interactions", "call_transcripts",
    "campaign_sends", "complaints", "digital_events", "satisfaction_surveys",
    "transactions",
]
STATIC_DATASETS = set(DATASETS[:6])
SAMPLE_ROWS = 40
ID_RE = re.compile(r"(^|[_-])(id|key|number|no)$|(^|[_-])(id|key)([_-]|$)", re.I)
TIME_RE = re.compile(r"(^|[_-])(date|time|timestamp|created|updated|opened|closed|resolved|occurred|sent)([_-]|$)", re.I)
LANG_RE = re.compile(r"lang|locale|language", re.I)
STATUS_RE = re.compile(r"status|state|stage|outcome|result|reason|category|type|priority|disposition", re.I)
TEXT_RE = re.compile(r"text|transcript|comment|description|message|note|subject|summary|body", re.I)
BOOL_RE = re.compile(r"^(true|false|yes|no|y|n|0|1)$", re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
INT_RE = re.compile(r"^[+-]?\d+$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d+|\d+)$")


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--reports-root", type=Path, default=Path("reports/incremental"))
    parser.add_argument("--sample-rows", type=int, default=SAMPLE_ROWS)
    return parser.parse_args()


def dataset_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return relative.parts[0] if len(relative.parts) > 1 else path.stem


def partition_key(path: Path) -> tuple[int, int, int, str]:
    text = str(path)
    values = [int(match) for match in re.findall(r"(?:year|month|day)=(\d+)", text)]
    return (*((values + [0, 0, 0])[:3]), text)


def representative_files(root: Path, name: str) -> list[Path]:
    if name in STATIC_DATASETS:
        path = root / f"{name}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Missing static dataset file: {path}")
        return [path]
    paths = sorted((path for path in (root / name).rglob("*.csv") if path.is_file()), key=partition_key)
    if len(paths) < 3:
        raise RuntimeError(f"Dataset {name} has {len(paths)} CSV files; exactly 3 are required")
    return [paths[0], paths[len(paths) // 2], paths[-1]]


def semantic_type(column: str, values: list[str]) -> str:
    nonempty = [value.strip() for value in values if value.strip()]
    lower = column.lower()
    if ID_RE.search(lower):
        return "identifier"
    if LANG_RE.search(lower):
        return "categorical"
    if TIME_RE.search(lower):
        if nonempty and all(DATE_RE.match(value) for value in nonempty):
            return "date"
        return "timestamp"
    if STATUS_RE.search(lower):
        return "categorical"
    if not nonempty:
        return "string"
    if all(BOOL_RE.match(value) for value in nonempty):
        return "boolean"
    if all(INT_RE.match(value) for value in nonempty):
        return "integer"
    if all(DECIMAL_RE.match(value) for value in nonempty):
        return "decimal"
    if all(DATE_RE.match(value) for value in nonempty):
        return "date"
    if all(TIMESTAMP_RE.match(value) for value in nonempty):
        return "timestamp"
    if TEXT_RE.search(lower):
        return "string"
    return "categorical" if len(set(nonempty)) <= 20 else "string"


def read_prefix(path: Path, limit: int) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                raise ValueError("empty file: missing header")
            if not header or any(not name.strip() for name in header):
                raise ValueError("blank column name in header")
            rows = []
            widths = Counter()
            for row in reader:
                widths[len(row)] += 1
                if len(rows) < limit:
                    rows.append(row)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        raise RuntimeError(f"Could not parse prefix of {path}: {exc}") from exc
    if len(widths) > 1:
        raise RuntimeError(f"CSV parsing anomaly in sampled prefix of {path}: row widths={dict(widths)}")
    return {"header": header, "rows": rows, "sample_row_count": len(rows), "row_widths": dict(widths)}


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def main() -> int:
    started = time.perf_counter()
    options = args()
    root = options.data_root.resolve()
    output = options.reports_root.resolve()
    if options.sample_rows < 1:
        raise ValueError("--sample-rows must be positive")
    if not root.is_dir():
        raise FileNotFoundError(f"Data root does not exist: {root}")
    output.mkdir(parents=True, exist_ok=True)
    print(f"Schema reconnaissance started: root={root}", flush=True)
    records = []
    datasets = []
    files_inspected = 0
    for name in DATASETS:
        paths = representative_files(root, name)
        print(f"Inspecting {name}: {len(paths)} representative file(s)", flush=True)
        samples = []
        for path in paths:
            sample = read_prefix(path, options.sample_rows)
            files_inspected += 1
            samples.append({"path": relative(root, path), **sample})
        headers = [tuple(sample["header"]) for sample in samples]
        all_columns = list(dict.fromkeys(column for header in headers for column in header))
        columns_all = [column for column in all_columns if all(column in header for header in headers)]
        columns_some = [column for column in all_columns if column not in columns_all]
        dataset_record = {
            "dataset": name,
            "representative_files": [sample["path"] for sample in samples],
            "sample_rows_per_file": options.sample_rows,
            "sample_rows_observed": {sample["path"]: sample["sample_row_count"] for sample in samples},
            "columns": all_columns,
            "column_order": list(headers[0]),
            "columns_present_in_all_samples": columns_all,
            "columns_missing_from_some_samples": columns_some,
            "header_inconsistency": len(set(headers)) > 1,
            "row_widths": {sample["path"]: sample["row_widths"] for sample in samples},
            "schema_drift": bool(columns_some or len(set(headers)) > 1),
        }
        datasets.append(dataset_record)
        for index, column in enumerate(all_columns):
            observed = []
            per_file = {}
            for sample in samples:
                values = [row[index] for row in sample["rows"] if index < len(row)] if column in sample["header"] else []
                per_file[sample["path"]] = semantic_type(column, values) if values else "absent"
                observed.extend(values)
            inferred = semantic_type(column, observed)
            lower = column.lower()
            records.append({
                "dataset": name,
                "column_name": column,
                "column_order": headers[0].index(column) + 1 if column in headers[0] else None,
                "present_in_all_samples": column in columns_all,
                "observed_sample_type": inferred,
                "observed_nonempty_values": sum(bool(value.strip()) for value in observed),
                "observed_distinct_values_capped": min(len(set(value.strip() for value in observed if value.strip())), 100),
                "per_file_observed_types": json.dumps(per_file, sort_keys=True),
                "likely_semantic_type": inferred,
                "primary_key_candidate": bool(ID_RE.search(lower)),
                "foreign_key_candidate": bool(ID_RE.search(lower)),
                "timestamp_or_date_candidate": inferred in {"date", "timestamp"} and not bool(re.search(r"(^|[_-])(was|has|is|flag|count|score|seconds|hours)([_-]|$)", lower)),
                "status_category_reason_field": bool(STATUS_RE.search(lower)),
                "free_text_field": bool(TEXT_RE.search(lower)) and inferred == "string" and not bool(ID_RE.search(lower)),
                "language_related_field": bool(LANG_RE.search(lower)),
                "customer_identifier": bool(re.search(r"customer|client|member|account", lower) and ID_RE.search(lower)),
                "transaction_identifier": bool(re.search(r"transaction|payment|order", lower) and ID_RE.search(lower)),
                "interaction_identifier": bool(re.search(r"interaction|call|conversation", lower) and ID_RE.search(lower)),
                "complaint_identifier": bool(re.search(r"complaint|case|ticket", lower) and ID_RE.search(lower)),
                "agent_identifier": bool(re.search(r"agent|employee|representative", lower) and ID_RE.search(lower)),
                "product_identifier": bool(re.search(r"product|sku|item", lower) and ID_RE.search(lower)),
            })
    drift = [dataset for dataset in datasets if dataset["schema_drift"]]
    payload = {
        "script": "schema_recon.py",
        "script_version": "1.0",
        "data_root": str(root),
        "sample_rows_per_file": options.sample_rows,
        "files_inspected": files_inspected,
        "datasets_inspected": len(datasets),
        "datasets": datasets,
        "columns": records,
        "schema_drift_datasets": [dataset["dataset"] for dataset in drift],
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "raw_values_written": False,
    }
    csv_path = output / "02_schema_inventory.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    (output / "02_schema_inventory.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report = render_report(payload)
    (output / "SCHEMA_RECON.md").write_text(report, encoding="utf-8")
    print(f"Completed: files_inspected={files_inspected}, datasets={len(datasets)}, runtime_seconds={payload['runtime_seconds']}", flush=True)
    print(f"Schema drift datasets: {', '.join(payload['schema_drift_datasets']) or 'none observed'}", flush=True)
    return 0


def render_report(payload: dict) -> str:
    fields = payload["columns"]
    def names(predicate):
        return ", ".join(f"`{row['dataset']}.{row['column_name']}`" for row in fields if predicate(row)) or "None observed in sampled headers"
    lines = [
        "# Schema Reconnaissance", "", "## Scope", "",
        f"Prefix-only reconnaissance inspected {payload['files_inspected']} files across {payload['datasets_inspected']} datasets. Each static CSV contributed one prefix; each partitioned dataset contributed earliest, middle, and latest paths. Sample size was {payload['sample_rows_per_file']} rows per file where available. Raw values were not written.", "",
        f"Runtime: {payload['runtime_seconds']} seconds.", "", "## Dataset-by-dataset schema summary", "",
    ]
    for dataset in payload["datasets"]:
        lines += [f"### `{dataset['dataset']}`", "", f"Representative files: {', '.join('`' + path + '`' for path in dataset['representative_files'])}", "", f"Columns in first sample order: {', '.join('`' + column + '`' for column in dataset['column_order'])}", "", f"Columns present in all samples: {', '.join('`' + column + '`' for column in dataset['columns_present_in_all_samples']) or 'None'}", f"Columns missing from some samples: {', '.join('`' + column + '`' for column in dataset['columns_missing_from_some_samples']) or 'None'}", f"Header inconsistency: {'YES' if dataset['header_inconsistency'] else 'No'}", ""]
    lines += ["## Relevant fields for Workflow A", "", "Transaction identifiers: " + names(lambda row: row["transaction_identifier"]), "Customer identifiers: " + names(lambda row: row["customer_identifier"]), "Product identifiers: " + names(lambda row: row["product_identifier"]), "Interaction identifiers: " + names(lambda row: row["interaction_identifier"]), "Status/category/reason fields: " + names(lambda row: row["status_category_reason_field"]), "", "## Relevant fields for Workflow B", "", "Complaint identifiers: " + names(lambda row: row["complaint_identifier"]), "Customer identifiers: " + names(lambda row: row["customer_identifier"]), "Interaction identifiers: " + names(lambda row: row["interaction_identifier"]), "Agent identifiers: " + names(lambda row: row["agent_identifier"]), "Status/category/reason fields: " + names(lambda row: row["status_category_reason_field"]), "", "## Candidate timestamp, language, and text fields", "", "Timestamp/date candidates: " + names(lambda row: row["timestamp_or_date_candidate"]), "Language-related fields: " + names(lambda row: row["language_related_field"]), "Free-text fields: " + names(lambda row: row["free_text_field"]), "", "## Candidate join keys", "", "Identifier-like columns are candidates only; relationships were not tested: " + names(lambda row: row["primary_key_candidate"] or row["foreign_key_candidate"]), "", "## Schema drift findings", "", "Schema drift datasets: " + (", ".join('`' + name + '`' for name in payload["schema_drift_datasets"]) or "None observed"), "", "No full-file scan was performed. Parsing anomalies outside sampled prefixes, nullability, value distributions, key uniqueness, joins, and semantic validation remain unknown.", "", "## Unknowns requiring actual data scans", "", "- Complete row counts and complete distinct-value counts.", "- Full-file schema drift and malformed records outside the sampled prefixes.", "- Primary-key uniqueness and foreign-key validity.", "- Timestamp validity, partition alignment, language coverage, workflow labels, and leakage.", "- PII presence in values; this report contains column metadata only.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SCHEMA_RECON_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)