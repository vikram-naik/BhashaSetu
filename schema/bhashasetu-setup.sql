-- =========================
-- BhashaSetu DB Setup
-- =========================

-- Create database (run as postgres superuser)
DO
$$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_database WHERE datname = 'bhashasetu'
   ) THEN
      PERFORM dblink_exec('dbname=' || current_database(),
                          'CREATE DATABASE bhashasetu');
   END IF;
END
$$ LANGUAGE plpgsql;

-- Create user if not exists
DO
$$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_roles WHERE rolname = 'bhasha_user'
   ) THEN
      CREATE ROLE bhasha_user WITH LOGIN PASSWORD 'StrongPasswordHere';
   END IF;
END
$$ LANGUAGE plpgsql;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE bhashasetu TO bhasha_user;

-- Connect to bhashasetu DB
\c bhashasetu

-- Create schema if not exists
CREATE SCHEMA IF NOT EXISTS bhashasetu AUTHORIZATION bhasha_user;

-- Ensure default search_path for user
ALTER ROLE bhasha_user SET search_path = bhashasetu;
