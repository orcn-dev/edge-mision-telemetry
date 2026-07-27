import json
import logging
import os
import time
from typing import Any, Callable

import psycopg2
from prometheus_client import Counter, Gauge, start_http_server

PG_HOST = os.getenv("PG_HOST", "postgres")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "telemetry")
PG_USER = os.getenv("PG_USER", "telemetry")
PG_PASS = os.getenv("PG_PASS", "telemetry")
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "5"))
DB_MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", "5"))
DB_RETRY_BASE_SECONDS = float(os.getenv("DB_RETRY_BASE_SECONDS", "0.25"))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "100"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("telemetry-ai")

ANOMALY_SCORE = Gauge(
    "telemetry_anomaly_score",
    "Current anomaly score for the latest evaluated telemetry event",
    ["device_id"],
)
ANOMALY_EVALUATIONS = Counter(
    "telemetry_anomaly_evaluations_total",
    "Telemetry events evaluated by the anomaly service",
)
EVALUATION_CONFLICTS = Counter(
    "telemetry_evaluation_conflicts_total",
    "Duplicate anomaly evaluations rejected by the database constraint",
)
INCIDENTS_CREATED = Counter(
    "telemetry_incidents_created_total",
    "Unique incidents inserted into PostgreSQL",
)
INCIDENT_CONFLICTS = Counter(
    "telemetry_incident_conflicts_total",
    "Duplicate incident insertions rejected by the database constraint",
)
AI_PROCESSING_ERRORS = Counter(
    "telemetry_ai_processing_errors_total",
    "Anomaly evaluation or database processing failures",
)
AI_DB_RETRIES = Counter(
    "telemetry_ai_db_retries_total",
    "Database connection retries performed by the anomaly service",
)

ConnectionFactory = Callable[[], Any]


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))


def detect_anomaly(temp: float | None, vibration: float | None) -> float:
    score = 0.0
    if temp is not None and temp > 55:
        score += 0.6
    if vibration is not None and vibration > 0.8:
        score += 0.6
    return min(score, 1.0)


def pg_conn():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASS,
        connect_timeout=3,
    )


def connect_with_retry(connection_factory: ConnectionFactory = pg_conn):
    last_error: Exception | None = None

    for attempt in range(1, DB_MAX_RETRIES + 1):
        try:
            return connection_factory()
        except psycopg2.Error as exc:
            last_error = exc
            if attempt == DB_MAX_RETRIES:
                break

            delay = DB_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            AI_DB_RETRIES.inc()
            logger.warning(
                json.dumps(
                    {
                        "event": "database_connection_retry",
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "error": str(exc),
                    },
                    sort_keys=True,
                )
            )
            time.sleep(delay)

    assert last_error is not None
    raise last_error


def process_next_event(connection_factory: ConnectionFactory = pg_conn) -> str:
    conn = connect_with_retry(connection_factory)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.id, t.device_id, t.ts, t.temp, t.vibration
                    FROM telemetry_events AS t
                    LEFT JOIN telemetry_evaluations AS e
                        ON e.telemetry_event_id = t.id
                    WHERE e.telemetry_event_id IS NULL
                    ORDER BY t.id
                    LIMIT 1
                    FOR UPDATE OF t SKIP LOCKED
                    """
                )
                row = cur.fetchone()

                if row is None:
                    return "no_data"

                telemetry_event_id, device_id, ts, temp, vibration = row
                score = detect_anomaly(temp, vibration)
                is_anomaly = score >= 0.9

                cur.execute(
                    """
                    INSERT INTO telemetry_evaluations (
                        telemetry_event_id,
                        anomaly_score,
                        is_anomaly
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telemetry_event_id) DO NOTHING
                    RETURNING telemetry_event_id
                    """,
                    (telemetry_event_id, score, is_anomaly),
                )
                evaluation_inserted = cur.fetchone()

                if evaluation_inserted is None:
                    EVALUATION_CONFLICTS.inc()
                    log_event(
                        "evaluation_duplicate",
                        telemetry_event_id=telemetry_event_id,
                        device_id=device_id,
                    )
                    return "duplicate_evaluation"

                ANOMALY_SCORE.labels(device_id=device_id).set(score)
                ANOMALY_EVALUATIONS.inc()

                if not is_anomaly:
                    log_event(
                        "telemetry_evaluated",
                        telemetry_event_id=telemetry_event_id,
                        device_id=device_id,
                        anomaly_score=score,
                        incident_created=False,
                    )
                    return "normal"

                cur.execute(
                    """
                    INSERT INTO incidents (
                        telemetry_event_id,
                        device_id,
                        ts,
                        anomaly_score,
                        reason
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (telemetry_event_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        telemetry_event_id,
                        device_id,
                        ts,
                        score,
                        "High temperature/vibration anomaly score",
                    ),
                )
                incident_inserted = cur.fetchone()
    finally:
        conn.close()

    if incident_inserted is None:
        INCIDENT_CONFLICTS.inc()
        log_event(
            "incident_duplicate",
            telemetry_event_id=telemetry_event_id,
            device_id=device_id,
            anomaly_score=score,
        )
        return "duplicate_incident"

    INCIDENTS_CREATED.inc()
    log_event(
        "incident_created",
        incident_id=incident_inserted[0],
        telemetry_event_id=telemetry_event_id,
        device_id=device_id,
        anomaly_score=score,
    )
    return "incident_created"


def loop() -> None:
    while True:
        processed = 0

        try:
            while processed < MAX_BATCH_SIZE:
                result = process_next_event()
                if result == "no_data":
                    break
                processed += 1
        except (psycopg2.Error, ValueError, TypeError):
            AI_PROCESSING_ERRORS.inc()
            logger.exception(json.dumps({"event": "anomaly_processing_failed"}))

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    start_http_server(9101)
    log_event("metrics_server_started", port=9101)
    loop()
