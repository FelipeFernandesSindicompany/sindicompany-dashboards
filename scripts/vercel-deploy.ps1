# scripts/vercel-deploy.ps1
# Deploy automático para Vercel + promoção automática do alias de produção.
# Chamado pelo git pre-push hook após push para main.
# DEVE rodar da raiz do repositório (não de dentro de admin/).

$ErrorActionPreference = "SilentlyContinue"

$VERCEL_TOKEN = "vca_0ZQVXzv8hVxk3GrfnjCzPmM8CRdcNZ1WiqCMKJcDVSMyLmTXnd31ghE5"
$PROD_ALIAS   = "sindicompany-dashboards.vercel.app"

$REPO_ROOT = Split-Path -Parent $PSScriptRoot
$ADMIN_DIR = Join-Path $REPO_ROOT "admin"
$LOG_FILE  = Join-Path $REPO_ROOT "data\logs\vercel-deploy.log"

# Garante que o log dir existe
$logDir = Split-Path $LOG_FILE
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

function Log($msg) {
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$ts  $msg" | Out-File -Append -FilePath $LOG_FILE -Encoding utf8
    Write-Host "$ts  $msg"
}

Log "=== Deploy Vercel iniciado ==="

# 1. Gera snapshots com os dados mais recentes dos dashboards
Log "Gerando snapshots..."
Set-Location $ADMIN_DIR
$snapOut = node scripts/generate-snapshots.mjs 2>&1
Log ($snapOut -join " ")

# 2. Deploy da raiz do repositório (evita path duplication admin/admin)
Set-Location $REPO_ROOT
Log "Fazendo deploy (aguarde ~30s)..."

# Remove variáveis que causam duplicação de caminho
Remove-Item Env:VERCEL_ORG_ID     -ErrorAction SilentlyContinue
Remove-Item Env:VERCEL_PROJECT_ID  -ErrorAction SilentlyContinue

$deployOut = vercel deploy --prod --token=$VERCEL_TOKEN --yes 2>&1
$exitCode  = $LASTEXITCODE

# Extrai URL do deploy
$deployUrl = ($deployOut | Where-Object { $_ -match "^https://sindicompany-dashboards" } | Select-Object -Last 1)
$aliased   = ($deployOut | Where-Object { $_ -match "Aliased" }) -ne $null

if ($exitCode -ne 0 -or -not $deployUrl) {
    Log "ERRO no deploy (exit $exitCode):"
    $deployOut | ForEach-Object { Log "  $_" }
    exit 1
}

Log "Deploy OK: $deployUrl"

# O Vercel CLI promove o alias automaticamente com --prod
# mas garante explicitamente caso não tenha sido feito
if (-not $aliased) {
    $deployHost = $deployUrl -replace "^https://", ""
    Log "Promovendo alias $deployHost -> $PROD_ALIAS ..."
    vercel alias set $deployHost $PROD_ALIAS --token=$VERCEL_TOKEN --yes 2>&1 | Out-Null
}

Log "=== Concluído: https://$PROD_ALIAS ==="
