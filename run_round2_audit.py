from pathlib import Path
import duckdb
import pandas as pd

# ============================================================
# CONFIGURATION
# ============================================================

REPO_DIR = Path(__file__).resolve().parent

# CHANGE THIS ONLY IF NECESSARY
DATA_DIR = Path(
    r"C:\Users\anali\OneDrive\Desktop\Senior\Factored_hackton\data"
)

OUTPUT_DIR = REPO_DIR / "round2_artifacts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not DATA_DIR.exists():
    raise FileNotFoundError(f"DATA_DIR does not exist: {DATA_DIR}")

print(f"Repository : {REPO_DIR}")
print(f"Dataset    : {DATA_DIR}")
print(f"Output     : {OUTPUT_DIR}")

con = duckdb.connect()

# Conservative settings
con.execute("SET threads=4")


# ============================================================
# HELPERS
# ============================================================

def files(pattern):
    return str(DATA_DIR / "**" / pattern)


def run_df(name, query):
    print(f"\n[RUN] {name}")
    df = con.execute(query).df()
    path = OUTPUT_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"[OK]  {path}")
    print(df.head(10).to_string(index=False))
    return df


# ============================================================
# 0. SCHEMA SANITY CHECK
# ============================================================

schema_query = f"""
DESCRIBE SELECT *
FROM read_csv_auto('{files("transactions*.csv")}')
LIMIT 1
"""

schema = con.execute(schema_query).df()
schema.to_csv(OUTPUT_DIR / "transactions_schema.csv", index=False)

print("\n=== TRANSACTIONS SCHEMA ===")
print(schema[["column_name", "column_type"]].to_string(index=False))


# ============================================================
# 1. FK RECONCILIATION
# ============================================================

# 1A complaints -> interactions
#
# Important:
# We test exact equality and normalized equality.
# Prefix coincidence is NOT treated as a relationship.

q1 = f"""
WITH complaints AS (
    SELECT DISTINCT
        CAST(origin_interaction_id AS VARCHAR) AS child_id
    FROM read_csv_auto('{files("complaints*.csv")}')
    WHERE origin_interaction_id IS NOT NULL
),
interactions AS (
    SELECT DISTINCT
        CAST(interaction_id AS VARCHAR) AS parent_id
    FROM read_csv_auto('{files("call_center_interactions*.csv")}')
),
exact_match AS (
    SELECT COUNT(*) AS n
    FROM complaints c
    INNER JOIN interactions i
        ON c.child_id = i.parent_id
),
normalized_match AS (
    SELECT COUNT(*) AS n
    FROM complaints c
    INNER JOIN interactions i
        ON regexp_replace(c.child_id, '^INT[-_]', '')
         = regexp_replace(i.parent_id, '^INT[-_]', '')
)
SELECT
    (SELECT COUNT(*) FROM complaints) AS distinct_child_keys,
    (SELECT COUNT(*) FROM interactions) AS distinct_parent_keys,
    exact_match.n AS exact_matches,
    normalized_match.n AS normalized_matches
FROM exact_match, normalized_match
"""

run_df("fk_reconciliation_complaints", q1)


# 1B digital_events -> transactions

q2 = f"""
WITH events AS (
    SELECT DISTINCT
        CAST(transaction_id AS VARCHAR) AS child_id
    FROM read_csv_auto('{files("digital_events*.csv")}')
    WHERE transaction_id IS NOT NULL
),
transactions AS (
    SELECT DISTINCT
        CAST(transaction_id AS VARCHAR) AS parent_id
    FROM read_csv_auto('{files("transactions*.csv")}')
),
exact_match AS (
    SELECT COUNT(*) AS n
    FROM events e
    INNER JOIN transactions t
        ON e.child_id = t.parent_id
),
normalized_match AS (
    SELECT COUNT(*) AS n
    FROM events e
    INNER JOIN transactions t
        ON regexp_replace(e.child_id, '^TRX[-_]', '')
         = regexp_replace(t.parent_id, '^TRX[-_]', '')
)
SELECT
    (SELECT COUNT(*) FROM events) AS distinct_child_keys,
    (SELECT COUNT(*) FROM transactions) AS distinct_parent_keys,
    exact_match.n AS exact_matches,
    normalized_match.n AS normalized_matches
FROM exact_match, normalized_match
"""

run_df("fk_reconciliation_digital", q2)


# ============================================================
# 2. DUPLICATE VALIDATION
# ============================================================

tables = {
    "transactions": "transaction_id",
    "call_center_interactions": "interaction_id",
    "call_transcripts": "transcript_id",
    "complaints": "complaint_id",
    "satisfaction_surveys": "survey_id",
    "digital_events": "event_id",
}

duplicate_results = []

for table, pk in tables.items():

    pattern = files(f"{table}*.csv")

    query = f"""
    WITH base AS (
        SELECT *
        FROM read_csv_auto('{pattern}')
    ),
    pk_stats AS (
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT {pk}) AS distinct_pk
        FROM base
    )
    SELECT
        '{table}' AS dataset,
        total_rows,
        distinct_pk,
        total_rows - distinct_pk AS duplicate_pk_rows
    FROM pk_stats
    """

    df = con.execute(query).df()
    duplicate_results.append(df)

duplicates = pd.concat(duplicate_results, ignore_index=True)
duplicates.to_csv(
    OUTPUT_DIR / "duplicate_validation.csv",
    index=False
)

print("\n=== PRIMARY KEY DUPLICATES ===")
print(duplicates.to_string(index=False))


# ============================================================
# 3. WORKFLOW A — COHORT CHARACTERIZATION
# ============================================================

q3a = f"""
SELECT
    contact_reason,
    reason_category,
    was_resolved,
    was_escalated,
    has_transcript,
    COUNT(*) AS interaction_count,
    ROUND(
        100.0 * COUNT(*) /
        SUM(COUNT(*)) OVER (),
        2
    ) AS pct_of_total
FROM read_csv_auto('{files("call_center_interactions*.csv")}')
GROUP BY
    contact_reason,
    reason_category,
    was_resolved,
    was_escalated,
    has_transcript
ORDER BY interaction_count DESC
"""

run_df("workflow_a_cohorts", q3a)


# ============================================================
# 4. TRANSACTION-RELATED REASON DISTRIBUTION
# ============================================================

q4 = f"""
SELECT
    contact_reason,
    reason_category,
    COUNT(*) AS interaction_count,
    SUM(CASE WHEN has_transcript THEN 1 ELSE 0 END)
        AS transcript_count,
    SUM(CASE WHEN was_resolved THEN 1 ELSE 0 END)
        AS resolved_count,
    SUM(CASE WHEN was_escalated THEN 1 ELSE 0 END)
        AS escalated_count
FROM read_csv_auto('{files("call_center_interactions*.csv")}')
WHERE
    LOWER(CAST(reason_category AS VARCHAR)) LIKE '%transaction%'
    OR LOWER(CAST(contact_reason AS VARCHAR)) LIKE '%transaction%'
GROUP BY
    contact_reason,
    reason_category
ORDER BY interaction_count DESC
"""

run_df("workflow_a_transaction_reasons", q4)


# ============================================================
# 5. TEMPORAL PROFILE — TRANSACTIONS
# ============================================================

# First inspect whether process_date exists.

transaction_columns = set(schema["column_name"].astype(str))

if "process_date" in transaction_columns:

    q5 = f"""
    SELECT
        MIN(transaction_date) AS min_event_date,
        MAX(transaction_date) AS max_event_date,
        MIN(process_date) AS min_process_date,
        MAX(process_date) AS max_process_date,
        SUM(
            CASE
                WHEN transaction_date > process_date
                THEN 1 ELSE 0
            END
        ) AS event_after_process_count,
        COUNT(DISTINCT customer_id) AS unique_customers
    FROM read_csv_auto('{files("transactions*.csv")}')
    """

else:

    q5 = f"""
    SELECT
        MIN(transaction_date) AS min_event_date,
        MAX(transaction_date) AS max_event_date,
        NULL AS min_process_date,
        NULL AS max_process_date,
        NULL AS event_after_process_count,
        COUNT(DISTINCT customer_id) AS unique_customers
    FROM read_csv_auto('{files("transactions*.csv")}')
    """

run_df("temporal_transactions", q5)


# ============================================================
# 6. COMPLAINT LIFECYCLE
# ============================================================

q6 = f"""
SELECT
    COUNT(*) AS total_complaints,

    SUM(
        CASE WHEN resolution_date IS NOT NULL
        THEN 1 ELSE 0 END
    ) AS resolved_count,

    SUM(
        CASE WHEN resolution_date IS NULL
        THEN 1 ELSE 0 END
    ) AS unresolved_count,

    SUM(
        CASE
            WHEN resolution_date IS NOT NULL
             AND creation_date IS NOT NULL
             AND resolution_date < creation_date
            THEN 1 ELSE 0
        END
    ) AS negative_resolution_lag,

    MIN(creation_date) AS min_creation_date,
    MAX(creation_date) AS max_creation_date,
    MIN(resolution_date) AS min_resolution_date,
    MAX(resolution_date) AS max_resolution_date

FROM read_csv_auto('{files("complaints*.csv")}')
"""

run_df("temporal_complaints", q6)


# ============================================================
# 7. CUSTOMER TEMPORAL OVERLAP
# ============================================================

q7 = f"""
WITH yearly AS (
    SELECT DISTINCT
        EXTRACT(YEAR FROM interaction_date) AS year,
        customer_id
    FROM read_csv_auto('{files("call_center_interactions*.csv")}')
    WHERE interaction_date IS NOT NULL
),
year_counts AS (
    SELECT
        year,
        COUNT(*) AS customers
    FROM yearly
    GROUP BY year
)
SELECT *
FROM year_counts
ORDER BY year
"""

run_df("temporal_customer_counts", q7)


# ============================================================
# 8. LANGUAGE COVERAGE
# ============================================================

q8 = f"""
SELECT
    detected_language,
    COUNT(*) AS transcript_count,
    ROUND(
        100.0 * COUNT(*) /
        SUM(COUNT(*)) OVER (),
        2
    ) AS percentage
FROM read_csv_auto('{files("call_transcripts*.csv")}')
GROUP BY detected_language
ORDER BY transcript_count DESC
"""

run_df("language_coverage_round2", q8)


# ============================================================
# 9. FINAL MANIFEST
# ============================================================

manifest = pd.DataFrame([
    {
        "artifact": p.name,
        "path": str(p.relative_to(REPO_DIR)),
        "size_bytes": p.stat().st_size
    }
    for p in sorted(OUTPUT_DIR.glob("*.csv"))
])

manifest.to_csv(
    OUTPUT_DIR / "round2_manifest.csv",
    index=False
)

print("\n========================================")
print("ROUND 2 AUDIT COMPLETE")
print("========================================")
print(manifest.to_string(index=False))

con.close()