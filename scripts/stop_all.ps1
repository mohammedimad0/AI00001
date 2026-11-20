# Stops what start_all.ps1 started: backend, dashboard, and the Docker stack (if running).
#   powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1
$root = Split-Path $PSScriptRoot -Parent
foreach ($port in 8000, 5173) {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($owner) {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($owner.OwningProcess)").CommandLine
        if ($cmd -match "-m backend|vite") { Stop-Process -Id $owner.OwningProcess -Force; Write-Host "stopped :$port" }
        else { Write-Host "port $port is used by something else, left alone: $cmd" -ForegroundColor Yellow }
    }
}
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) { $docker = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" }
if (Test-Path $docker) {
    & $docker info *> $null
    if ($LASTEXITCODE -eq 0) { & $docker compose -f "$root\infra\docker-compose.yml" down; Write-Host "Docker stack stopped" }
}
