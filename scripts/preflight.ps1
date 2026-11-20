# Pre-flight check before a demo: prints a green / yellow / red checklist, and the exact fix for each problem.
#   powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1
# Green = good. Yellow = optional or "not started yet" (the demo still works). Red = fix before the demo.

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$script:red = 0; $script:yellow = 0

function Ok($what, $detail = "")   { Write-Host "  [ OK ] " -ForegroundColor Green -NoNewline; Write-Host "$what " -NoNewline; Write-Host $detail -ForegroundColor DarkGray }
function Warn($what, $detail, $fix) { $script:yellow++; Write-Host "  [ -- ] " -ForegroundColor Yellow -NoNewline; Write-Host "$what " -NoNewline; Write-Host $detail -ForegroundColor DarkGray; if ($fix) { Write-Host "         fix: $fix" -ForegroundColor Yellow } }
function Bad($what, $detail, $fix)  { $script:red++;    Write-Host "  [FAIL] " -ForegroundColor Red -NoNewline;    Write-Host "$what " -NoNewline; Write-Host $detail -ForegroundColor DarkGray; Write-Host "         fix: $fix" -ForegroundColor Red }
function Get-Url($url, $timeout = 3) { try { Invoke-RestMethod -Uri $url -TimeoutSec $timeout } catch { $null } }
function Find-Docker {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe", "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "`nPager Intelligence - pre-flight check`n" -ForegroundColor Cyan

# 1. Python virtual environment + packages
if (-not (Test-Path $py)) {
    Bad "Python venv" "(.venv missing)" "python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
} else {
    & $py -c "import fastapi, chromadb, langgraph, sqlmodel, httpx" 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "Python venv" "($(& $py --version), packages installed)" }
    else { Bad "Python venv" "(packages missing)" ".\.venv\Scripts\pip install -r requirements.txt" }
}

# 2. Node + dashboard packages
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Bad "Node.js" "(not installed)" "winget install OpenJS.NodeJS.LTS   (then open a new terminal)" }
elseif (-not (Test-Path "frontend\node_modules")) { Bad "Node.js" "($(node --version), dashboard packages missing)" "cd frontend; npm install" }
else { Ok "Node.js" "($(node --version), dashboard packages installed)" }

# 3. Docker (optional: without it the demo runs in FAKE mode)
$docker = Find-Docker
if (-not $docker) { Warn "Docker" "(not installed - demo will run in FAKE mode)" "install Docker Desktop: https://www.docker.com/products/docker-desktop/" }
else {
    & $docker info *> $null
    if ($LASTEXITCODE -eq 0) { Ok "Docker running" "" }
    else { Warn "Docker" "(installed but not running - demo will run in FAKE mode)" "open Docker Desktop and wait for 'Engine running'" }
}

# 4 + 5. Ollama and the model from core\config.py
$model = (Select-String -Path "core\config.py" -Pattern '^LLM_MODEL\s*=\s*"([^"]+)"').Matches.Groups[1].Value
$tags = Get-Url "http://localhost:11434/api/tags"
if (-not $tags) {
    Bad "Ollama running" "(not reachable on :11434; TLS would use the cached sample answer)" "start the Ollama app from the Start menu, or run: ollama serve"
    Bad "Model $model pulled" "(cannot check while Ollama is down)" "ollama pull $model"
} else {
    Ok "Ollama running" ""
    if ($tags.models.name -contains $model) { Ok "Model $model pulled" "" }
    else { Bad "Model $model pulled" "(not found)" "ollama pull $model" }
}

# 6. Embedding model in the Hugging Face cache (needed offline)
$hf = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2\snapshots"
if ((Test-Path $hf) -and (Get-ChildItem $hf -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count -gt 3) { Ok "Embedding model cached" "(all-MiniLM-L6-v2, works offline)" }
else { Bad "Embedding model cached" "(not downloaded yet)" ".\.venv\Scripts\python.exe demo.py   (once, with internet)" }

# 7. ChromaDB seeded with the 25 runbooks
if (Test-Path $py) {
    $seed = & $py -c "import chromadb; from chromadb.config import Settings; c = chromadb.PersistentClient(path='chroma_db', settings=Settings(anonymized_telemetry=False)); col = c.get_or_create_collection('runbooks', metadata={'hnsw:space': 'cosine'}); print(len(col.get(where={'source': 'seed'})['ids']), col.count())" 2>$null
    $parts = "$seed".Trim() -split " "
    if ($parts.Count -eq 2 -and [int]$parts[0] -ge 25) { Ok "ChromaDB seeded" "($($parts[0]) seed runbooks, $($parts[1]) total)" }
    else { Bad "ChromaDB seeded" "(found '$seed')" ".\.venv\Scripts\python.exe -c `"from rag import store; print(store.load_runbooks())`"" }
}

# 8. Ports: free, or already used by OUR service
$checks = @(
    @{ port = 8000; name = "backend";    probe = { (Get-Url "http://127.0.0.1:8000/health") -ne $null } },
    @{ port = 5173; name = "dashboard";  probe = { try { (Invoke-WebRequest -UseBasicParsing "http://localhost:5173" -TimeoutSec 3).Content -match "Pager Intelligence" } catch { $false } } },
    @{ port = 9090; name = "Prometheus"; probe = { try { (Invoke-WebRequest -UseBasicParsing "http://localhost:9090/-/ready" -TimeoutSec 3).StatusCode -eq 200 } catch { $false } } },
    @{ port = 3100; name = "Loki";       probe = { try { (Invoke-WebRequest -UseBasicParsing "http://localhost:3100/ready" -TimeoutSec 3).StatusCode -eq 200 } catch { $false } } }
)
foreach ($c in $checks) {
    $owner = Get-NetTCPConnection -LocalPort $c.port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $owner) { Ok "Port $($c.port)" "(free)" }
    elseif (& $c.probe) { Ok "Port $($c.port)" "(in use by our $($c.name))" }
    else {
        $proc = (Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Bad "Port $($c.port)" "(taken by another program: $proc)" "Stop-Process -Id $($owner.OwningProcess)   (or close $proc)"
    }
}

# 9. Backend health (only if it is already running)
$health = Get-Url "http://127.0.0.1:8000/health" 5
if (-not $health) { Warn "Backend /health" "(not started yet)" "powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1" }
elseif ($health.status -eq "ok") { Ok "Backend /health" "(ok, data source: $($health.data_source), LLM warm-up: $($health.ollama.warmup.state))" }
else { Warn "Backend /health" "(degraded: ollama ok=$($health.ollama.ok), chromadb ok=$($health.chromadb.ok))" "see the red items above" }

Write-Host ""
if ($script:red -gt 0) { Write-Host "  $($script:red) problem(s) to fix before the demo." -ForegroundColor Red; exit 1 }
elseif ($script:yellow -gt 0) { Write-Host "  Ready (with $($script:yellow) optional item(s) above)." -ForegroundColor Yellow }
else { Write-Host "  All green. Ready for the demo." -ForegroundColor Green }
