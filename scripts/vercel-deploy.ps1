param()
$ErrorActionPreference = "SilentlyContinue"

$ALIAS = "sindicompany-dashboards.vercel.app"
$NODE  = "C:\Program Files\nodejs\node.exe"
$VCLI  = "C:\Users\MF PRINTER\AppData\Roaming\npm\node_modules\vercel\dist\vc.js"

$env:PATH = "C:\Users\MF PRINTER\AppData\Roaming\npm;C:\Program Files\nodejs;C:\Windows\System32;$env:PATH"

$ROOT  = Split-Path -Parent $PSScriptRoot
$ADMIN = Join-Path $ROOT "admin"
$LOG   = Join-Path $ROOT "data\logs\vercel-deploy.log"

$AUTH_FILE = "$env:APPDATA\xdg.data\com.vercel.cli\auth.json"
if (-not (Test-Path $AUTH_FILE)) { Write-Host "auth.json nao encontrado — rodar: vercel login"; exit 1 }
$authData = Get-Content $AUTH_FILE -Raw | ConvertFrom-Json
$TOKEN = $authData.token
if (-not $TOKEN) { Write-Host "Token nao encontrado — rodar: vercel login"; exit 1 }

$logDir = Split-Path $LOG
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

function L($m) {
    $t = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    ("$t  $m") | Out-File -Append -FilePath $LOG -Encoding utf8
    Write-Host "$t  $m"
}

L "Deploy iniciado"

# 1. Gera snapshots localmente
Set-Location $ADMIN
L "Gerando snapshots..."
$s = & $NODE scripts/generate-snapshots.mjs 2>&1
L ($s -join " ")

# 2. Deploy da RAIZ do projeto (Vercel tem rootDirectory=admin configurado)
Set-Location $ROOT
$env:VERCEL_ORG_ID     = "team_ZcZYzyZxy59xsCSB41wUYrpv"
$env:VERCEL_PROJECT_ID = "prj_W66oRPPeGYSpkGWdwIA3IQrMlJo7"

L "Fazendo deploy..."
$out  = & $NODE $VCLI deploy --prod --yes --token=$TOKEN 2>&1
$code = $LASTEXITCODE

$url = $null
foreach ($line in $out) {
    if ($line -match '"url"\s*:\s*"(https://[^"]+)"') { $url = $Matches[1] }
}
if (-not $url) {
    $url = ($out | Where-Object { $_ -match "Aliased\s+https://" } | Select-Object -Last 1) -replace '.*Aliased\s+',''
}

if ($code -ne 0) {
    L ("ERRO deploy (exit " + $code + ")")
    $out | ForEach-Object { L ("  " + $_) }
    exit 1
}

L ("Deploy OK: " + $url)
L ("Concluido: https://" + $ALIAS)
