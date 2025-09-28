-- drop_bhashasetu_objects.sql
-- Drops all objects inside schema "bhashasetu" except the schema itself and users.
-- Idempotent: safe to run multiple times.
-- Run as a DB superuser or as the schema owner:
--   psql -U bhasha_user -d bhashasetu -f drop_bhashasetu_objects.sql

DO
$$
DECLARE
  obj record;
BEGIN
  -- 1) Drop materialized views
  FOR obj IN
    SELECT matviewname AS name
    FROM pg_matviews
    WHERE schemaname = 'bhashasetu'
  LOOP
    EXECUTE format('DROP MATERIALIZED VIEW IF EXISTS bhashasetu.%I CASCADE', obj.name);
  END LOOP;

  -- 2) Drop regular views
  FOR obj IN
    SELECT viewname AS name
    FROM pg_views
    WHERE schemaname = 'bhashasetu'
  LOOP
    EXECUTE format('DROP VIEW IF EXISTS bhashasetu.%I CASCADE', obj.name);
  END LOOP;

  -- 3) Drop functions (use identity args to handle overloads)
  FOR obj IN
    SELECT n.nspname AS schemaname,
           p.proname AS fname,
           pg_get_function_identity_arguments(p.oid) AS args
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'bhashasetu'
  LOOP
    -- args can be '' for no-arg functions
    EXECUTE format('DROP FUNCTION IF EXISTS %I.%I(%s) CASCADE',
                   obj.schemaname, obj.fname, obj.args);
  END LOOP;

  -- 4) Drop triggers are dropped with table CASCADE; no explicit action needed.

  -- 5) Drop tables
  FOR obj IN
    SELECT tablename AS name
    FROM pg_tables
    WHERE schemaname = 'bhashasetu'
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS bhashasetu.%I CASCADE', obj.name);
  END LOOP;

  -- 6) Drop sequences
  FOR obj IN
    SELECT sequence_name AS name
    FROM information_schema.sequences
    WHERE sequence_schema = 'bhashasetu'
  LOOP
    EXECUTE format('DROP SEQUENCE IF EXISTS bhashasetu.%I CASCADE', obj.name);
  END LOOP;

  -- 7) Drop indexes (standalone indexes, if any remain)
  FOR obj IN
    SELECT indexname AS name
    FROM pg_indexes
    WHERE schemaname = 'bhashasetu'
  LOOP
    EXECUTE format('DROP INDEX IF EXISTS bhashasetu.%I CASCADE', obj.name);
  END LOOP;

  -- 8) Drop types (composite / enum / domain types) in schema
  FOR obj IN
    SELECT t.typname AS name
    FROM pg_type t
    JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE n.nspname = 'bhashasetu'
      AND (t.typtype = 'c' OR t.typtype = 'e' OR t.typtype = 'd')  -- composite/enum/domain
  LOOP
    EXECUTE format('DROP TYPE IF EXISTS bhashasetu.%I CASCADE', obj.name);
  END LOOP;

  -- 9) Informational message
  RAISE NOTICE 'All droppable objects inside schema "bhashasetu" have been removed (views, functions, tables, sequences, indexes, types). Schema remains.';
END
$$;
