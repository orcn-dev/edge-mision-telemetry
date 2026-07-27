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

Write-Host "Waiting for ingest service health..."
$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/healthz" -TimeoutSec 2
        if ($health.status -eq "ok") {
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
    docker compose logs ingest postgres
    throw "Ingest service did not become healthy."
}

$payload = '{"device_id":"node-part3","seq":42,"ts":1772490151,"temp":60.0,"vibration":0.95}'

Write-Host "Publishing the same telemetry packet from two concurrent processes..."
$first = Start-Job -ScriptBlock {
    param($message)
    docker compose exec -T mqtt mosquitto_pub -h localhost -t telemetry/node-part3 -m $message
} -ArgumentList $payload

$second = Start-Job -ScriptBlock {
    param($message)
    docker compose exec -T mqtt mosquitto_pub -h localhost -t telemetry/node-part3 -m $message
} -ArgumentList $payload

Wait-Job $first, $second | Out-Null
Receive-Job $first, $second
Remove-Job $first, $second

Write-Host "Waiting for ingestion and anomaly evaluation..."
Start-Sleep -Seconds 12

$telemetryRows = (docker compose exec -T postgres psql -U telemetry -d telemetry -tAc "SELECT COUNT(*) FROM telemetry_events WHERE device_id='node-part3' AND seq=42;").Trim()
$incidentRows = (docker compose exec -T postgres psql -U telemetry -d telemetry -tAc "SELECT COUNT(*) FROM incidents i JOIN telemetry_events t ON t.id=i.telemetry_event_id WHERE t.device_id='node-part3' AND t.seq=42;").Trim()

$ingestMetrics = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/metrics").Content
$aiMetrics = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:9101/metrics").Content

$packetConflict = ($ingestMetrics -split "`n" | Where-Object { $_ -match '^telemetry_db_conflicts_total ' } | Select-Object -First 1).Trim()
$incidentConflict = ($aiMetrics -split "`n" | Where-Object { $_ -match '^telemetry_incident_conflicts_total ' } | Select-Object -First 1).Trim()

Write-Host ""
Write-Host "=== PART 3 RELIABILITY PROOF ==="
Write-Host "Concurrent messages sent : 2"
Write-Host "Telemetry rows stored    : $telemetryRows"
Write-Host "Incident rows stored     : $incidentRows"
Write-Host "Packet conflict metric   : $packetConflict"
Write-Host "Incident conflict metric : $incidentConflict"
Write-Host "Grafana dashboard        : http://localhost:3000"
Write-Host "Grafana login            : admin / admin"
Write-Host ""

if ($telemetryRows -ne "1" -or $incidentRows -ne "1") {
    throw "Reliability proof failed: expected exactly one telemetry row and one incident."
}

Write-Host "PASS: duplicate delivery produced one telemetry row and one incident."
