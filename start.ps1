# Codonova Startup Script
# Run this script from the autonomousdev directory
# Usage: .\start.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Title($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-OK($msg)    { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-WARN($msg)  { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-ERR($msg)   { Write-Host "  ✗ $msg" -ForegroundColor Red }

Write-Host @"

  ██████╗ ██████╗ ██████╗  ██████╗ ███╗   ██╗ ██████╗ ██╗   ██╗ █████╗
 ██╔════╝██╔═══██╗██╔══██╗██╔═══██╗████╗  ██║██╔═══██╗██║   ██║██╔══██╗
 ██║     ██║   ██║██║  ██║██║   ██║██╔██╗ ██║██║   ██║██║   ██║███████║
 ██║     ██║   ██║██║  ██║██║   ██║██║╚██╗██║██║   ██║╚██╗ ██╔╝██╔══██║
 ╚██████╗╚██████╔╝██████╔╝╚██████╔╝██║ ╚████║╚██████╔╝ ╚████╔╝ ██║  ██║
  ╚═════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝   ╚═══╝  ╚═╝  ╚═╝
         Autonomous Software Development System

"@ -ForegroundColor Magenta

# ── Check .env ────────────────────────────────────────────────────────────────
Write-Title "Checking configuration"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-WARN ".env created from .env.example — please fill in your API keys!"
    Write-Host "  Edit: $(Resolve-Path '.env')" -ForegroundColor Yellow
} else {
    $envContent = Get-Content ".env" -Raw
    $keys = @("GEMINI_API_KEY", "GROQ_API_KEY")
    $missingKeys = @()
    foreach ($key in $keys) {
        if ($envContent -match "$key=your_") {
            $missingKeys += $key
        }
    }
    if ($missingKeys.Count -gt 0) {
        Write-WARN "Missing API keys in .env:"
        foreach ($k in $missingKeys) { Write-Host "    - $k" -ForegroundColor Yellow }
        Write-Host "  Get free keys from: https://aistudio.google.com and https://console.groq.com" -ForegroundColor Yellow
        $answer = Read-Host "  Continue anyway? (y/N)"
        if ($answer -ne "y") { exit 1 }
    } else {
        Write-OK ".env configured"
    }
}

# ── Check Docker ──────────────────────────────────────────────────────────────
Write-Title "Checking Docker"
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not running" }
    Write-OK "Docker daemon running"
} catch {
    Write-WARN "Docker Desktop not running. Attempting to start..."
    $dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerPath) {
        Start-Process $dockerPath
        Write-Host "  Waiting for Docker to start (up to 90 seconds)..." -ForegroundColor Yellow
        $ready = $false
        for ($i = 0; $i -lt 18; $i++) {
            Start-Sleep 5
            $result = docker info 2>&1
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            Write-Host "  ." -NoNewline -ForegroundColor Gray
        }
        if ($ready) {
            Write-OK "Docker started"
        } else {
            Write-ERR "Docker failed to start. Please start Docker Desktop manually."
            exit 1
        }
    } else {
        Write-ERR "Docker Desktop not found. Install from https://docker.com/products/docker-desktop"
        exit 1
    }
}

# ── Build & Start Services ─────────────────────────────────────────────────────
Write-Title "Starting Codonova services"
Write-Host "  Starting: Neo4j, ChromaDB, Backend, Frontend..." -ForegroundColor Cyan

docker-compose up -d --build 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-ERR "docker-compose failed. Check the output above."
    exit 1
}

# ── Wait for health ────────────────────────────────────────────────────────────
Write-Title "Waiting for services to be healthy"
Write-Host "  This may take 30-60 seconds on first run..." -ForegroundColor Yellow

$maxWait = 120
$interval = 5
$elapsed = 0

while ($elapsed -lt $maxWait) {
    Start-Sleep $interval
    $elapsed += $interval

    $backendOk = $false
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { $backendOk = $true }
    } catch {}

    $neo4jOk = $false
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:7474" -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { $neo4jOk = $true }
    } catch {}

    if ($backendOk -and $neo4jOk) {
        Write-OK "All services ready!"
        break
    }

    Write-Host "  Waiting... ($elapsed/$maxWait s)" -ForegroundColor Gray
}

# ── Status Summary ─────────────────────────────────────────────────────────────
Write-Title "Codonova is ready!"
Write-Host @"

  Service URLs:
    🌐 Dashboard:     http://localhost:3000
    📚 API Docs:      http://localhost:8000/docs
    🔍 Neo4j Browser: http://localhost:7474
    🗃 ChromaDB:      http://localhost:8001

  Quick API test:
    curl -X POST http://localhost:8000/api/plan -H "Content-Type: application/json" -d '{"requirement": "Build a todo list REST API"}'

  View logs:
    docker-compose logs -f backend

  Stop:
    docker-compose down
"@ -ForegroundColor Green

# ── Open browser ──────────────────────────────────────────────────────────────
$openBrowser = Read-Host "`nOpen Dashboard in browser? (Y/n)"
if ($openBrowser -ne "n") {
    Start-Process "http://localhost:3000"
}
