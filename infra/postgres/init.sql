CREATE TABLE IF NOT EXISTS telemetry_events (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts BIGINT NOT NULL,
    temp DOUBLE PRECISION,
    vibration DOUBLE PRECISION,
    raw JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_telemetry_device_sequence UNIQUE (device_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_telemetry_events_created_at
    ON telemetry_events (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_telemetry_events_device_time
    ON telemetry_events (device_id, ts DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id BIGSERIAL PRIMARY KEY,
    telemetry_event_id BIGINT NOT NULL,
    device_id TEXT NOT NULL,
    ts BIGINT NOT NULL,
    anomaly_score DOUBLE PRECISION NOT NULL
        CHECK (anomaly_score >= 0 AND anomaly_score <= 1),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_incidents_telemetry_event
        FOREIGN KEY (telemetry_event_id)
        REFERENCES telemetry_events (id)
        ON DELETE CASCADE,
    CONSTRAINT uq_incident_per_telemetry_event UNIQUE (telemetry_event_id)
);

CREATE INDEX IF NOT EXISTS ix_incidents_created_at
    ON incidents (created_at DESC);
