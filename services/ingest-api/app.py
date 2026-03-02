import json
import os
import time
from typing import Any, Dict

import psycopg2
from fastapi import FastAPI, Response
from paho.mqtt import client as mqtt

# ---- Config ----
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "telemetry/#")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "telemetry")
PG_USER = os.getenv("PG_USER", "telemetry")
PG_PASS = os.getenv("PG_PASS", "telemetry")

# ---- Simple in-memory metrics ----
metrics = {
    "telemetry_messages_total": 0,
    "telemetry_db_inserts_total": 0,
    "telemetry_db_conflicts_total": 0,
    "telemetry_last_message_ts": 0,
    "telemetry_ingest_errors_total": 0,
}

def pg_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS
    )

def insert_event(payload: Dict[str, Any]) -> None:
    device_id = str(payload.get("device_id", "unknown"))
    seq = int(payload.get("seq", -1))
    ts = int(payload.get("ts", int(time.time())))
    temp = payload.get("temp")
    vibration = payload.get("vibration")

    sql = """
    INSERT INTO telemetry_events (device_id, seq, ts, temp, vibration, raw)
    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (device_id, seq) DO NOTHING;
    """

    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (device_id, seq, ts, temp, vibration, json.dumps(payload)))
            if cur.rowcount == 1:
                metrics["telemetry_db_inserts_total"] += 1
            else:
                metrics["telemetry_db_conflicts_total"] += 1

# ---- MQTT callbacks ----
def on_connect(client, userdata, flags, rc, properties=None):
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        metrics["telemetry_messages_total"] += 1
        metrics["telemetry_last_message_ts"] = int(time.time())
        insert_event(payload)
    except Exception:
        metrics["telemetry_ingest_errors_total"] += 1

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

app = FastAPI(title="Ingest API", version="0.1.0")

@app.on_event("startup")
def startup():
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_start()

@app.on_event("shutdown")
def shutdown():
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/metrics")
def prometheus_metrics():
    # minimal Prometheus exposition format
    lines = []
    for k, v in metrics.items():
        lines.append(f"# TYPE {k} counter")
        lines.append(f"{k} {v}")
    return Response("\n".join(lines) + "\n", media_type="text/plain")