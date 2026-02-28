
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Main rules table
CREATE TABLE IF NOT EXISTS safety_rules (
    id              SERIAL PRIMARY KEY,
    rule_id         UUID NOT NULL UNIQUE,
    original_text   TEXT NOT NULL,
    actionable_rule TEXT NOT NULL,
    materials       TEXT[] DEFAULT '{}',
    suggested_severity  INTEGER CHECK (suggested_severity BETWEEN 1 AND 5),
    validated_severity  INTEGER CHECK (validated_severity BETWEEN 1 AND 5),
    categories      TEXT[] DEFAULT '{}',
    source_document TEXT NOT NULL,
    page_number     INTEGER,
    section_heading TEXT DEFAULT 'Unknown Section',
    embedding       vector(384),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 3. Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_rules_categories  ON safety_rules USING GIN (categories);
CREATE INDEX IF NOT EXISTS idx_rules_severity    ON safety_rules (validated_severity DESC);
CREATE INDEX IF NOT EXISTS idx_rules_document    ON safety_rules (source_document);
CREATE INDEX IF NOT EXISTS idx_rules_rule_id     ON safety_rules (rule_id);

-- 4. Vector similarity index (IVFFlat — good for up to ~100k rows)
--    Increase lists if you have significantly more rules.
CREATE INDEX IF NOT EXISTS idx_rules_embedding
    ON safety_rules USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id                  SERIAL PRIMARY KEY,
    run_timestamp       TIMESTAMPTZ NOT NULL,
    model_used          TEXT,
    total_pages         INTEGER,
    rule_count          INTEGER,
    document_count      INTEGER,
    source_documents    TEXT[],
    json_source_file    TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);
