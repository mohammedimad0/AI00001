# Fires every chaos scenario at the victim app, in order, with pauses (~6 minutes).
#   powershell -ExecutionPolicy Bypass -File scripts\chaos_demo.ps1
#   ... -Pause 10        shorter waits
#   ... -NoDocker        don't stop/start the Postgres container (db-down is then only simulated)
param(
    [string]$Victim = "http://localhost:8080",
    [int]$Pause = 20,
    [switch]$NoDocker
)
$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "..\infra\docker-compose.yml"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Note($text) { Write-Host "   $text" -ForegroundColor DarkGray }
function Wait-For($seconds, $why) { Note "waiting $seconds s ($why)"; Start-Sleep -Seconds $seconds }
function Chaos($path, $ip = $null) {
    $headers = @{}
    if ($ip) { $headers["X-Forwarded-For"] = $ip }
    $r = Invoke-RestMethod -Method Post -Uri "$Victim$path" -Headers $headers
    Note ("victim: " + ($r | ConvertTo-Json -Compress))
}

try { Invoke-RestMethod "$Victim/healthz" | Out-Null } catch {
    Write-Host "Victim app not reachable at $Victim. Start the stack first:" -ForegroundColor Red
    Write-Host "  docker compose -f infra\docker-compose.yml up -d --build"
    exit 1
}

Step "1/5 Brute-force login attack from North Korea (175.45.176.0/22): 2 IPs x 100 attempts"
Chaos "/chaos/bruteforce" "175.45.176.23"
Chaos "/chaos/bruteforce" "175.45.177.104"
Step "    + 3 ordinary failed logins from India (49.36.0.0/14), spread out"
foreach ($ip in "49.36.12.7", "49.37.200.15", "49.38.4.90") {
    try {
        Invoke-RestMethod -Method Post -Uri "$Victim/login" -ContentType "application/json" `
            -Headers @{ "X-Forwarded-For" = $ip } -Body '{"user":"priya","password":"wrong"}' | Out-Null
    } catch { Note "login from $ip rejected (401), as a mistyped password would be" }
    Start-Sleep -Seconds 5
}
Wait-For $Pause "logs reach Loki -> poller (every 10 s) -> incidents"

Step "2/5 CPU spike on the victim for 60 s (HighCPU fires, then resolves by itself)"
Chaos "/chaos/cpu?seconds=60"
Wait-For ($Pause + 70) "alert fires after ~20 s, resolves ~30 s after the burn ends"

Step "3/5 Fill the victim's /data disk to 95% for 45 s (DiskAlmostFull)"
Chaos "/chaos/disk?seconds=45"
Wait-For ($Pause + 40) "alert fires, Alertmanager waits 10 s (group_wait), webhook"

Step "4/5 Database outage: victim cannot reach db-primary for 90 s"
Chaos "/chaos/db-down?seconds=90"
if (-not $NoDocker) {
    Note "also stopping the real Postgres container, so TargetDown fires in Prometheus"
    docker compose -f $compose stop db-primary | Out-Null
    Wait-For 60 "Connection refused logs + TargetDown + HighErrorRate"
    docker compose -f $compose start db-primary | Out-Null
    Note "Postgres started again"
    Wait-For ($Pause + 10) "recovery"
} else {
    Wait-For 90 "Connection refused logs + HighErrorRate"
}

Step "5/5 Expired TLS certificate: 3 client hosts fail the handshake with api-gateway for 60 s"
Chaos "/chaos/tls?seconds=60"
Wait-For ($Pause + 50) "no runbook for TLS -> the local LLM writes the fix"

Chaos "/chaos/stop"
Step "Done. Look at the dashboard: http://localhost:5173"
