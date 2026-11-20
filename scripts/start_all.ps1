# One command to start everything:
#   powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1           (LIVE + FAKE if Docker runs, else FAKE)
#   powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1 -Fake     (force FAKE mode, no Docker)
# Opens two windows (backend, dashboard) and the dashboard in your browser.
# Stop: powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1
param([switch]$Fake, [switch]$NoBrowser)

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
function Say($text, $color = "Cyan") { Write-Host $text -ForegroundColor $color }
function Is-Up($url) { try { Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 10 | Out-Null; $true } catch { $false } }
function Find-Docker {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe", "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Say "`nPager Intelligence - starting everything`n"
if (-not (Test-Path ".venv\Scripts\python.exe")) { Say "Python venv missing. Run scripts\preflight.ps1 for the fix." Red; exit 1 }

# 1. Docker stack (optional)
$mode = "fake"
$docker = Find-Docker
if ($Fake) {
    Say "1/4 FAKE mode requested: skipping Docker." Yellow
} elseif (-not $docker) {
    Say "1/4 Docker is not installed -> starting in FAKE mode (demo replay + story work fully offline)." Yellow
} else {
    & $docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Say "1/4 Docker is not running -> starting in FAKE mode. (Open Docker Desktop and re-run for LIVE data.)" Yellow
    } else {
        Say "1/4 Starting the Docker stack (Prometheus, Alertmanager, Loki, Promtail, victim app, Postgres)..."
        & $docker compose -f infra\docker-compose.yml up -d --build 2>&1 | Select-String "Started|Running|Error|error" | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -eq 0) { $mode = "both"; Say "    stack is up: LIVE + FAKE mode" Green }
        else { Say "    Docker stack failed -> continuing in FAKE mode" Yellow }
    }
}

# 2. Backend
if (Is-Up "http://127.0.0.1:8000/health") {
    Say "2/4 Backend already running on :8000 (reusing it)." Yellow
} else {
    Say "2/4 Starting the backend (new window 'Pager backend')..."
    $cmd = "`$host.UI.RawUI.WindowTitle = 'Pager backend'; `$env:PAGER_DATA_SOURCE = '$mode'; Set-Location '$root'; .\.venv\Scripts\python.exe -m backend"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
}

# 3. Dashboard
if (Is-Up "http://localhost:5173") {
    Say "3/4 Dashboard already running on :5173 (reusing it)." Yellow
} else {
    Say "3/4 Starting the dashboard (new window 'Pager dashboard')..."
    $install = if (Test-Path "frontend\node_modules") { "" } else { "npm install; " }
    $cmd = "`$host.UI.RawUI.WindowTitle = 'Pager dashboard'; Set-Location '$root\frontend'; ${install}npm run dev"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
}

# 4. Wait until both answer, then open the browser
Say "4/4 Waiting for the backend (loads the AI models, ~20-40 s) and the dashboard..."
$deadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $deadline -and -not ((Is-Up "http://127.0.0.1:8000/health") -and (Is-Up "http://localhost:5173"))) { Start-Sleep -Seconds 2 }
if (-not ((Is-Up "http://127.0.0.1:8000/health") -and (Is-Up "http://localhost:5173"))) {
    Say "Something did not start within 3 minutes. Look at the 'Pager backend' / 'Pager dashboard' windows for the error." Red
    exit 1
}
$health = Invoke-RestMethod "http://127.0.0.1:8000/health"
Say "`nReady." Green
Say ("  data source : {0}" -f $health.data_source.ToUpper()) White
Say ("  local LLM   : {0} ({1})" -f $health.ollama.model, $(if ($health.ollama.ok) { "running" } else { "NOT running - TLS will use the cached sample answer" })) White
Say  "  dashboard   : http://localhost:5173   -> press 'Demo story'" White
if ($mode -eq "both") { Say "  chaos       : powershell -ExecutionPolicy Bypass -File scripts\chaos_demo.ps1" White }
Say  "  stop        : powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1" White
if (-not $NoBrowser) { Start-Process "http://localhost:5173" }
