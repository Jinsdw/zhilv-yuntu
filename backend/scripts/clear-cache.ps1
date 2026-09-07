# ============================================
# 智旅云图 - 缓存清理脚本
# ============================================

param(
    [switch]$RedisOnly,      
    [switch]$MemoryOnly,     
    [switch]$Confirm         
)

$ErrorActionPreference = "Stop"

function Write-Success { param($Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Warn { param($Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Err { param($Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }
function Write-Sep { Write-Host "----------------------------------------" -ForegroundColor DarkGray }

function Show-Banner {
    Write-Host ""
    Write-Sep
    Write-Host "  🧹 智旅云图 - 缓存清理工具" -ForegroundColor Magenta
    Write-Host "  Clear Cache Utility" -ForegroundColor Magenta
    Write-Sep
    Write-Host ""
}

function Clear-Cache-Redis {
    Write-Info "正在连接 Redis 容器..."
    try {
        $container = docker container ls -a --filter "name=zhilv-redis" --format "{{.Names}}" | Select-Object -First 1
        
        if (-not $container) {
            Write-Warn "未找到 Redis 容器 (zhilv-redis)"
            Write-Info "可以使用 Docker Desktop 启动 redis 服务"
            return $false
        }
        
        $output = docker exec $container redis-cli FLUSHALL 2>&1
        
        if ($LASTEXITCODE -eq 0 -and $output -match "OK") {
            Write-Success "Redis 缓存已清空"
            return $true
        } else {
            Write-Err "Redis 清空失败：$output"
            return $false
        }
    } catch {
        Write-Err "执行错误：$_"
        return $false
    }
}

function Clear-Cache-Memory {
    Write-Info "尝试通过 Python API 清空内存缓存..."
    $backendDir = Split-Path -Parent $PSScriptRoot
    $env:ZHILV_BACKEND_DIR = $backendDir
    $pythonCmd = @'
import os
import sys
sys.path.insert(0, os.environ['ZHILV_BACKEND_DIR'])
try:
    from app.services.cache_service import cache_service
    count = cache_service.clear_all()
    print(f"CLEAR_SUCCESS:{count}")
except Exception as e:
    print(f"CLEAR_ERROR:{e}")
'@
    
    $venvPython = Join-Path $backendDir 'venv\Scripts\python.exe'
    $pythonExe = if (Test-Path $venvPython) { $venvPython } else { 'python' }

    $resultText = ''
    try {
        $ErrorActionPreference = 'Continue'
        $result = $pythonCmd | & $pythonExe - 2>&1
    } catch {
        Write-Warn "Python 命令执行失败：$_"
        return $false
    } finally {
        $ErrorActionPreference = 'Stop'
    }

    $resultText = $result -join "`n"
    if ($resultText -match "CLEAR_SUCCESS:(\d+)") {
        $count = $matches[1]
        Write-Success "内存缓存已清空 ($count 条记录)"
        return $true
    } elseif ($resultText -match "CLEAR_ERROR:(.+)") {
        Write-Warn "无法清空内存缓存：$($matches[1])"
        return $false
    } else {
        Write-Warn "无法清空内存缓存：$resultText"
        return $false
    }
}

Show-Banner

if ($RedisOnly -and $MemoryOnly) {
    Write-Err "不能同时指定 -RedisOnly 和 -MemoryOnly"
    exit 1
}

if (-not $RedisOnly -and -not $MemoryOnly -and $Confirm) {
    Write-Host ""
    Write-Warn "⚠️  这将清空所有缓存数据！"
    $answer = Read-Host "确定要继续吗？(y/N)"
    if ($answer -ne "y" -and $answer -ne "Y") {
        Write-Info "操作已取消"
        exit 0
    }
}

if (-not $RedisOnly -and -not $MemoryOnly) {
    $RedisOnly = $true
    $MemoryOnly = $true
}

Write-Sep
Write-Host "  开始清理缓存..." -ForegroundColor Cyan
Write-Sep

$redisSuccess = $false
$memorySuccess = $false

if ($RedisOnly) {
    Write-Host ""
    Write-Host "[1/2] Redis 缓存" -ForegroundColor Yellow
    $redisSuccess = Clear-Cache-Redis
}

if ($MemoryOnly) {
    Write-Host ""
    Write-Host "[2/2] 内存缓存" -ForegroundColor Yellow
    $memorySuccess = Clear-Cache-Memory
}

Write-Sep
Write-Host ""
Write-Host "  清理完成：" -ForegroundColor Cyan
Write-Sep
Write-Host "  - Redis: $(if ($redisSuccess) { '✅' } else { '❌' })"
Write-Host "  - 内存：$(if ($memorySuccess) { '✅' } else { '❌' })"
Write-Host ""

if ($redisSuccess -or $memorySuccess) {
    Write-Success "缓存清理成功"
    exit 0
} else {
    Write-Err "缓存清理失败"
    exit 1
}