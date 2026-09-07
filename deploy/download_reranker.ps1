# ============================================
# 智旅云图 - Rerank 模型本地下载脚本（Windows）
# ============================================
# 功能：把 BAAI/bge-reranker-v2-m3 下载为 HF 标准缓存目录，供服务器容器离线加载。
# 用法（在项目根目录执行，或直接运行 download_reranker.cmd）:
#   powershell -ExecutionPolicy Bypass -File .\deploy\download_reranker.ps1
# 产物：backend\models\hf_cache\hub\models--BAAI--bge-reranker-v2-m3\snapshots\...
# 后续：把 backend\models\hf_cache 上传到服务器 /www/wwwroot/zhilv/backend/models/
#       （docker-compose.prod.yaml 已配置 HF_HOME=/app/models/hf_cache + 离线模式）

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TargetCache = Join-Path $Root "backend\models\hf_cache"
$SnapshotCheck = Join-Path $TargetCache "hub\models--BAAI--bge-reranker-v2-m3\snapshots"

if (Test-Path $SnapshotCheck) {
    Write-Host "模型已存在，无需重新下载：$SnapshotCheck" -ForegroundColor Green
    exit 0
}

# [1/4] 定位 Python
Write-Host "[1/4] 检查 Python..." -ForegroundColor Cyan
$py = $null
foreach ($candidate in @("py", "python")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $py = $candidate; break }
}
if (-not $py) {
    Write-Error "未找到 Python，请先安装 Python 3.9+（安装时勾选 Add to PATH）。"
}

# [2/4] 临时虚拟环境（只装 huggingface_hub，无需 torch）
Write-Host "[2/4] 创建临时 Python 环境..." -ForegroundColor Cyan
$VenvDir = Join-Path $env:TEMP "zhilv-hf-download-venv"
if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
& $py -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { Write-Error "创建虚拟环境失败，请检查 Python 是否可用（$py -m venv）。" }
$PythonExe = [string](Join-Path $VenvDir "Scripts\python.exe")
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Error "虚拟环境创建异常：未找到 $PythonExe"
}

Write-Host "  Python: $PythonExe" -ForegroundColor Gray
& $PythonExe -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    & $PythonExe -m pip install --upgrade pip --quiet -i https://pypi.tuna.tsinghua.edu.cn/simple
}
if ($LASTEXITCODE -ne 0) { Write-Error "pip 升级失败，请检查网络后重试。" }
& $PythonExe -m pip install huggingface_hub --quiet
if ($LASTEXITCODE -ne 0) {
    & $PythonExe -m pip install huggingface_hub --quiet -i https://pypi.tuna.tsinghua.edu.cn/simple
}
if ($LASTEXITCODE -ne 0) { Write-Error "huggingface_hub 安装失败，请检查网络后重试（可先用 pip 测试联网）。" }

# [3/4] 下载模型（约 2.3GB）：优先国内镜像，失败再直连 HuggingFace
Write-Host "[3/4] 下载 BAAI/bge-reranker-v2-m3（约 2.3GB，请耐心等待）..." -ForegroundColor Cyan
$PyScript = "from huggingface_hub import snapshot_download`nsnapshot_download('BAAI/bge-reranker-v2-m3')"
$ScriptPath = Join-Path $VenvDir "download_model.py"
[System.IO.File]::WriteAllText($ScriptPath, $PyScript, (New-Object System.Text.UTF8Encoding($false)))

$env:HF_ENDPOINT = "https://hf-mirror.com"
& $PythonExe $ScriptPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "hf-mirror 下载失败，尝试直连 HuggingFace..." -ForegroundColor Yellow
    Remove-Item Env:HF_ENDPOINT
    & $PythonExe $ScriptPath
}
if ($LASTEXITCODE -ne 0) { Write-Error "模型下载失败，请检查网络后重试。" }

# [4/4] 复制到项目 backend\models\hf_cache
Write-Host "[4/4] 复制缓存到 $TargetCache ..." -ForegroundColor Cyan
$HubSrc = Join-Path $env:USERPROFILE ".cache\huggingface"
if (-not (Test-Path $HubSrc)) { Write-Error "未找到 HF 缓存目录：$HubSrc" }
New-Item -ItemType Directory -Path $TargetCache -Force | Out-Null
Copy-Item -Path (Join-Path $HubSrc "*") -Destination $TargetCache -Recurse -Force

# 清理临时环境与镜像变量
Remove-Item $VenvDir -Recurse -Force
Remove-Item Env:HF_ENDPOINT

if (Test-Path $SnapshotCheck) {
    $SizeMB = [Math]::Round((Get-ChildItem $TargetCache -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host ""
    Write-Host "完成！模型已就绪（${SizeMB} MB）：" -ForegroundColor Green
    Write-Host "  $TargetCache" -ForegroundColor Yellow
    Write-Host "下一步：把 backend\models\hf_cache 上传到服务器 /www/wwwroot/zhilv/backend/models/，然后执行 docker compose -f docker-compose.prod.yaml restart backend" -ForegroundColor Cyan
} else {
    Write-Error "缓存结构异常，请手动检查 $TargetCache"
}