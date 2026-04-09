-- Interview Coach - Initial Database Schema
-- PostgreSQL 17 + pgvector Extension
-- Architecture v3.2.1 Compliant

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ===========================================
-- USER PROFILES
-- ===========================================

CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    resume_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ===========================================
-- ACHIEVEMENTS (with embeddings)
-- ===========================================

CREATE TABLE IF NOT EXISTS achievements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    context TEXT,
    action TEXT,
    result TEXT,
    metrics TEXT[],
    tags TEXT[],
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ===========================================
-- DOCUMENT CHUNKS (for RAG with embeddings)
-- ===========================================

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Vector indexes for similarity search
CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx 
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS achievements_embedding_idx 
    ON achievements USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ===========================================
-- CONTEXT PROFILES (company/interviewer research)
-- ===========================================

CREATE TABLE IF NOT EXISTS context_profiles (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    payload JSONB DEFAULT '{}',
    source_urls TEXT[],
    raw_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS context_document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_id UUID REFERENCES context_profiles(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS context_document_chunks_embedding_idx
    ON context_document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS context_document_chunks_context_idx
    ON context_document_chunks(context_id, kind);

-- ===========================================
-- INTERVIEW CONFIGURATIONS
-- Note: Uses logical aliases, NOT model IDs
-- ===========================================

CREATE TABLE IF NOT EXISTS interview_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    job_description TEXT,
    company_values TEXT[],
    response_style TEXT DEFAULT 'mixed',
    language_preference TEXT DEFAULT 'auto',
    custom_rules TEXT,
    -- Provider aliases (no hardcoded model IDs)
    stt_alias TEXT DEFAULT 'stt_primary',
    llm_alias TEXT DEFAULT 'llm_main',
    embedding_alias TEXT DEFAULT 'embedding_primary',
    provider_overrides JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ===========================================
-- SESSIONS
-- ===========================================

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_id UUID REFERENCES interview_configs(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'active',
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ,
    summary JSONB
);

CREATE INDEX IF NOT EXISTS sessions_config_idx ON sessions(config_id);
CREATE INDEX IF NOT EXISTS sessions_status_idx ON sessions(status);

-- ===========================================
-- EXCHANGES (Q&A pairs)
-- ===========================================

CREATE TABLE IF NOT EXISTS exchanges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    index_in_session INT NOT NULL,
    interviewer_utterance TEXT NOT NULL,
    language_detected TEXT,
    question_analysis JSONB NOT NULL,
    suggested_response JSONB NOT NULL,
    quality_result JSONB NOT NULL,
    user_actual_response TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS exchanges_session_idx ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS exchanges_session_order_idx ON exchanges(session_id, index_in_session);

-- ===========================================
-- EVENT LOG (append-only for replay + audit)
-- ===========================================

CREATE TABLE IF NOT EXISTS event_log (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    trace_id TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS event_log_session_idx ON event_log(session_id, created_at);

-- ===========================================
-- LATENCY METRICS (time-series)
-- ===========================================

CREATE TABLE IF NOT EXISTS latency_metrics (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    exchange_index INT,
    step_name TEXT NOT NULL,
    duration_ms INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS latency_metrics_session_idx ON latency_metrics(session_id);
CREATE INDEX IF NOT EXISTS latency_metrics_step_idx ON latency_metrics(step_name, created_at);

-- ===========================================
-- UPDATE TRIGGER
-- ===========================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE OR REPLACE TRIGGER update_user_profiles_updated_at 
    BEFORE UPDATE ON user_profiles 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- GRANTS (for development)
-- ===========================================

-- Note: In production, use more restrictive grants
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO interview_coach;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO interview_coach;
