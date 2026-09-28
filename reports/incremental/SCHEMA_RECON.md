# Schema Reconnaissance

## Scope

Prefix-only reconnaissance inspected 27 files across 13 datasets. Each static CSV contributed one prefix; each partitioned dataset contributed earliest, middle, and latest paths. Sample size was 40 rows per file where available. Raw values were not written.

Runtime: 7.461 seconds.

## Dataset-by-dataset schema summary

### `branches`

Representative files: `branches.csv`

Columns in first sample order: `branch_id`, `branch_code`, `branch_name`, `branch_type`, `address`, `city`, `state`, `country`, `postal_code`, `geographic_zone`, `phone`, `email`, `opening_time`, `closing_time`, `has_atms`, `atm_count`, `has_teller_windows`, `teller_window_count`, `latitude`, `longitude`, `branch_opening_date`, `branch_status`

Columns present in all samples: `branch_id`, `branch_code`, `branch_name`, `branch_type`, `address`, `city`, `state`, `country`, `postal_code`, `geographic_zone`, `phone`, `email`, `opening_time`, `closing_time`, `has_atms`, `atm_count`, `has_teller_windows`, `teller_window_count`, `latitude`, `longitude`, `branch_opening_date`, `branch_status`
Columns missing from some samples: None
Header inconsistency: No

### `customers`

Representative files: `customers.csv`

Columns in first sample order: `customer_id`, `document_number`, `document_type`, `first_name`, `last_name`, `date_of_birth`, `gender`, `email`, `mobile_phone`, `landline_phone`, `address`, `city`, `state`, `country`, `postal_code`, `detected_accent`, `segment`, `credit_score`, `estimated_monthly_income`, `occupation`, `marital_status`, `education_level`, `registration_date`, `registration_branch_id`, `customer_status`, `last_updated`, `accepts_marketing`

Columns present in all samples: `customer_id`, `document_number`, `document_type`, `first_name`, `last_name`, `date_of_birth`, `gender`, `email`, `mobile_phone`, `landline_phone`, `address`, `city`, `state`, `country`, `postal_code`, `detected_accent`, `segment`, `credit_score`, `estimated_monthly_income`, `occupation`, `marital_status`, `education_level`, `registration_date`, `registration_branch_id`, `customer_status`, `last_updated`, `accepts_marketing`
Columns missing from some samples: None
Header inconsistency: No

### `daily_exchange_rates`

Representative files: `daily_exchange_rates.csv`

Columns in first sample order: `date`, `source_currency`, `target_currency`, `exchange_rate`, `buy_rate`, `sell_rate`, `source`

Columns present in all samples: `date`, `source_currency`, `target_currency`, `exchange_rate`, `buy_rate`, `sell_rate`, `source`
Columns missing from some samples: None
Header inconsistency: No

### `marketing_campaigns`

Representative files: `marketing_campaigns.csv`

Columns in first sample order: `campaign_id`, `campaign_name`, `description`, `campaign_type`, `campaign_objective`, `promoted_product`, `target_segment`, `target_country`, `start_date`, `end_date`, `budget`, `campaign_status`, `expected_conversion_rate`

Columns present in all samples: `campaign_id`, `campaign_name`, `description`, `campaign_type`, `campaign_objective`, `promoted_product`, `target_segment`, `target_country`, `start_date`, `end_date`, `budget`, `campaign_status`, `expected_conversion_rate`
Columns missing from some samples: None
Header inconsistency: No

### `products`

Representative files: `products.csv`

Columns in first sample order: `product_id`, `customer_id`, `product_type`, `product_number`, `currency`, `current_balance`, `credit_limit`, `interest_rate`, `opening_date`, `expiration_date`, `opening_branch_id`, `product_status`, `opening_channel`, `has_linked_app`, `days_past_due`, `last_transaction_date`, `last_updated`

Columns present in all samples: `product_id`, `customer_id`, `product_type`, `product_number`, `currency`, `current_balance`, `credit_limit`, `interest_rate`, `opening_date`, `expiration_date`, `opening_branch_id`, `product_status`, `opening_channel`, `has_linked_app`, `days_past_due`, `last_transaction_date`, `last_updated`
Columns missing from some samples: None
Header inconsistency: No

### `service_agents`

Representative files: `service_agents.csv`

Columns in first sample order: `agent_id`, `employee_code`, `first_name`, `last_name`, `email`, `phone`, `native_accent`, `country_of_origin`, `assigned_branch_id`, `agent_type`, `experience_level`, `languages`, `specialty`, `hire_date`, `avg_csat`, `total_monthly_interactions`, `agent_status`, `work_shift`

Columns present in all samples: `agent_id`, `employee_code`, `first_name`, `last_name`, `email`, `phone`, `native_accent`, `country_of_origin`, `assigned_branch_id`, `agent_type`, `experience_level`, `languages`, `specialty`, `hire_date`, `avg_csat`, `total_monthly_interactions`, `agent_status`, `work_shift`
Columns missing from some samples: None
Header inconsistency: No

### `call_center_interactions`

Representative files: `call_center_interactions/year=2023/month=06/day=17/call_center_interactions_20230617.csv`, `call_center_interactions/year=2024/month=12/day=16/call_center_interactions_20241216.csv`, `call_center_interactions/year=2026/month=06/day=17/call_center_interactions_20260617.csv`

Columns in first sample order: `interaction_id`, `interaction_date`, `process_date`, `customer_id`, `agent_id`, `interaction_type`, `channel`, `contact_reason`, `reason_category`, `duration_seconds`, `wait_time_seconds`, `was_resolved`, `requires_followup`, `detected_sentiment`, `sentiment_score`, `customer_detected_accent`, `agent_used_accent`, `was_escalated`, `mentioned_products`, `has_transcript`, `has_recording`

Columns present in all samples: `interaction_id`, `interaction_date`, `process_date`, `customer_id`, `agent_id`, `interaction_type`, `channel`, `contact_reason`, `reason_category`, `duration_seconds`, `wait_time_seconds`, `was_resolved`, `requires_followup`, `detected_sentiment`, `sentiment_score`, `customer_detected_accent`, `agent_used_accent`, `was_escalated`, `mentioned_products`, `has_transcript`, `has_recording`
Columns missing from some samples: None
Header inconsistency: No

### `call_transcripts`

Representative files: `call_transcripts/year=2023/month=06/day=17/call_transcripts_20230617.csv`, `call_transcripts/year=2024/month=12/day=16/call_transcripts_20241216.csv`, `call_transcripts/year=2026/month=06/day=17/call_transcripts_20260617.csv`

Columns in first sample order: `transcript_id`, `interaction_id`, `process_date`, `customer_id`, `agent_id`, `full_text`, `customer_text`, `agent_text`, `detected_language`, `detected_accent`, `accent_confidence`, `detected_keywords`, `mentioned_entities`, `detected_intents`, `main_topics`, `transcription_model`, `audio_quality`, `duration_seconds`

Columns present in all samples: `transcript_id`, `interaction_id`, `process_date`, `customer_id`, `agent_id`, `full_text`, `customer_text`, `agent_text`, `detected_language`, `detected_accent`, `accent_confidence`, `detected_keywords`, `mentioned_entities`, `detected_intents`, `main_topics`, `transcription_model`, `audio_quality`, `duration_seconds`
Columns missing from some samples: None
Header inconsistency: No

### `campaign_sends`

Representative files: `campaign_sends/year=2023/month=07/day=01/campaign_sends_20230701.csv`, `campaign_sends/year=2024/month=12/day=23/campaign_sends_20241223.csv`, `campaign_sends/year=2026/month=06/day=17/campaign_sends_20260617.csv`

Columns in first sample order: `send_id`, `send_date`, `process_date`, `campaign_id`, `customer_id`, `send_channel`, `template_used`, `subject`, `send_status`, `was_delivered`, `was_opened`, `open_date`, `was_clicked`, `click_date`, `click_count`, `had_conversion`, `conversion_date`, `conversion_value`, `open_device`, `open_country`, `failure_reason`, `send_cost`

Columns present in all samples: `send_id`, `send_date`, `process_date`, `campaign_id`, `customer_id`, `send_channel`, `template_used`, `subject`, `send_status`, `was_delivered`, `was_opened`, `open_date`, `was_clicked`, `click_date`, `click_count`, `had_conversion`, `conversion_date`, `conversion_value`, `open_device`, `open_country`, `failure_reason`, `send_cost`
Columns missing from some samples: None
Header inconsistency: No

### `complaints`

Representative files: `complaints/year=2023/month=06/day=17/complaints_20230617.csv`, `complaints/year=2024/month=12/day=16/complaints_20241216.csv`, `complaints/year=2026/month=06/day=17/complaints_20260617.csv`

Columns in first sample order: `complaint_id`, `creation_date`, `process_date`, `customer_id`, `case_type`, `category`, `subcategory`, `reception_channel`, `affected_product_id`, `related_branch_id`, `origin_interaction_id`, `description`, `claimed_amount`, `currency`, `priority`, `status`, `assigned_agent_id`, `assignment_date`, `first_response_date`, `resolution_date`, `closing_date`, `sla_breached`, `resolution_days`, `resolution`, `compensation_granted`, `resolution_satisfaction`, `is_repeat_complainer`

Columns present in all samples: `complaint_id`, `creation_date`, `process_date`, `customer_id`, `case_type`, `category`, `subcategory`, `reception_channel`, `affected_product_id`, `related_branch_id`, `origin_interaction_id`, `description`, `claimed_amount`, `currency`, `priority`, `status`, `assigned_agent_id`, `assignment_date`, `first_response_date`, `resolution_date`, `closing_date`, `sla_breached`, `resolution_days`, `resolution`, `compensation_granted`, `resolution_satisfaction`, `is_repeat_complainer`
Columns missing from some samples: None
Header inconsistency: No

### `digital_events`

Representative files: `digital_events/year=2023/month=06/day=17/digital_events_20230617.csv`, `digital_events/year=2024/month=12/day=16/digital_events_20241216.csv`, `digital_events/year=2026/month=06/day=17/digital_events_20260617.csv`

Columns in first sample order: `event_id`, `event_date`, `process_date`, `customer_id`, `session_id`, `event_type`, `event_category`, `channel`, `platform`, `browser`, `app_version`, `page_url`, `page_title`, `action`, `element_id`, `product_id`, `event_value`, `duration_seconds`, `ip_address`, `ip_country`, `ip_city`, `is_mobile`, `referrer`, `utm_source`, `utm_medium`, `utm_campaign`

Columns present in all samples: `event_id`, `event_date`, `process_date`, `customer_id`, `session_id`, `event_type`, `event_category`, `channel`, `platform`, `browser`, `app_version`, `page_url`, `page_title`, `action`, `element_id`, `product_id`, `event_value`, `duration_seconds`, `ip_address`, `ip_country`, `ip_city`, `is_mobile`, `referrer`, `utm_source`, `utm_medium`, `utm_campaign`
Columns missing from some samples: None
Header inconsistency: No

### `satisfaction_surveys`

Representative files: `satisfaction_surveys/year=2023/month=06/day=17/satisfaction_surveys_20230617.csv`, `satisfaction_surveys/year=2024/month=12/day=16/satisfaction_surveys_20241216.csv`, `satisfaction_surveys/year=2026/month=06/day=17/satisfaction_surveys_20260617.csv`

Columns in first sample order: `survey_id`, `survey_date`, `process_date`, `interaction_id`, `customer_id`, `agent_id`, `survey_type`, `send_channel`, `main_score`, `nps_category`, `question_1_text`, `question_1_response`, `question_2_text`, `question_2_response`, `question_3_text`, `question_3_response`, `open_comments`, `comment_sentiment`, `response_time_hours`, `campaign_response_rate`

Columns present in all samples: `survey_id`, `survey_date`, `process_date`, `interaction_id`, `customer_id`, `agent_id`, `survey_type`, `send_channel`, `main_score`, `nps_category`, `question_1_text`, `question_1_response`, `question_2_text`, `question_2_response`, `question_3_text`, `question_3_response`, `open_comments`, `comment_sentiment`, `response_time_hours`, `campaign_response_rate`
Columns missing from some samples: None
Header inconsistency: No

### `transactions`

Representative files: `transactions/year=2023/month=06/day=17/transactions_20230617.csv`, `transactions/year=2024/month=12/day=16/transactions_20241216.csv`, `transactions/year=2026/month=06/day=17/transactions_20260617.csv`

Columns in first sample order: `transaction_id`, `transaction_date`, `process_date`, `product_id`, `customer_id`, `transaction_type`, `transaction_category`, `amount`, `currency`, `amount_usd`, `channel`, `branch_id`, `merchant_name`, `merchant_category`, `transaction_country`, `transaction_city`, `transaction_status`, `response_code`, `is_fraud`, `fraud_score`, `latitude`, `longitude`

Columns present in all samples: `transaction_id`, `transaction_date`, `process_date`, `product_id`, `customer_id`, `transaction_type`, `transaction_category`, `amount`, `currency`, `amount_usd`, `channel`, `branch_id`, `merchant_name`, `merchant_category`, `transaction_country`, `transaction_city`, `transaction_status`, `response_code`, `is_fraud`, `fraud_score`, `latitude`, `longitude`
Columns missing from some samples: None
Header inconsistency: No

## Relevant fields for Workflow A

Transaction identifiers: `transactions.transaction_id`
Customer identifiers: `customers.customer_id`, `products.customer_id`, `call_center_interactions.customer_id`, `call_transcripts.customer_id`, `campaign_sends.customer_id`, `complaints.customer_id`, `digital_events.customer_id`, `satisfaction_surveys.customer_id`, `transactions.customer_id`
Product identifiers: `products.product_id`, `products.product_number`, `complaints.affected_product_id`, `digital_events.product_id`, `transactions.product_id`
Interaction identifiers: `call_center_interactions.interaction_id`, `call_transcripts.interaction_id`, `complaints.origin_interaction_id`, `satisfaction_surveys.interaction_id`
Status/category/reason fields: `branches.branch_type`, `branches.state`, `branches.branch_status`, `customers.document_type`, `customers.state`, `customers.marital_status`, `customers.customer_status`, `marketing_campaigns.campaign_type`, `marketing_campaigns.campaign_status`, `products.product_type`, `products.product_status`, `service_agents.agent_type`, `service_agents.agent_status`, `call_center_interactions.interaction_type`, `call_center_interactions.contact_reason`, `call_center_interactions.reason_category`, `campaign_sends.send_status`, `campaign_sends.failure_reason`, `complaints.case_type`, `complaints.category`, `complaints.subcategory`, `complaints.priority`, `complaints.status`, `digital_events.event_type`, `digital_events.event_category`, `satisfaction_surveys.survey_type`, `satisfaction_surveys.nps_category`, `transactions.transaction_type`, `transactions.transaction_category`, `transactions.merchant_category`, `transactions.transaction_status`

## Relevant fields for Workflow B

Complaint identifiers: `complaints.complaint_id`
Customer identifiers: `customers.customer_id`, `products.customer_id`, `call_center_interactions.customer_id`, `call_transcripts.customer_id`, `campaign_sends.customer_id`, `complaints.customer_id`, `digital_events.customer_id`, `satisfaction_surveys.customer_id`, `transactions.customer_id`
Interaction identifiers: `call_center_interactions.interaction_id`, `call_transcripts.interaction_id`, `complaints.origin_interaction_id`, `satisfaction_surveys.interaction_id`
Agent identifiers: `service_agents.agent_id`, `call_center_interactions.agent_id`, `call_transcripts.agent_id`, `complaints.assigned_agent_id`, `satisfaction_surveys.agent_id`
Status/category/reason fields: `branches.branch_type`, `branches.state`, `branches.branch_status`, `customers.document_type`, `customers.state`, `customers.marital_status`, `customers.customer_status`, `marketing_campaigns.campaign_type`, `marketing_campaigns.campaign_status`, `products.product_type`, `products.product_status`, `service_agents.agent_type`, `service_agents.agent_status`, `call_center_interactions.interaction_type`, `call_center_interactions.contact_reason`, `call_center_interactions.reason_category`, `campaign_sends.send_status`, `campaign_sends.failure_reason`, `complaints.case_type`, `complaints.category`, `complaints.subcategory`, `complaints.priority`, `complaints.status`, `digital_events.event_type`, `digital_events.event_category`, `satisfaction_surveys.survey_type`, `satisfaction_surveys.nps_category`, `transactions.transaction_type`, `transactions.transaction_category`, `transactions.merchant_category`, `transactions.transaction_status`

## Candidate timestamp, language, and text fields

Timestamp/date candidates: `branches.opening_time`, `branches.closing_time`, `branches.branch_opening_date`, `customers.date_of_birth`, `customers.registration_date`, `customers.last_updated`, `daily_exchange_rates.date`, `marketing_campaigns.start_date`, `marketing_campaigns.end_date`, `products.opening_date`, `products.expiration_date`, `products.last_transaction_date`, `products.last_updated`, `service_agents.hire_date`, `call_center_interactions.interaction_date`, `call_center_interactions.process_date`, `call_transcripts.process_date`, `campaign_sends.send_date`, `campaign_sends.process_date`, `campaign_sends.open_date`, `campaign_sends.click_date`, `campaign_sends.conversion_date`, `complaints.creation_date`, `complaints.process_date`, `complaints.assignment_date`, `complaints.first_response_date`, `complaints.resolution_date`, `complaints.closing_date`, `digital_events.event_date`, `digital_events.process_date`, `satisfaction_surveys.survey_date`, `satisfaction_surveys.process_date`, `transactions.transaction_date`, `transactions.process_date`
Language-related fields: `service_agents.languages`, `call_transcripts.detected_language`
Free-text fields: `marketing_campaigns.description`, `call_transcripts.full_text`, `call_transcripts.customer_text`, `call_transcripts.agent_text`, `call_transcripts.transcription_model`, `campaign_sends.subject`, `complaints.description`, `satisfaction_surveys.question_1_text`, `satisfaction_surveys.question_2_text`, `satisfaction_surveys.question_3_text`, `satisfaction_surveys.open_comments`, `satisfaction_surveys.comment_sentiment`

## Candidate join keys

Identifier-like columns are candidates only; relationships were not tested: `branches.branch_id`, `customers.customer_id`, `customers.document_number`, `customers.registration_branch_id`, `marketing_campaigns.campaign_id`, `products.product_id`, `products.customer_id`, `products.product_number`, `products.opening_branch_id`, `service_agents.agent_id`, `service_agents.assigned_branch_id`, `call_center_interactions.interaction_id`, `call_center_interactions.customer_id`, `call_center_interactions.agent_id`, `call_transcripts.transcript_id`, `call_transcripts.interaction_id`, `call_transcripts.customer_id`, `call_transcripts.agent_id`, `campaign_sends.send_id`, `campaign_sends.campaign_id`, `campaign_sends.customer_id`, `complaints.complaint_id`, `complaints.customer_id`, `complaints.affected_product_id`, `complaints.related_branch_id`, `complaints.origin_interaction_id`, `complaints.assigned_agent_id`, `digital_events.event_id`, `digital_events.customer_id`, `digital_events.session_id`, `digital_events.element_id`, `digital_events.product_id`, `satisfaction_surveys.survey_id`, `satisfaction_surveys.interaction_id`, `satisfaction_surveys.customer_id`, `satisfaction_surveys.agent_id`, `transactions.transaction_id`, `transactions.product_id`, `transactions.customer_id`, `transactions.branch_id`

## Schema drift findings

Schema drift datasets: None observed

No full-file scan was performed. Parsing anomalies outside sampled prefixes, nullability, value distributions, key uniqueness, joins, and semantic validation remain unknown.

## Unknowns requiring actual data scans

- Complete row counts and complete distinct-value counts.
- Full-file schema drift and malformed records outside the sampled prefixes.
- Primary-key uniqueness and foreign-key validity.
- Timestamp validity, partition alignment, language coverage, workflow labels, and leakage.
- PII presence in values; this report contains column metadata only.
