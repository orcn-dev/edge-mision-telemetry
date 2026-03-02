import time
import psycopg2
from prometheus_client import start_http_server, Gauge

conn = psycopg2.connect(
    host="postgres",
    dbname="telemetry",
    user="telemetry",
    password="telemetry",
    port=5432,
)
conn.autocommit = True

anomaly_metric = Gauge("telemetry_anomaly_score", "Current anomaly score")

def detect_anomaly(temp, vibration):
    score = 0.0
    if temp is not None and temp > 55:
        score += 0.6
    if vibration is not None and vibration > 0.8:
        score += 0.6
    return min(score, 1.0)

def loop():
    while True:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT device_id, ts, temp, vibration
                FROM telemetry_events
                ORDER BY id DESC
                LIMIT 1
            """)
            row = cur.fetchone()

            if row:
                device_id, ts, temp, vibration = row
                score = detect_anomaly(temp, vibration)
                anomaly_metric.set(score)

                if score >= 0.9:
                    cur.execute("""
                        INSERT INTO incidents(device_id, ts, anomaly_score, reason)
                        VALUES (%s,%s,%s,%s)
                    """, (device_id, ts, score, "High temp/vibration"))

                print(f"score: {score:.2f} | temp={temp} vib={vibration}")

        time.sleep(5)

if __name__ == "__main__":
    start_http_server(9101)
    print("AI metrics on http://localhost:9101/metrics")
    loop()