param(
    [switch]$Reset
)

$ErrorActionPreference = "Stop"

if ($Reset) {
    Write-Host "Resetting containers and PostgreSQL volume..."
    docker compose down -v
}

Write-Host "Starting Edge Mission Telemetry stack..."
docker compose up -d --build

Write-Host "Waiting for ingest service, database and MQTT subscription..."
$healthy = $false
for ($attempt = 1; $attempt -le 45; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/healthz" -TimeoutSec 2
        if ($health.status -eq "ok" -and $health.database -eq "reachable" -and $health.mqtt -eq "subscribed") {
            $healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    docker compose ps
    docker compose logs ingest mqtt postgres
    throw "Ingest service did not become ready with both PostgreSQL and MQTT."
}

$payload = '{"device_id":"node-part3","seq":42,"ts":1772490151,"temp":60.0,"vibration":0.95}'

Write-Host "Publishing the same telemetry packet concurrently..."
docker compose exec -T -e "PAYLOAD=$payload" mqtt sh -c 'mosquitto_pub -h localhost -q 1 -t telemetry/node-part3 -m "$PAYLOAD" & mosquitto_pub -h localhost -q 1 -t telemetry/node-part3 -m "$PAYLOAD" & wait'

Write-Host "Waiting for ingestion and anomaly evaluation..."
$telemetryRows = "0"
$evaluationRows = "0"
$incidentRows = "0"

for ($attempt = 1; $attempt -le 30; $attempt++) {
    $telemetryRows = (docker compose exec -T postgres psql -U telemetry -d telemetry -tAc "SELECT COUNT(*) FROM telemetry_events WHERE device_id='node-part3' AND seq=42;").Trim()
    $evaluationRows = (docker compose exec -T postgres psql -U telemetry -d telemetry -tAc "SELECT COUNT(*) FROM telemetry_evaluations e JOIN telemetry_events t ON t.id=e.telemetry_event_id WHERE t.device_id='node-part3' AND t.seq=42;").Trim()
    $incidentRows = (docker compose exec -T postgres psql -U telemetry -d telemetry -tAc "SELECT COUNT(*) FROM incidents i JOIN telemetry_events t ON t.id=i.telemetry_event_id WHERE t.device_id='node-part3' AND t.seq=42;").Trim()

    if ($telemetryRows -eq "1" -and $evaluationRows -eq "1" -and $incidentRows -eq "1") {
        break
    }

    Start-Sleep -Seconds 1
}

$ingestMetrics = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/metrics").Content
$aiMetrics = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:9101/metrics").Content

$packetConflict = ($ingestMetrics -split "`n" | Where-Object { $_ -match '^telemetry_db_conflicts_total ' } | Select-Object -First 1).Trim()
$evaluationMetric = ($aiMetrics -split "`n" | Where-Object { $_ -match '^telemetry_anomaly_evaluations_total ' } | Select-Object -First 1).Trim()
$incidentMetric = ($aiMetrics -split "`n" | Where-Object { $_ -match '^telemetry_incidents_created_total ' } | Select-Object -First 1).Trim()

Write-Host ""
Write-Host "=== PART 3 RELIABILITY PROOF ==="
Write-Host "Concurrent messages sent : 2"
Write-Host "Telemetry rows stored    : $telemetryRows"
Write-Host "Evaluation rows stored   : $evaluationRows"
Write-Host "Incident rows stored     : $incidentRows"
Write-Host "Packet conflict metric   : $packetConflict"
Write-Host "Evaluation metric        : $evaluationMetric"
Write-Host "Incident metric          : $incidentMetric"
Write-Host "Grafana dashboard        : http://localhost:3000"
Write-Host "Grafana login            : admin / admin"
Write-Host ""

if ($telemetryRows -ne "1" -or $evaluationRows -ne "1" -or $incidentRows -ne "1") {
    docker compose logs ingest mqtt ai postgres
    throw "Reliability proof failed: expected one telemetry row, one evaluation and one incident."
}

Write-Host "PASS: duplicate delivery produced one stored packet, one evaluation and one incident."
