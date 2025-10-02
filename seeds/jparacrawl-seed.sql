-- seeds/jparacrawl-seed.sql
SET search_path TO bhashasetu;

-- Domain: web-crawl
INSERT INTO domain (domain_uid, version, code, description, is_active)
VALUES (3, 1, 'web-crawl', 'Web-crawled parallel corpus (JParaCrawl / OPUS)', TRUE)
ON CONFLICT (domain_uid) DO NOTHING;

-- Source: JParaCrawl (OPUS)
INSERT INTO source (source_uid, version, type, name, author, url, metadata, is_active)
VALUES (2, 1, 'jparacrawl', 'JParaCrawl (OPUS)', 'OPUS / JParaCrawl', 'https://opus.nlpl.eu/', '{}'::jsonb, TRUE)
ON CONFLICT (source_uid) DO NOTHING;

-- Method: corpus
INSERT INTO method_lookup (method_uid, version, name, description, provider, is_active)
VALUES (5, 1, 'corpus', 'Parallel corpus ingestion (JParaCrawl / OPUS)', 'OPUS', TRUE)
ON CONFLICT (method_uid) DO NOTHING;
