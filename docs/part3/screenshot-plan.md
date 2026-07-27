# Part 3 Screenshot Plan

## 01 — Architecture

Capture or render the flow:

```text
Device -> MQTT -> Ingest API -> PostgreSQL -> Anomaly Service -> Prometheus -> Grafana
```

Caption:

> Telemetri paketi edge katmanından gözlemlenebilirlik katmanına kadar tek bir operasyon zinciri içinde ilerliyor.

## 02 — Idempotent ingestion code + terminal proof

VS Code split view:

- Left: `services/ingest-api/app.py`
  - `ON CONFLICT (device_id, seq) DO NOTHING`
  - inserted / duplicate metric branches
- Right: PowerShell after running `./scripts/part3-demo.ps1 -Reset`

Expected terminal block:

```text
Concurrent messages sent : 2
Telemetry rows stored    : 1
Evaluation rows stored   : 1
Incident rows stored     : 1
PASS: duplicate delivery produced one stored packet, one evaluation and one incident.
```

Caption:

> Aynı paket iki eş zamanlı süreçten gönderildi. Sistem iki teslimatı gördü; ancak yalnızca bir telemetri kaydı, bir değerlendirme ve bir incident oluşturdu.

## 03 — Concurrency-safe anomaly worker

Capture `services/ai-service/ai_service.py` around:

```sql
FOR UPDATE OF t SKIP LOCKED
```

and:

```sql
INSERT INTO telemetry_evaluations ...
ON CONFLICT (telemetry_event_id) DO NOTHING
```

Caption:

> Satır kilidi çalışanların aynı işi paylaşmasını sağlar; unique constraint ise yarış koşuluna karşı son savunma hattıdır.

## 04 — Automated tests

Capture:

- `tests/test_ingest_idempotency.py`
- `tests/test_ai_incident_idempotency.py`
- terminal test result

Target result:

```text
8 passed
```

Caption:

> Başarılı senaryo kadar replay ve concurrency davranışı da otomatik testlerle korunuyor.

## 05 — GitHub Actions integration proof

Capture the successful `Reliability CI` workflow showing:

```text
unit-tests
integration-smoke
```

The integration job must visibly include:

```text
Publish the same telemetry packet concurrently
Verify exactly-once persistence and processing
Verify reliability metrics are visible
```

Caption:

> Pipeline yalnızca kodu test etmiyor; gerçek container stack'ini kurup duplicate teslimatın veritabanı sonucunu doğruluyor.

## 06 — Grafana reliability dashboard

Open:

```text
http://localhost:3000
admin / admin
```

Use the provisioned dashboard:

```text
Reliability / Edge Mission Telemetry — Reliability Overview
```

Keep these panels visible:

- Telemetry Throughput
- Duplicate Packets / 5m
- Ingest Errors / 5m
- Seconds Since Last Packet
- Anomaly Score by Device
- Unique Incidents / 5m

Caption:

> Idempotency duplicate veriyi engeller; observability ise duplicate teslimatın ne zaman ve ne sıklıkta gerçekleştiğini görünür kılar.
