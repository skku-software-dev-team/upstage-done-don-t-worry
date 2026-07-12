CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(255) NOT NULL,
    doc_type    VARCHAR(100) NOT NULL,
    version     VARCHAR(50)  NOT NULL,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS clauses (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    clause_no    VARCHAR(50),
    title        TEXT,
    requirement  TEXT,
    related_laws TEXT,
    page         INT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clause_id UUID NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    question  TEXT NOT NULL,
    order_no  INT  NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_items (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category_id  UUID REFERENCES categories(id),
    merged_title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_map (
    canonical_id UUID NOT NULL REFERENCES canonical_items(id) ON DELETE CASCADE,
    clause_id    UUID NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    PRIMARY KEY (canonical_id, clause_id)
);

CREATE TABLE IF NOT EXISTS org_status (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID NOT NULL,
    canonical_id UUID NOT NULL REFERENCES canonical_items(id) ON DELETE CASCADE,
    status       VARCHAR(50) NOT NULL DEFAULT 'not_started',
    jira_key     VARCHAR(100),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (org_id, canonical_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
    id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clause_id UUID NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    embedding vector(4096)
);

-- Index for vector similarity search
CREATE INDEX IF NOT EXISTS embeddings_vector_idx
    ON embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
