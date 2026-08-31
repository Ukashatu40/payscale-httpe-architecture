-- schemas/ddl/000-extensions-and-helpers.sql
-- Prerequisite setup: extensions, UUIDv7 function, roles, and Citus
-- distribution setup. Run this FIRST, before 001-008.

-- Citus extension for horizontal sharding (ADR-002)
CREATE EXTENSION IF NOT EXISTS citus;

-- pgcrypto for gen_random_bytes(), used by the UUIDv7 implementation below
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- PostgreSQL 15 has no native UUIDv7 generator (added upstream later than
-- PG15). This is a standard RFC-9562-draft-compatible implementation:
-- 48-bit millisecond timestamp prefix (time-ordered, matching the brief's
-- "UUIDv7 for time-ordered distribution" requirement) + 74 random bits.
-- Time-ordering matters here specifically because it keeps INSERT locality
-- reasonable within a single shard's B-tree indexes, avoiding the random-
-- insert index fragmentation that pure UUIDv4 would cause at 12,000+ TPS.
CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS UUID AS $$
DECLARE
    unix_ts_ms BYTEA;
    uuid_bytes BYTEA;
BEGIN
    unix_ts_ms := substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::BIGINT) FROM 3);
    uuid_bytes := unix_ts_ms || gen_random_bytes(10);
    -- Set version (7) and variant bits per RFC 9562
    uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);
    uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);
    RETURN encode(uuid_bytes, 'hex')::UUID;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- Application roles: separates the write path from any process that might
-- need to touch append-only tables, so REVOKE UPDATE/DELETE (used in 003
-- and 005) has a concrete role to apply to. This is the DB-level enforcement
-- referenced in Section 6 of the project strategy ("do not trust application
-- validation alone").
CREATE ROLE app_write_role LOGIN;
CREATE ROLE app_readonly_role LOGIN;
CREATE ROLE app_migration_role LOGIN;  -- used only for DDL changes / partition
                                          -- maintenance, never by application
                                          -- runtime code

GRANT CONNECT ON DATABASE payscale TO app_write_role, app_readonly_role, app_migration_role;
GRANT USAGE ON SCHEMA public TO app_write_role, app_readonly_role, app_migration_role;

-- Broad grants applied here; the specific REVOKE UPDATE, DELETE calls for
-- append-only tables (ledger_entries, transaction_events) happen in their
-- own DDL files (003, 005) AFTER those tables exist.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO app_write_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO app_readonly_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_migration_role;

-- Shared trigger function used across multiple tables (001, 004, 006) —
-- defined once here rather than repeated per file.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;