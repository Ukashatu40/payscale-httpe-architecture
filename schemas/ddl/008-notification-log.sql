-- schemas/ddl/008-notification-log.sql
-- Designed from scratch.

CREATE TYPE notification_channel_enum AS ENUM ('WEBSOCKET', 'PUSH', 'SMS', 'EMAIL');
CREATE TYPE notification_status_enum AS ENUM ('QUEUED', 'SENT', 'DELIVERED', 'FAILED');

CREATE TABLE notification_log (
    notification_id      UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    transaction_id          UUID,               -- nullable: not every
                                                    -- notification is transaction-tied
    user_id                    UUID NOT NULL,
    channel                      notification_channel_enum NOT NULL,
    notification_type              VARCHAR(100) NOT NULL,   -- e.g. 'TXN_COMPLETED', 'TXN_FAILED'
    status                          notification_status_enum NOT NULL DEFAULT 'QUEUED',
    retry_count                       INTEGER NOT NULL DEFAULT 0,
    payload                            JSONB DEFAULT '{}',
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at                         TIMESTAMPTZ,

    CONSTRAINT fk_notification_user FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Citus: distributed by user_id — the dominant query pattern is "get
-- notification history for user X."
SELECT create_distributed_table('notification_log', 'user_id');

-- Indexes
CREATE INDEX idx_notification_user_created ON notification_log (user_id, created_at DESC);
CREATE INDEX idx_notification_status_failed ON notification_log (notification_id)
    WHERE status = 'FAILED';  -- retry-worker query