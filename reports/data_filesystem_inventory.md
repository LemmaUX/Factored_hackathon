# Data Filesystem Inventory

## Scope and method

This report was produced from filesystem metadata under `data/` only. The scan used recursive file and directory metadata (`path`, `name`, `extension`, and byte length). CSV contents were not opened, and no DuckDB, row counting, schema inference, data-value inspection, copying, normalization, or audit stage was run.

Scan status: **SUCCESS**  
Elapsed scan time: less than 5 minutes  
Root: `data/`

## Overall totals

| Metric | Value |
|---|---:|
| Total files | 7,671 |
| CSV files | 7,671 |
| Total size (bytes) | 5,349,322,481 |
| Total size (GB, decimal) | 5.349 |
| Total size (GiB) | 4.982 |
| Recursive directories | 7,958 |
| Zero-byte files | 0 |
| Files smaller than 1 KB | 0 |
| Files larger than 100 MB | 0 |
| File extensions | `.csv` only |

## Logical datasets

Logical names are the first directory component for partitioned families and the filename stem for root-level CSVs. `First path` and `Last path` are lexicographic filesystem paths, not event-time bounds.

| Dataset | CSV files | Total bytes | First path | Last path | Year/month/day partitioned |
|---|---:|---:|---|---|---|
| branches | 1 | 89,529 | `branches.csv` | `branches.csv` | No |
| customers | 1 | 46,897,358 | `customers.csv` | `customers.csv` | No |
| daily_exchange_rates | 1 | 778,914 | `daily_exchange_rates.csv` | `daily_exchange_rates.csv` | No |
| marketing_campaigns | 1 | 32,710 | `marketing_campaigns.csv` | `marketing_campaigns.csv` | No |
| products | 1 | 68,213,646 | `products.csv` | `products.csv` | No |
| service_agents | 1 | 237,992 | `service_agents.csv` | `service_agents.csv` | No |
| call_center_interactions | 1,097 | 139,734,950 | `call_center_interactions/year=2023/month=06/day=17/call_center_interactions_20230617.csv` | `call_center_interactions/year=2026/month=06/day=17/call_center_interactions_20260617.csv` | Yes |
| call_transcripts | 1,097 | 137,235,657 | `call_transcripts/year=2023/month=06/day=17/call_transcripts_20230617.csv` | `call_transcripts/year=2026/month=06/day=17/call_transcripts_20260617.csv` | Yes |
| campaign_sends | 1,083 | 325,976,325 | `campaign_sends/year=2023/month=07/day=01/campaign_sends_20230701.csv` | `campaign_sends/year=2026/month=06/day=17/campaign_sends_20260617.csv` | Yes |
| complaints | 1,097 | 17,990,612 | `complaints/year=2023/month=06/day=17/complaints_20230617.csv` | `complaints/year=2026/month=06/day=17/complaints_20260617.csv` | Yes |
| digital_events | 1,097 | 3,757,355,051 | `digital_events/year=2023/month=06/day=17/digital_events_20230617.csv` | `digital_events/year=2026/month=06/day=17/digital_events_20260617.csv` | Yes |
| satisfaction_surveys | 1,097 | 46,446,098 | `satisfaction_surveys/year=2023/month=06/day=17/satisfaction_surveys_20230617.csv` | `satisfaction_surveys/year=2026/month=06/day=17/satisfaction_surveys_20260617.csv` | Yes |
| transactions | 1,097 | 808,333,639 | `transactions/year=2023/month=06/day=17/transactions_20230617.csv` | `transactions/year=2026/month=06/day=17/transactions_20260617.csv` | Yes |

## Partition coverage

| Property | Filesystem observation |
|---|---|
| Minimum year directory | 2023 |
| Maximum year directory | 2026 |
| Available years | 2023, 2024, 2025, 2026 |
| Available month directories | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 |
| Day partitions | Present; 7,665 `day=NN` directories |
| Dataset families with day partitions | call_center_interactions, call_transcripts, campaign_sends, complaints, digital_events, satisfaction_surveys, transactions |

The directory scan does not establish that every year/month/day combination exists for every dataset, nor that partition dates match timestamps inside files. Those questions require reading data values and are intentionally **UNKNOWN** here.

## Largest 20 logical datasets by total size

| Rank | Dataset | Total bytes |
|---:|---|---:|
| 1 | digital_events | 3,757,355,051 |
| 2 | transactions | 808,333,639 |
| 3 | campaign_sends | 325,976,325 |
| 4 | call_center_interactions | 139,734,950 |
| 5 | call_transcripts | 137,235,657 |
| 6 | products | 68,213,646 |
| 7 | customers | 46,897,358 |
| 8 | satisfaction_surveys | 46,446,098 |
| 9 | complaints | 17,990,612 |
| 10 | daily_exchange_rates | 778,914 |
| 11 | service_agents | 237,992 |
| 12 | branches | 89,529 |
| 13 | marketing_campaigns | 32,710 |

Only 13 logical datasets exist, so ranks 14 through 20 are not applicable.

## Largest 20 individual CSV files

| Rank | Size (bytes) | Path |
|---:|---:|---|
| 1 | 68,213,646 | `products.csv` |
| 2 | 46,897,358 | `customers.csv` |
| 3 | 7,481,897 | `digital_events/year=2023/month=08/day=01/digital_events_20230801.csv` |
| 4 | 7,462,600 | `digital_events/year=2025/month=11/day=20/digital_events_20251120.csv` |
| 5 | 7,426,587 | `digital_events/year=2025/month=12/day=11/digital_events_20251211.csv` |
| 6 | 7,399,441 | `digital_events/year=2024/month=07/day=19/digital_events_20240719.csv` |
| 7 | 7,389,394 | `digital_events/year=2023/month=10/day=26/digital_events_20231026.csv` |
| 8 | 7,365,579 | `digital_events/year=2023/month=10/day=31/digital_events_20231031.csv` |
| 9 | 7,350,686 | `digital_events/year=2024/month=01/day=16/digital_events_20240116.csv` |
| 10 | 7,329,032 | `digital_events/year=2023/month=07/day=11/digital_events_20230711.csv` |
| 11 | 7,303,290 | `digital_events/year=2026/month=05/day=06/digital_events_20260506.csv` |
| 12 | 7,290,156 | `digital_events/year=2023/month=10/day=27/digital_events_20231027.csv` |
| 13 | 7,266,535 | `digital_events/year=2025/month=12/day=08/digital_events_20251208.csv` |
| 14 | 7,246,484 | `digital_events/year=2025/month=12/day=15/digital_events_20251215.csv` |
| 15 | 7,239,395 | `digital_events/year=2026/month=06/day=12/digital_events_20260612.csv` |
| 16 | 7,238,990 | `digital_events/year=2025/month=07/day=31/digital_events_20250731.csv` |
| 17 | 7,238,595 | `digital_events/year=2025/month=09/day=08/digital_events_20250908.csv` |
| 18 | 7,176,666 | `digital_events/year=2026/month=01/day=23/digital_events_20260123.csv` |
| 19 | 7,159,262 | `digital_events/year=2025/month=11/day=21/digital_events_20251121.csv` |
| 20 | 7,132,685 | `digital_events/year=2024/month=02/day=06/digital_events_20240206.csv` |

## Filesystem anomalies

| Check | Result | Interpretation |
|---|---|---|
| Duplicate filenames | No duplicate filename groups observed in the scan | No anomaly detected at basename level |
| Unexpected extensions | None; all 7,671 files are `.csv` | No unexpected extension detected |
| Broken-looking paths | None observed from filesystem paths | No obvious malformed path detected |
| Missing expected partition levels | No missing level in the seven partitioned families; static root CSVs are intentionally unpartitioned | Directory structure is consistent at the family level |
| Incomplete year/month/day combinations | Not established | **UNKNOWN** without enumerating expected calendar combinations per family |
| Partition/data timestamp mismatch | Not tested | **UNKNOWN** because file contents were not read |

## Explicit non-results

This filesystem inventory cannot provide row counts, column counts, schemas, data types, null rates, duplicate keys, joins, timestamps, languages, PII classification, workflow feasibility, or evaluation feasibility. The requested subsequent audit stages were not run.