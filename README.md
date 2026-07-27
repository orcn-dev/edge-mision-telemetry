# Edge Mission Telemetry

A containerized edge telemetry pipeline focused on **idempotency, concurrency safety, fault recovery, and observability**.

The project uses synthetic device data only and demonstrates how repeated or concurrent message delivery can be handled without creating duplicate operational records.

## Architecture

```text
Device Simulator
      |
      v
MQTT / Mosquitto
      |
      v
FastAPI Ingest Service
      |
      v
PostgreSQL
  | telemetry_events
  | telemetry_evaluations
  | incidents
      |
      v
Anomaly Service
      |
      v
Prometheus -> Grafana
```

## Reliability guarantees

### Idempotent telemetry ingestion

Every packet carries a device identifier and sequence number. PostgreSQL enforces:

```sql
UNIQUE (device_id, seq)
```

The ingest service uses:

```sql
ON CONFLICT (device_id, seq) DO NOTHING
```

Two concurrent deliveries can therefore produce only one `telemetry_events` row. The rejected replay is exposed through `telemetry_db_conflicts_total`.

### Exactly-once anomaly evaluation

The anomaly worker selects the oldest unevaluated packet using:

```sql
FOR UPDATE OF t SKIP LOCKED
```

Each telemetry event can have only one `telemetry_evaluations` row. The database constraint remains the final protection if multiple workers race for the same event.

### Idempotent incident creation

A high-risk telemetry event can create only one incident because `incidents.telemetry_event_id` is unique and the insert uses `ON CONFLICT DO NOTHING`.

### Retry with exponential backoff

The ingest and anomaly services retry temporary PostgreSQL connection failures with bounded exponential backoff. Retry attempts and processing errors are exported as metrics.

## Stack

- Python 3.12
- FastAPI
- MQTT / Eclipse Mosquitto
- PostgreSQL 15
- Prometheus
- Grafana
- Docker Compose
- Pytest
- GitHub Actions

## Run locally

```powershell
./scripts/part3-demo.ps1 -Reset
```

The script:

1. Builds and starts the complete stack.
2. Publishes the same high-risk packet from two concurrent processes.
3. Waits for ingestion and anomaly evaluation.
4. Verifies that the database contains exactly:
   - one telemetry row,
   - one evaluation row,
   - one incident row.
5. Prints the duplicate and processing metrics for a screenshot-ready proof.

Grafana:

```text
http://localhost:3000
admin / admin
```

Other endpoints:

```text
http://localhost:8000/healthz
http://localhost:8000/metrics
http://localhost:9101/metrics
http://localhost:9090
```

## Tests

```powershell
python -m pip install -r services/ingest-api/requirements.txt
python -m pip install -r services/ai-service/requirements.txt
python -m pip install pytest
pytest -q
```

Tests cover:

- first packet insertion,
- duplicate packet rejection,
- normal anomaly evaluation,
- high-risk incident creation,
- concurrent evaluation conflict protection,
- duplicate incident protection,
- connection cleanup.

## CI integration proof

The GitHub Actions workflow performs both unit and integration validation:

```text
Install dependencies
        |
        v
Run Pytest
        |
        v
Build Docker Compose stack
        |
        v
Publish duplicate packet concurrently
        |
        v
Verify 1 packet + 1 evaluation + 1 incident
        |
        v
Verify Prometheus metrics
```

## Operational metrics

### Ingest service

- `telemetry_messages_total`
- `telemetry_db_inserts_total`
- `telemetry_db_conflicts_total`
- `telemetry_ingest_errors_total`
- `telemetry_db_retries_total`
- `telemetry_last_message_timestamp_seconds`

### Anomaly service

- `telemetry_anomaly_score`
- `telemetry_anomaly_evaluations_total`
- `telemetry_evaluation_conflicts_total`
- `telemetry_incidents_created_total`
- `telemetry_incident_conflicts_total`
- `telemetry_ai_processing_errors_total`
- `telemetry_ai_db_retries_total`

## Article context

This branch supports Part 3 of the **Yüksek Teknolojide Yazılım Omurgası** series:

> Aynı telemetri paketi iki kez gelirse ne olur?

The implementation turns that question into visible proof through database constraints, row locking, automated tests, integration CI, metrics, and a Grafana dashboard.
