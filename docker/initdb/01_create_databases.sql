-- Runs automatically on first PostgreSQL container boot.
-- The 'credit_risk' database is created by the POSTGRES_DB environment variable.
-- This script creates the Metabase internal metadata database alongside it.

CREATE DATABASE metabase_internal;