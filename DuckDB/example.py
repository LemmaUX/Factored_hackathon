import duckdb

DATA_DIR = r"C:\Users\anali\OneDrive\Desktop\Senior\Factored_hackton\data"

con = duckdb.connect()

q = f"""
WITH transactional_transcripts AS (
    SELECT
        t.transcript_id,
        i.customer_id,
        t.customer_text,

        CASE
            WHEN lower(t.customer_text) LIKE '%cuenta de ahorros%'
                THEN 'Cuenta Ahorro'
            WHEN lower(t.customer_text) LIKE '%tarjeta de crédito%'
                THEN 'Tarjeta Crédito'
            ELSE NULL
        END AS expected_product_type

    FROM read_csv_auto(
        '{DATA_DIR}\\**\\call_transcripts*.csv'
    ) t
    INNER JOIN read_csv_auto(
        '{DATA_DIR}\\**\\call_center_interactions*.csv'
    ) i
        ON t.interaction_id = i.interaction_id

    WHERE i.contact_reason = 'Transaccional'
      AND t.customer_text IS NOT NULL
),

product_counts AS (
    SELECT
        t.transcript_id,
        t.customer_id,
        t.expected_product_type,
        COUNT(p.product_id) AS compatible_product_count
    FROM transactional_transcripts t
    LEFT JOIN read_csv_auto(
        '{DATA_DIR}\\**\\products*.csv'
    ) p
        ON p.customer_id = t.customer_id
       AND p.product_type = t.expected_product_type
    GROUP BY
        t.transcript_id,
        t.customer_id,
        t.expected_product_type
)

SELECT
    CASE
        WHEN compatible_product_count = 0
            THEN 'NO_PRODUCT'
        WHEN compatible_product_count = 1
            THEN 'UNIQUE_PRODUCT'
        ELSE 'MULTIPLE_PRODUCTS'
    END AS resolution_class,

    expected_product_type,

    COUNT(*) AS transcripts,
    COUNT(DISTINCT customer_id) AS customers,

    ROUND(
        100.0 * COUNT(*) /
        SUM(COUNT(*)) OVER (
            PARTITION BY expected_product_type
        ),
        2
    ) AS pct_within_product_type

FROM product_counts
GROUP BY
    expected_product_type,
    resolution_class
ORDER BY
    expected_product_type,
    resolution_class;
"""

print("=== NATIVE PRODUCT RESOLUTION VALIDATION ===")
print(con.execute(q).df().to_string(index=False))