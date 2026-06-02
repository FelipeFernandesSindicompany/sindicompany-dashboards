param()
$ErrorActionPreference = "SilentlyContinue"

$TOKEN     = "vca_1983vyzyT3nMOoH00LXVbdSw8VtVVdQTEz9WDhc9HYMp5HsKsT06RwA0"
$ALIAS     = "sindicompany-dashboards.vercel.app"
$NODE      = "C:\Program Files\nodejs\node.exe"
$VCLI      = "C:\Users\MF PRINTER\AppData\Roaming\npm\node_modules\vercel\dist\vc.js"
$env:PATH  = "C:\Users\MF PRINTER\AppData\Roaming\npm;C:\Program Files\nodejs;$env:PATH"

$ROOT      = Split-Path -Parent $PSScriptRoot
$ADMIN     = Join-Path $ROOT "admin"
$LOG       = Join-Path $ROOT "data\logs\vercel-deploy.log"

$logDir = Split-Path $LOG
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

function L($m) {
    $t = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    ("$t  $m") | Out-File -Append -FilePath $LOG -Encoding utf8
    Write-Host "$t  $m"
}

L "Deploy iniciado"

# 1. Gera snapshots
Set-Location $ADMIN
L "Gerando snapshots..."
$s = & $NODE scripts/generate-snapshots.mjs 2>&1
L ($s -join " ")

# 2. Deploy do diretorio admin/
Remove-Item Env:VERCEL_ORG_ID     -ErrorAction SilentlyContinue
Remove-Item Env:VERCEL_PROJECT_ID  -ErrorAction SilentlyContinue

L "Fazendo deploy..."
$out  = & $NODE $VCLI deploy --prod --token=$TOKEN --yes 2>&1
$code = $LASTEXITCODE
$out | ForEach-Object { L ("  > " + $_) }

if ($code -ne 0) {
    L "ERRO deploy (exit $code) - rodar: vercel login"
    exit 1
}

# Tenta extrair URL do deploy (dois formatos possiveis)
# Formato novo (JSON): "url": "https://..."
# Formato antigo: linha comecando com https://
$url = $null
$jsonText = ($out | Where-Object { $_ -match '"url"' } | Select-Object -First 1)
if ($jsonText -match '"url"\s*:\s*"(https://[^"]+)"') {
    $url = $Matches[1]
}
if (-not $url) {
    $url = ($out | Where-Object { $_ -match "^https://sindicompany" } | Select-Object -Last 1)
}

if (-not $url) {
    L "Deploy OK mas URL nao extraida - alias manual necessario"
    exit 0
}

L ("Deploy OK: " + $url)

# Promove alias de producao
$host2 = $url -replace "^https://", ""
L ("Promovendo " + $host2 + " -> " + $ALIAS)
$aOut = & $NODE $VCLI alias set $host2 $ALIAS --token=$TOKEN --yes 2>&1
L ($aOut -join " ")

L ("Concluido: https://" + $ALIAS)
