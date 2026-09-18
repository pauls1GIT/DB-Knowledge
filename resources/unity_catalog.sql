CREATE SCHEMA IF NOT EXISTS ${catalog}.${schema};
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.article_chunks (
  chunk_id STRING NOT NULL,
  known_error_id STRING NOT NULL,
  article_version_id STRING NOT NULL,
  version_number INT NOT NULL,
  title STRING NOT NULL,
  section STRING NOT NULL,
  content STRING NOT NULL,
  error_codes ARRAY<STRING>,
  source_jira_issue_id STRING,
  review_id STRING,
  status STRING NOT NULL,
  is_current BOOLEAN NOT NULL,
  published_at TIMESTAMP,
  content_hash STRING NOT NULL
) USING DELTA
TBLPROPERTIES (delta.enableChangeDataFeed = true);
