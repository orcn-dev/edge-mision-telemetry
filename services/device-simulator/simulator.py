import json, time, random
import paho.mqtt.client as mqtt

client = mqtt.Client()
client.connect("localhost", 1883, 60)

seq = 0
while True:
    payload = {
        "device_id": "node-01",
        "temp": round(random.uniform(30, 60), 2),
        "vibration": round(random.uniform(0, 1), 3),
        "seq": seq,
        "ts": int(time.time())
    }
    client.publish("telemetry/node-01", json.dumps(payload))
    print("sent:", payload)
    seq += 1
    time.sleep(1)