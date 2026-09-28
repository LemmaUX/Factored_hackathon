# Security and Privacy Data Review

No sensitive values are emitted.

| Dataset | Column pattern | Risk | Handling |
|---|---|---|---|
| branches | branch_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
| branches | address | PII or free-text | Restrict access; hash or redact in derived artifacts |
| branches | phone | PII or free-text | Restrict access; hash or redact in derived artifacts |
| branches | email | PII or free-text | Restrict access; hash or redact in derived artifacts |
| call_transcripts | full_text | sensitive free text | Restrict access; hash or redact in derived artifacts |
| call_transcripts | customer_text | sensitive free text | Restrict access; hash or redact in derived artifacts |
| call_transcripts | agent_text | sensitive free text | Restrict access; hash or redact in derived artifacts |
| complaints | description | sensitive free text | Restrict access; hash or redact in derived artifacts |
| customers | document_number | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | document_type | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | first_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | last_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | date_of_birth | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | email | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | mobile_phone | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | landline_phone | PII or free-text | Restrict access; hash or redact in derived artifacts |
| customers | address | PII or free-text | Restrict access; hash or redact in derived artifacts |
| digital_events | ip_address | PII or free-text | Restrict access; hash or redact in derived artifacts |
| marketing_campaigns | campaign_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
| marketing_campaigns | description | sensitive free text | Restrict access; hash or redact in derived artifacts |
| satisfaction_surveys | question_1_text | sensitive free text | Restrict access; hash or redact in derived artifacts |
| satisfaction_surveys | question_2_text | sensitive free text | Restrict access; hash or redact in derived artifacts |
| satisfaction_surveys | question_3_text | sensitive free text | Restrict access; hash or redact in derived artifacts |
| satisfaction_surveys | open_comments | sensitive free text | Restrict access; hash or redact in derived artifacts |
| satisfaction_surveys | comment_sentiment | sensitive free text | Restrict access; hash or redact in derived artifacts |
| service_agents | first_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
| service_agents | last_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
| service_agents | email | PII or free-text | Restrict access; hash or redact in derived artifacts |
| service_agents | phone | PII or free-text | Restrict access; hash or redact in derived artifacts |
| transactions | merchant_name | PII or free-text | Restrict access; hash or redact in derived artifacts |
