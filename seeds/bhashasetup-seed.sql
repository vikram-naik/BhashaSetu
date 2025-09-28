-- =========================
-- BhashaSetu Seed Data
-- =========================

SET search_path TO bhashasetu;

-- Languages
INSERT INTO language (language_uid, version, code, full_code, name, is_active)
VALUES (1, 1, 'ja', 'ja', 'Japanese', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO language (language_uid, version, code, full_code, name, is_active)
VALUES (2, 1, 'en', 'en', 'English', TRUE)
ON CONFLICT DO NOTHING;

-- Directions
INSERT INTO direction_lookup (direction_uid, version, code, source_lang_uid, target_lang_uid, description, is_active)
VALUES (1, 1, 'en2ja', 2, 1, 'English to Japanese', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO direction_lookup (direction_uid, version, code, source_lang_uid, target_lang_uid, description, is_active)
VALUES (2, 1, 'ja2en', 1, 2, 'Japanese to English', TRUE)
ON CONFLICT DO NOTHING;

-- Domains
INSERT INTO domain (domain_uid, version, code, description, is_active)
VALUES (1, 1, 'social-media', 'Casual social media text', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO domain (domain_uid, version, code, description, is_active)
VALUES (2, 1, 'scientific', 'Scientific and technical text', TRUE)
ON CONFLICT DO NOTHING;

-- Sources
INSERT INTO source (source_uid, version, type, name, author, is_active)
VALUES (1, 1, 'twitter', 'Twitter / X', 'multiple', TRUE)
ON CONFLICT DO NOTHING;

-- Methods
INSERT INTO method_lookup (method_uid, version, name, description, provider, is_active)
VALUES (1, 1, 'human', 'Human professional translator', 'multiple', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO method_lookup (method_uid, version, name, description, provider, is_active)
VALUES (2, 1, 'google', 'Google Translate MT system', 'Google', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO method_lookup (method_uid, version, name, description, provider, is_active)
VALUES (3, 1, 'deepl', 'DeepL Translate MT system', 'DeepL GmbH', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO method_lookup (method_uid, version, name, description, provider, is_active)
VALUES (4, 1, 'chatgpt', 'ChatGPT translation model', 'OpenAI', TRUE)
ON CONFLICT DO NOTHING;

-- Metrics
INSERT INTO metric (metric_uid, version, name, description, scale, is_active)
VALUES (1, 1, 'BLEU', 'Bilingual Evaluation Understudy score', '0-100', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO metric (metric_uid, version, name, description, scale, is_active)
VALUES (2, 1, 'chrF', 'Character n-gram F-score', '0-100', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO metric (metric_uid, version, name, description, scale, is_active)
VALUES (3, 1, 'COMET', 'Crosslingual Optimized Metric for Evaluation of Translation', '0-1', TRUE)
ON CONFLICT DO NOTHING;
