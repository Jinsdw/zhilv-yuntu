param(
    [switch]$Status,
    [switch]$Stop,
    [switch]$Restart,
    [switch]$Build,
    [switch]$Logs,
    [string]$Service
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Write-Success { param($Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Warn { param($Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Err { param($Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Show-Banner {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Magenta
    Write-Host "       ZHiLv YunTu - Service Starter" -ForegroundColor Magenta
    Write-Host "========================================" -ForegroundColor Magenta
    Write-Host ""
}

function Test-DockerRunning {
    try {
        $null = docker info 2>&1
        return $true
    }
    catch {
        return $false
    }
}

function Test-DockerCompose {
    try {
        $null = docker-compose --version 2>&1
        return $true
    }
    catch {
        return $false
    }
}

function Initialize-EnvFile {
    $envFile = ".env"
    $envExample = ".env.example"

    if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
        Write-Info "Copying env template..."
        Copy-Item $envExample $envFile
        Write-Success "Created .env file"
        Write-Warn "Please edit .env and fill in your API keys"
        return $false
    }
    return $true
}

function Start-Services {
    Show-Banner

    if (-not (Test-DockerRunning)) {
        Write-Err "Docker is not running. Please start Docker Desktop"
        exit 1
    }

    if (-not (Test-DockerCompose)) {
        Write-Err "Docker Compose is not installed"
        exit 1
    }

    $envReady = Initialize-EnvFile
    if (-not $envReady) {
        Write-Host ""
        Write-Warn "Please configure .env file and run again"
        exit 0
    }

    Write-Info "Starting services..."
    docker-compose up -d

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Services started successfully!"
        Write-Host ""
        Show-Status
    }
    else {
        Write-Err "Failed to start services"
        exit 1
    }
}

function Stop-Services {
    Show-Banner
    Write-Info "Stopping services..."
    docker-compose down
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Services stopped"
    }
}

function Restart-Services {
    Show-Banner
    Stop-Services
    Start-Services
}

function Show-Status {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host "           Service Status" -ForegroundColor Cyan
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host ""

    docker-compose ps

    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host "           Access URLs" -ForegroundColor Cyan
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Backend API: http://localhost:8000" -ForegroundColor Yellow
    Write-Host "  API Docs: http://localhost:8000/docs" -ForegroundColor Yellow
    Write-Host "  Redis: localhost:6379" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Frontend (local Node.js):" -ForegroundColor Cyan
    Write-Host "    cd frontend; npm install; npm run dev" -ForegroundColor Yellow
    Write-Host "    URL: http://localhost:5173" -ForegroundColor Yellow
    Write-Host ""
}

function Show-Logs {
    if ($Service) {
        docker-compose logs -f $Service
    }
    else {
        docker-compose logs -f
    }
}

function Build-Images {
    Show-Banner
    Write-Info "Building Docker images..."
    docker-compose build --no-cache
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Images built successfully"
    }
    else {
        Write-Err "Failed to build images"
        exit 1
    }
}

switch ($true) {
    $Status  { Show-Status }
    $Stop    { Stop-Services }
    $Restart { Restart-Services }
    $Logs    { Show-Logs }
    $Build   { Build-Images }
    default  { Start-Services }
}
