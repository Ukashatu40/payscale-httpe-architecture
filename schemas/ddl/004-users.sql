-- schemas/ddl/004-users.sql
-- Designed from scratch — equivalent rigor to reference entities per brief instruction.

CREATE TYPE kyc_status_enum AS ENUM ('PENDING', 'VERIFIED', 'REJECTED');
CREATE TYPE risk_tier_enum AS ENUM ('LOW', 'MEDIUM', 'HIGH');
CREATE TYPE user_status_enum AS ENUM ('ACTIVE', 'SUSPENDED', 'CLOSED');

CREATE TABLE users (
    user_id            UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    phone_number_hash    VARCHAR(128) NOT NULL,   -- hashed, not plaintext — PII
                                                     -- minimization at rest; the
                                                     -- Audit & Compliance Service
                                                     -- (docs/03) owns reversible
                                                     -- lookup via a separate,
                                                     -- access-controlled vault table
                                                     -- not modeled here
    email_hash            VARCHAR(128),
    full_name              VARCHAR(255) NOT NULL,
    kyc_status              kyc_status_enum NOT NULL DEFAULT 'PENDING',
    kyc_verified_at          TIMESTAMPTZ,
    risk_tier                 risk_tier_enum NOT NULL DEFAULT 'MEDIUM',
    status                     user_status_enum NOT NULL DEFAULT 'ACTIVE',
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_users_phone_hash UNIQUE (phone_number_hash)
);

-- Citus: reference table, not distributed. Users is read far more often than
-- written relative to accounts/transactions, and account-to-user lookups
-- happen from every shard — a small reference table replicated to every
-- worker node avoids a cross-shard join on every account lookup.
SELECT create_reference_table('users');

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_users_kyc_status ON users (kyc_status) WHERE kyc_status != 'VERIFIED';
CREATE INDEX idx_users_risk_tier_high ON users (user_id) WHERE risk_tier = 'HIGH';