# Edge Mission Telemetry 🚀

A containerized edge telemetry simulation platform with real-time
ingestion, anomaly scoring, and observability.

This project demonstrates an end-to-end data pipeline:

Device Simulator → MQTT → Ingest API → PostgreSQL → AI Service →
Prometheus → Grafana

------------------------------------------------------------------------

## 🧱 Architecture

-   **MQTT (Mosquitto)** -- Message broker for device telemetry
-   **Ingest Service (FastAPI + MQTT client)** -- Consumes telemetry and
    writes to PostgreSQL
-   **PostgreSQL** -- Persistent event storage
-   **AI Service** -- Computes anomaly scores from latest telemetry
-   **Prometheus** -- Metrics scraping
-   **Grafana** -- Visualization dashboards

------------------------------------------------------------------------

## 📡 Telemetry Flow

1.  Device simulator publishes JSON messages:

    ``` json
    {
      "device_id": "node-01",
      "temp": 57.7,
      "vibration": 0.635,
      "seq": 2336,
      "ts": 1772490151
    }
    ```

2.  Ingest service:

    -   Subscribes to `telemetry/#`
    -   Inserts into `telemetry_events`
    -   Handles idempotency via `(device_id, seq)` uniqueness

3.  AI service:

    -   Reads latest telemetry
    -   Computes anomaly score
    -   Exposes Prometheus metric on port 9101

------------------------------------------------------------------------

## 🗄 Database Schema

### telemetry_events

-   id (BIGSERIAL PRIMARY KEY)
-   device_id (TEXT)
-   seq (INT)
-   ts (BIGINT)
-   temp (FLOAT)
-   vibration (FLOAT)
-   raw (JSONB)

Unique index:

    (device_id, seq)

### incidents

-   id (BIGSERIAL PRIMARY KEY)
-   device_id (TEXT)
-   ts (BIGINT)
-   score (FLOAT)
-   reason (TEXT)
-   created_at (TIMESTAMPTZ)

------------------------------------------------------------------------

## 📊 Metrics

### Ingest Metrics (Port 8000)

-   telemetry_messages_total
-   telemetry_db_inserts_total
-   telemetry_db_conflicts_total
-   telemetry_last_message_ts
-   telemetry_ingest_errors_total

### AI Metrics (Port 9101)

-   telemetry_anomaly_score

------------------------------------------------------------------------

## 🐳 Run with Docker

``` bash
docker compose up -d --build
```

Check services:

``` bash
docker compose ps
```

View logs:

``` bash
docker compose logs -f
```

------------------------------------------------------------------------

## 🔍 Troubleshooting

### High conflict count

If `telemetry_db_conflicts_total` increases but inserts stop:

This typically happens when the device simulator restarts and replays
existing `(device_id, seq)` values.

Solutions: - Truncate table (demo environment) - Use UPSERT instead of
DO NOTHING - Add session/boot identifier to uniqueness constraint

------------------------------------------------------------------------

## 🧠 Anomaly Logic

Current detection logic:

-   +0.6 score if temp \> 55
-   +0.6 score if vibration \> 0.8
-   Score capped at 1.0
-   Incident triggered when score \>= 0.9

------------------------------------------------------------------------

## 🎯 Purpose

This project demonstrates:

-   Event-driven architecture
-   Idempotent ingestion design
-   MQTT-based telemetry
-   Observability-first engineering
-   Real-time anomaly scoring
-   Containerized microservice deployment

------------------------------------------------------------------------

## 📌 Future Improvements

-   Session-aware device identity
-   Schema migrations
-   Alertmanager integration
-   Distributed scaling test
-   Retention & partitioning strategy

------------------------------------------------------------------------

Built for experimentation, observability practice, and edge data
engineering workflows.
