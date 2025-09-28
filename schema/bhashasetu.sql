-- ========================
-- Reference tables (single table, composite PK)
-- ========================

-- Languages
CREATE TABLE language (
    language_uid BIGINT NOT NULL,            -- stable identity
    version INT NOT NULL,                    -- version number
    code VARCHAR(10) NOT NULL,               -- ISO code: 'en', 'ja'
    dialect VARCHAR(50),                     -- e.g. 'US', 'GB', 'Kansai'
    full_code VARCHAR(20) NOT NULL,          -- e.g. 'en-US'
    name VARCHAR(100) NOT NULL,              -- Human-readable
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (language_uid, version)
);

-- Ensure only one active version per UID
CREATE UNIQUE INDEX uq_language_active
ON language(language_uid)
WHERE is_active = TRUE;


-- Domains
CREATE TABLE domain (
    domain_uid BIGINT NOT NULL,
    version INT NOT NULL,
    code VARCHAR(50) NOT NULL,               -- 'spoken', 'news', 'tech'
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (domain_uid, version)
);

CREATE UNIQUE INDEX uq_domain_active
ON domain(domain_uid)
WHERE is_active = TRUE;


-- Sources
CREATE TABLE source (
    source_uid BIGINT NOT NULL,
    version INT NOT NULL,
    type VARCHAR(50) NOT NULL,               -- 'twitter', 'book', 'video'
    name VARCHAR(255),
    author VARCHAR(255),
    url TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (source_uid, version)
);

CREATE UNIQUE INDEX uq_source_active
ON source(source_uid)
WHERE is_active = TRUE;


-- Translation methods
CREATE TABLE method_lookup (
    method_uid BIGINT NOT NULL,
    version INT NOT NULL,
    name VARCHAR(50) NOT NULL,               -- 'human', 'Google', 'DeepL'
    description TEXT,
    provider VARCHAR(50),
    license TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (method_uid, version)
);

CREATE UNIQUE INDEX uq_method_active
ON method_lookup(method_uid)
WHERE is_active = TRUE;


-- Direction lookup
CREATE TABLE direction_lookup (
    direction_uid BIGINT NOT NULL,
    version INT NOT NULL,
    code VARCHAR(20) NOT NULL,               -- 'en2ja'
    source_lang_uid BIGINT NOT NULL,         -- FK to language_uid
    target_lang_uid BIGINT NOT NULL,         -- FK to language_uid
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (direction_uid, version),
    FOREIGN KEY (source_lang_uid) REFERENCES language(language_uid),
    FOREIGN KEY (target_lang_uid) REFERENCES language(language_uid)
);

CREATE UNIQUE INDEX uq_direction_active
ON direction_lookup(direction_uid)
WHERE is_active = TRUE;


-- Metrics
CREATE TABLE metric (
    metric_uid BIGINT NOT NULL,
    version INT NOT NULL,
    name VARCHAR(50) NOT NULL,               -- 'BLEU', 'chrF', 'COMET'
    description TEXT,
    scale VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (metric_uid, version)
);

CREATE UNIQUE INDEX uq_metric_active
ON metric(metric_uid)
WHERE is_active = TRUE;


-- ========================
-- Core tables
-- ========================

-- Sentences
CREATE TABLE sentence (
    id BIGSERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    language_uid BIGINT NOT NULL REFERENCES language(language_uid),
    source_uid BIGINT REFERENCES source(source_uid),
    domain_uid BIGINT REFERENCES domain(domain_uid),
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW()
);

-- Translations
CREATE TABLE translation (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES sentence(id) ON DELETE CASCADE,
    target_id BIGINT NOT NULL REFERENCES sentence(id) ON DELETE CASCADE,
    direction_uid BIGINT NOT NULL REFERENCES direction_lookup(direction_uid),
    method_uid BIGINT NOT NULL REFERENCES method_lookup(method_uid),
    method_version VARCHAR(50),              -- 'ChatGPT-4 Sep2025'
    is_synthetic BOOLEAN DEFAULT FALSE,
    notes TEXT,
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW()
);

-- Translation metrics
CREATE TABLE translation_metric (
    id BIGSERIAL PRIMARY KEY,
    translation_id BIGINT NOT NULL REFERENCES translation(id) ON DELETE CASCADE,
    metric_uid BIGINT NOT NULL REFERENCES metric(metric_uid),
    score_num NUMERIC,
    score_txt VARCHAR(50),
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated_on TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_score_not_null CHECK (score_num IS NOT NULL OR score_txt IS NOT NULL),
    UNIQUE (translation_id, metric_uid, version)
);

-- ========================
-- Indexes for performance
-- ========================

-- Sentence text search
CREATE INDEX idx_sentence_text_gin ON sentence USING gin(to_tsvector('simple', text));

-- Sentence lookup helpers
CREATE INDEX idx_sentence_language ON sentence(language_uid);
CREATE INDEX idx_sentence_domain ON sentence(domain_uid);
CREATE INDEX idx_sentence_source ON sentence(source_uid);

-- Translation joins
CREATE INDEX idx_translation_source ON translation(source_id);
CREATE INDEX idx_translation_target ON translation(target_id);

-- Metric lookups
CREATE INDEX idx_translation_metric ON translation_metric(translation_id);
