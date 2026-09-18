-- New table only: existing publication records remain intact.
CREATE TABLE IF NOT EXISTS publication_claim (
    key VARCHAR(200) PRIMARY KEY,
    article_version_id VARCHAR(36) NOT NULL
);
