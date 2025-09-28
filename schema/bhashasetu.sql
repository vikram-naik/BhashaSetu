-- =========================
-- BhashaSetu Core Schema
-- =========================

-- Ensure schema exists (safety)
CREATE SCHEMA IF NOT EXISTS bhashasetu;

-- Use schema
SET search_path TO bhashasetu;

-- =========================
-- Reference tables
-- =========================

-- Languages (supports dialects/variants, versioned)
CREATE TABLE IF NOT EXISTS language (
    language_uid BIGINT NOT NULL,            -- stable identity for a language
    version INT NOT NULL,                    -- version number of this record
    code VARCHAR(10) NOT NULL,               -- ISO 639-1/2: 'en', 'ja'
    dialect VARCHAR(50),                     -- e.g. 'US', 'GB', 'Kansai'
    full_code VARCHAR(20) NOT NULL,          -- e.g. 'en-US', 'ja-Kansai'
    name VARCHAR(100) NOT NULL,              -- human-readable name
    is_active BOOLEAN DEFAULT TRUE,          -- marks current active version
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (language_uid, version),
    CONSTRAINT uq_language_uid UNIQUE (language_uid)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_language_active
ON language(language_uid) WHERE is_active = TRUE;

-- Domains (broad categories like news, spoken, literary)
CREATE TABLE IF NOT EXISTS domain (
    domain_uid BIGINT NOT NULL,              -- stable identity
    version INT NOT NULL,
    code VARCHAR(50) NOT NULL,               -- 'spoken', 'news', 'tech'
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (domain_uid, version),
    CONSTRAINT uq_domain_uid UNIQUE (domain_uid)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_active
ON domain(domain_uid) WHERE is_active = TRUE;

-- Sources (fine-grained provenance of a sentence)
CREATE TABLE IF NOT EXISTS source (
    source_uid BIGINT NOT NULL,              -- stable identity
    version INT NOT NULL,
    type VARCHAR(50) NOT NULL,               -- e.g. 'twitter', 'book', 'video'
    name VARCHAR(255),                       -- book name, video title, etc.
    author VARCHAR(255),                     -- author/creator name
    url TEXT,                                -- optional reference URL
    metadata JSONB DEFAULT '{}'::jsonb,      -- extra structured data
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (source_uid, version),
    CONSTRAINT uq_source_uid UNIQUE (source_uid)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_source_active
ON source(source_uid) WHERE is_active = TRUE;

-- Translation methods (human or machine providers)
CREATE TABLE IF NOT EXISTS method_lookup (
    method_uid BIGINT NOT NULL,              -- stable identity
    version INT NOT NULL,
    name VARCHAR(50) NOT NULL,               -- 'human', 'Google', 'DeepL'
    description TEXT,
    provider VARCHAR(50),                    -- provider info
    license TEXT,                            -- license terms if applicable
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (method_uid, version),
    CONSTRAINT uq_method_uid UNIQUE (method_uid)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_method_active
ON method_lookup(method_uid) WHERE is_active = TRUE;

-- Directions (normalized language pairs for translations)
CREATE TABLE IF NOT EXISTS direction_lookup (
    direction_uid BIGINT NOT NULL,           -- stable identity
    version INT NOT NULL,
    code VARCHAR(20) NOT NULL,               -- e.g. 'en2ja', 'ja2en'
    source_lang_uid BIGINT NOT NULL,         -- FK to language_uid
    target_lang_uid BIGINT NOT NULL,         -- FK to language_uid
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (direction_uid, version),
    CONSTRAINT uq_direction_uid UNIQUE (direction_uid),
    FOREIGN KEY (source_lang_uid) REFERENCES language(language_uid),
    FOREIGN KEY (target_lang_uid) REFERENCES language(language_uid)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_direction_active
ON direction_lookup(direction_uid) WHERE is_active = TRUE;

-- Metrics (scoring schemes: BLEU, chrF, COMET, MQM, etc.)
CREATE TABLE IF NOT EXISTS metric (
    metric_uid BIGINT NOT NULL,              -- stable identity
    version INT NOT NULL,
    name VARCHAR(50) NOT NULL,               -- metric name
    description TEXT,
    scale VARCHAR(50),                       -- e.g. '0-1', '0-100', 'grades'
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (metric_uid, version),
    CONSTRAINT uq_metric_uid UNIQUE (metric_uid)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_active
ON metric(metric_uid) WHERE is_active = TRUE;

-- =========================
-- Core tables
-- =========================

-- Sentences (atomic monolingual texts)
CREATE TABLE IF NOT EXISTS sentence (
    id BIGSERIAL PRIMARY KEY,
    text TEXT NOT NULL,                      -- actual text
    language_uid BIGINT NOT NULL REFERENCES language(language_uid),
    source_uid BIGINT REFERENCES source(source_uid),
    domain_uid BIGINT REFERENCES domain(domain_uid),
    version INT NOT NULL DEFAULT 1,          -- version for edits
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW()
);

-- Translations (links between sentences)
CREATE TABLE IF NOT EXISTS translation (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES sentence(id) ON DELETE CASCADE,
    target_id BIGINT NOT NULL REFERENCES sentence(id) ON DELETE CASCADE,
    direction_uid BIGINT NOT NULL REFERENCES direction_lookup(direction_uid),
    method_uid BIGINT NOT NULL REFERENCES method_lookup(method_uid),
    method_version VARCHAR(50),              -- e.g. 'ChatGPT-4 Sep2025'
    is_synthetic BOOLEAN DEFAULT FALSE,      -- flag if back-translated
    notes TEXT,
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW()
);

-- Translation metrics (scores per translation per metric)
CREATE TABLE IF NOT EXISTS translation_metric (
    id BIGSERIAL PRIMARY KEY,
    translation_id BIGINT NOT NULL REFERENCES translation(id) ON DELETE CASCADE,
    metric_uid BIGINT NOT NULL REFERENCES metric(metric_uid),
    score_num NUMERIC,                       -- numeric score (BLEU=32.4)
    score_txt VARCHAR(50),                   -- textual score (e.g. 'A+')
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_score_not_null CHECK (score_num IS NOT NULL OR score_txt IS NOT NULL),
    UNIQUE (translation_id, metric_uid, version)
);

-- =========================
-- Indexes for performance
-- =========================

-- Full-text search on sentences
CREATE INDEX IF NOT EXISTS idx_sentence_text_gin
ON sentence USING gin(to_tsvector('simple', text));

-- Fast lookups
CREATE INDEX IF NOT EXISTS idx_sentence_language ON sentence(language_uid);
CREATE INDEX IF NOT EXISTS idx_sentence_domain ON sentence(domain_uid);
CREATE INDEX IF NOT EXISTS idx_sentence_source ON sentence(source_uid);

-- Translation lookups
CREATE INDEX IF NOT EXISTS idx_translation_source ON translation(source_id);
CREATE INDEX IF NOT EXISTS idx_translation_target ON translation(target_id);

-- Metric lookups
CREATE INDEX IF NOT EXISTS idx_translation_metric ON translation_metric(translation_id);
