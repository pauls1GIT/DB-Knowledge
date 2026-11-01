CREATE TABLE IF NOT EXISTS article_embedding (
    key VARCHAR(64) PRIMARY KEY,
    model VARCHAR(500) NOT NULL,
    model_version VARCHAR(200) NOT NULL,
    vector JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
