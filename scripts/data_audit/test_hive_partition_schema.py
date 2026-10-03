"""Regression tests for the Round 2 real-data audit failure (DuckDB/Hive schema).

Root cause (verified read-only against the real dataset):
    transactions/ is Hive-partitioned as year=YYYY/month=MM/day=DD and every physical
    CSV contains EXACTLY 22 columns. DuckDB's `hive_partitioning=true` additionally
    exposes three VIRTUAL columns (day, month, year), so the sniffed query-visible
    relation has 25 columns. The old code fed all 25 names into the PHYSICAL
    `read_csv(..., columns={...})` map, which made DuckDB expect 25 physical fields per
    row and abort on the 22-field files.

These tests build a tiny synthetic Hive-partitioned transaction tree (22 physical
columns) under tmp_path. NO raw data is read; no production artifact is written.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import targeted_evidence as te  # noqa: E402


# The 22 physical CSV columns of the real transactions dataset (schema_recon verified).
TRANSACTION_PHYSICAL_COLUMNS = [
    "transaction_id", "transaction_date", "process_date", "product_id", "customer_id",
    "transaction_type", "transaction_category", "amount", "currency", "amount_usd",
    "channel", "branch_id", "merchant_name", "merchant_category", "transaction_country",
    "transaction_city", "transaction_status", "response_code", "is_fraud", "fraud_score",
    "latitude", "longitude",
]
HIVE_KEYS = ["day", "month", "year"]


def _row(prefix: str = "v") -> list[str]:
    values = {
        "transaction_id": f"{prefix}-T1", "transaction_date": "2026-01-10 09:00:00",
        "process_date": "2026-01-10", "product_id": "P1", "customer_id": "C1",
        "transaction_type": "purchase", "transaction_category": "pos", "amount": "10.50",
        "currency": "USD", "amount_usd": "10.50", "channel": "POS", "branch_id": "B1",
        "merchant_name": "MERCADO", "merchant_category": "retail", "transaction_country": "MX",
        "transaction_city": "CDMX", "transaction_status": "Approved", "response_code": "00",
        "is_fraud": "false", "fraud_score": "0.01", "latitude": "19.43", "longitude": "-99.13",
    }
    return [values[column] for column in TRANSACTION_PHYSICAL_COLUMNS]


def _write_partition(data_root: Path, year: str, month: str, day: str, rows: list[list[str]],
                     header: list[str] | None = None, filename: str = "part-0.csv") -> Path:
    directory = data_root / "transactions" / f"year={year}" / f"month={month}" / f"day={day}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header or TRANSACTION_PHYSICAL_COLUMNS)
        for row in rows:
            writer.writerow(row)
    return path


@pytest.fixture()
def hive_tree(tmp_path):
    """Synthetic Hive-partitioned transactions tree: 22 physical columns, 2 partitions."""
    _write_partition(tmp_path, "2026", "01", "10", [_row("A")])
    _write_partition(tmp_path, "2026", "01", "11", [_row("B")])
    # snapshot production paths, restore them on teardown (no global mutation leaks)
    saved = (te.DATA, te.REPORTS, te.CACHE_ROOT, te.DB_PATH)
    te.configure_paths(data_root=tmp_path / "data", reports_dir=tmp_path / "reports",
                       cache_root=tmp_path / "cache")
    try:
        yield tmp_path
    finally:
        te.DATA, te.REPORTS, te.CACHE_ROOT, te.DB_PATH = saved


def _hive_source(hive_tree: Path) -> str:
    """DuckDB-readable glob over the synthetic Hive tree (year=*/month=*/day=*/*.csv)."""
    return str(hive_tree / "data" / "transactions" / "year=*" / "month=*" / "day=*" / "*.csv")


def _physical_column_map(source: str, hive_partitioning: bool) -> tuple[list[str], list[str]]:
    """Return (sniffed query-visible columns, physical columns chosen by the fix)."""
    con = duckdb.connect()
    try:
        sniffed = [r[0] for r in con.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv('{source}', header=true, "
            f"union_by_name=true, sample_size=-1, hive_partitioning={hive_partitioning}))").fetchall()]
        return sniffed, te.physical_column_names(sniffed, hive_partitioning)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 1. The sniffed relation has 25 columns but only 22 are physical
# ---------------------------------------------------------------------------
def test_sniffed_relation_exposes_25_columns_but_only_22_are_physical(hive_tree):
    sniffed, physical = _physical_column_map(_hive_source(hive_tree), hive_partitioning=True)
    assert len(sniffed) == 25, f"expected 22 physical + 3 virtual = 25 query-visible columns, got {sniffed}"
    assert len(physical) == 22, "the physical columns={{...}} map must carry exactly the 22 physical columns"
    assert set(HIVE_KEYS) <= set(sniffed), "Hive keys must be present in the sniffed relation"
    assert not (set(HIVE_KEYS) & set(physical)), "day/month/year must never enter the physical columns map"
    assert physical == TRANSACTION_PHYSICAL_COLUMNS


def test_physical_column_names_is_hive_partitioning_aware():
    sniffed = TRANSACTION_PHYSICAL_COLUMNS + HIVE_KEYS
    assert te.physical_column_names(sniffed, hive_partitioning=True) == TRANSACTION_PHYSICAL_COLUMNS
    # without hive partitioning nothing is stripped (non-partitioned datasets unchanged)
    assert te.physical_column_names(TRANSACTION_PHYSICAL_COLUMNS, hive_partitioning=False) == TRANSACTION_PHYSICAL_COLUMNS
    # path artifacts such as `key=value` column names remain excluded
    assert te.physical_column_names(["a", "b=x", "day", "month", "year"], hive_partitioning=True) == ["a"]


# ---------------------------------------------------------------------------
# 2. make_cache materializes the Hive-partitioned transactions dataset
# ---------------------------------------------------------------------------
def test_make_cache_materializes_hive_transactions_with_25_query_visible_columns(hive_tree):
    con = duckdb.connect()
    try:
        counts = te.make_cache(con, hive_partitioning=True, datasets=("transactions",))
        columns = [r[0] for r in con.execute("DESCRIBE SELECT * FROM transactions").fetchall()]
        # 13 scoped DATASETS columns + __source_file + day/month/year (Hive-derived)
        assert len(columns) == 17, columns
        assert {"day", "month", "year"} <= set(columns)
        assert counts["transactions"] == 2
        rows = con.execute(
            "SELECT transaction_id, amount, currency, transaction_status, day, month, year, __source_file "
            "FROM transactions ORDER BY transaction_id").fetchall()
        assert [r[0] for r in rows] == ["A-T1", "B-T1"]
        # physical transaction fields survive materialization intact
        assert all(r[1] == "10.50" and r[2] == "USD" and r[3] == "Approved" for r in rows)
        # day/month/year come from Hive partitioning, not from the CSV body
        assert [(r[4], r[6]) for r in rows] == [(10, 2026), (11, 2026)]
        assert all(str(r[5]) == "01" for r in rows)
        assert all("/day=" in str(r[7]).replace("\\", "/") for r in rows)
    finally:
        con.close()


def test_read_csv_sql_uses_physical_columns_only_and_keeps_hive_partitioning(hive_tree, monkeypatch):
    """Assert the emitted SQL itself: 22-entry columns map, hive_partitioning=true, strict_mode=true."""
    captured: list[str] = []
    real_execute = duckdb.DuckDBPyConnection.execute

    def spy(self, query, *args, **kwargs):
        captured.append(query)
        return real_execute(self, query, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", spy)
    con = duckdb.connect()
    try:
        te.make_cache(con, hive_partitioning=True, datasets=("transactions",))
    finally:
        con.close()
    create = next(q for q in captured if q.startswith("CREATE TABLE \"transactions\""))
    mapping = create.split("columns={", 1)[1].split("}, union_by_name", 1)[0]
    names = [chunk.split(":")[0].strip().strip("'") for chunk in mapping.split(",")]
    assert len(names) == 22, names
    assert not (set(HIVE_KEYS) & set(names)), names
    assert "hive_partitioning=true" in create
    assert "strict_mode=true" in create
    assert "ignore_errors" not in create and "null_padding" not in create


# ---------------------------------------------------------------------------
# 3. A malformed physical row is NOT silently accepted
# ---------------------------------------------------------------------------
def test_malformed_physical_row_is_not_silently_accepted(hive_tree):
    # 23 physical fields in a 22-column file (extra unquoted comma)
    bad = _write_partition(hive_tree / "data", "2026", "01", "12", [_row("A") + ["EXTRA"]],
                           filename="part-bad.csv")
    con = duckdb.connect()
    try:
        with pytest.raises(Exception) as excinfo:
            te.make_cache(con, hive_partitioning=True)
        message = str(excinfo.value)
        assert "malformed" in message.lower() or "column" in message.lower(), message[:400]
        assert "strict_mode" in message or "sniffing" in message.lower(), message[:400]
    finally:
        con.close()
    assert bad.is_file(), "raw fixture file must not be rewritten to 'repair' it"


def test_too_few_physical_fields_is_not_silently_accepted(hive_tree):
    _write_partition(hive_tree / "data", "2026", "01", "12", [["only", "two", "fields"]])
    con = duckdb.connect()
    try:
        with pytest.raises(Exception):
            te.make_cache(con, hive_partitioning=True)
    finally:
        con.close()
