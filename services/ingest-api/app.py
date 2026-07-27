import json
import logging
import os
import time
from typing import Any, Callable, Dict, Literal

import psycopg2
from fastapi import FastAPI, Response, status
from paho.mqtt import client as mqtt
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "telemetry/#")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "telemetry")
PG_USER = os.getenv("PG_USER", "telemetry")
PG_PASS = os.getenv("PG_PASS", "telemetry")

DB_MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", "5"))
DB_RETRY_BASE_SECONDS = float(os.getenv("DB_RETRY_BASE_SECONDS", "0.25"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("telemetry-ingest")

TELEMETRY_MESSAGES = Counter(
    "telemetry_messages_total",
    "Total MQTT telemetry messages received",
)
TELEMETRY_DB_INSERTS = Counter(
    "telemetry_db_inserts_total",
    "Telemetry packets inserted into PostgreSQL",
)
TELEMETRY_DB_CONFLICTS = Counter(
    "telemetry_db_conflicts_total",
    "Duplicate telemetry packets rejected by the idempotency constraint",
)
TELEMETRY_INGEST_ERRORS = Counter(
    "telemetry_ingest_errors_total",
    "Telemetry packets that could not be processed",
)
TELEMETRY_DB_RETRIES = Counter(
    "telemetry_db_retries_total",
    "Database connection retries performed by the ingest service",
)
TELEMETRY_LAST_MESSAGE_TS = Gauge(
    "telemetry_last_message_timestamp_seconds",
    "Unix timestamp of the last MQTT telemetry message",
)

InsertResult = Literal["inserted", "duplicate"]
ConnectionFactory = Callable[[], Any]


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))


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
            TELEMETRY_DB_RETRIES.inc()
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


def insert_event(
    payload: Dict[str, Any],
    connection_factory: ConnectionFactory = pg_conn,
) -> InsertResult:
    device_id = str(payload.get("device_id", "unknown"))
    seq = int(payload.get("seq", -1))
    ts = int(payload.get("ts", int(time.time())))
    temp = payload.get("temp")
    vibration = payload.get("vibration")

    sql = """
        INSERT INTO telemetry_events (device_id, seq, ts, temp, vibration, raw)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (device_id, seq) DO NOTHING
        RETURNING id;
    """

    with connect_with_retry(connection_factory) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (device_id, seq, ts, temp, vibration, json.dumps(payload)),
            )
            inserted = cur.fetchone()

    if inserted is None:
        TELEMETRY_DB_CONFLICTS.inc()
        log_event("telemetry_duplicate", device_id=device_id, seq=seq)
        return "duplicate"

    TELEMETRY_DB_INSERTS.inc()
    log_event(
        "telemetry_inserted",
        telemetry_event_id=inserted[0],
        device_id=device_id,
        seq=seq,
    )
    return "inserted"


def on_connect(client, userdata, flags, reason_code, properties=None):
    if int(reason_code) != 0:
        logger.error("MQTT connection failed with reason code %s", reason_code)
        return

    client.subscribe(MQTT_TOPIC)
    log_event("mqtt_subscribed", topic=MQTT_TOPIC)


def on_message(client, userdata, msg):
    TELEMETRY_MESSAGES.inc()
    TELEMETRY_LAST_MESSAGE_TS.set(time.time())

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        insert_event(payload)
    except (ValueError, TypeError, json.JSONDecodeError, psycopg2.Error):
        TELEMETRY_INGEST_ERRORS.inc()
        logger.exception(
            json.dumps(
                {
                    "event": "telemetry_processing_failed",
                    "topic": msg.topic,
                },
                sort_keys=True,
            )
        )


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

app = FastAPI(title="Edge Mission Telemetry Ingest API", version="0.2.0")


@app.on_event("startup")
def startup():
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_start()


@app.on_event("shutdown")
def shutdown():
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


@app.get("/healthz")
def healthz(response: Response):
    try:
        with pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "database": "reachable"}
    except psycopg2.Error as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unreachable", "error": str(exc)}


@app.get("/metrics")
def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
