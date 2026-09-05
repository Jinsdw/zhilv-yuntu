# ============================================
# 智旅云图 - 服务器部署打包脚本（Windows 开发机运行）
# ============================================
# 功能：把需要部署的内容打包成 zip（自动排除 node_modules / .git / venv / 日志 /
#       本地 .env 等敏感与无关内容），上传到服务器解压即可。
# 用法：在项目根目录执行：
#       powershell -ExecutionPolicy Bypass -File .\deploy\package.ps1
# 产物：deploy/zhilv-yuntu-<时间戳>.zip

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $Root "deploy"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ZipPath = Join-Path $OutputDir "zhilv-yuntu-$Stamp.zip"

# 打包用临时目录
$Stage = Join-Path $env:TEMP "zhilv-yuntu-package"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }

Write-Host "[1/3] 复制项目文件（排除无关目录）..." -ForegroundColor Cyan
# /E 包含空目录；/XD 排除目录（按名称任意层级匹配）；/XF 排除文件
robocopy $Root $Stage /E `
    /XD node_modules .git .venv venv __pycache__ .pytest_cache .cursor .opensquilla logs dist `
    /XF .env test_del.txt *.pyc *.pyo *.zip

if ($LASTEXITCODE -ge 8) {
    Write-Error "robocopy 复制失败（退出码 $LASTEXITCODE）"
}
$LASTEXITCODE = 0

Write-Host "[2/3] 压缩为 $ZipPath ..." -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "[3/3] 清理临时目录..." -ForegroundColor Cyan
Remove-Item $Stage -Recurse -Force

$SizeMB = [Math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host ""
Write-Host "打包完成：" -ForegroundColor Green
Write-Host "  文件：$ZipPath" -ForegroundColor Yellow
Write-Host "  大小：$SizeMB MB" -ForegroundColor Yellow
Write-Host ""
Write-Host "下一步：上传到服务器 /www/wwwroot/zhilv 并解压，然后按 deploy/DEPLOY.md 操作。" -ForegroundColor Green
