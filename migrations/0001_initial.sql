-- Run against Lakebase/PostgreSQL. Alembic can replace this bootstrap migration later.
CREATE TABLE IF NOT EXISTS jira_issue (
  id UUID PRIMARY KEY, external_key VARCHAR(100) UNIQUE NOT NULL, summary TEXT NOT NULL,
  description TEXT NOT NULL, resolution TEXT NOT NULL, error_code VARCHAR(100), created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS known_error (
  id UUID PRIMARY KEY, title VARCHAR(500) NOT NULL, current_version_id UUID,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS article_version (
  id UUID PRIMARY KEY, known_error_id UUID NOT NULL REFERENCES known_error(id), version_number INTEGER NOT NULL,
  title VARCHAR(500) NOT NULL, problem TEXT NOT NULL, root_cause TEXT NOT NULL, solution TEXT NOT NULL,
  status VARCHAR(40) NOT NULL, source_jira_issue_id UUID REFERENCES jira_issue(id), review_id UUID,
  published_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(known_error_id, version_number)
);
CREATE TABLE IF NOT EXISTS human_review (
  id UUID PRIMARY KEY, workflow_id UUID NOT NULL, decision VARCHAR(30) NOT NULL, reviewer VARCHAR(200) NOT NULL,
  feedback TEXT, modified_content JSONB, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS workflow_checkpoint (
  workflow_id UUID PRIMARY KEY, status VARCHAR(40) NOT NULL, current_step VARCHAR(80) NOT NULL,
  state JSONB NOT NULL, revision_count INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS publication_outbox (
  id UUID PRIMARY KEY, article_version_id UUID NOT NULL, event_type VARCHAR(80) NOT NULL,
  payload JSONB NOT NULL, processed BOOLEAN NOT NULL DEFAULT FALSE, attempts INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON publication_outbox(processed, created_at);
