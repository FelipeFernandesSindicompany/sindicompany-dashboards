param()
$ErrorActionPreference = "SilentlyContinue"

$ALIAS = "sindicompany-dashboards.vercel.app"
$NODE  = "C:\Program Files\nodejs\node.exe"
$VCLI  = "C:\Users\MF PRINTER\AppData\Roaming\npm\node_modules\vercel\dist\vc.js"

# PATH explícito para funcionar no contexto restrito do hook
$env:PATH = "C:\Users\MF PRINTER\AppData\Roaming\npm;C:\Program Files\nodejs;C:\Windows\System32;$env:PATH"

$ROOT  = Split-Path -Parent $PSScriptRoot
$ADMIN = Join-Path $ROOT "admin"
$LOG   = Join-Path $ROOT "data\logs\vercel-deploy.log"

# Le token diretamente do auth.json do CLI (sempre atualizado apos vercel login)
$AUTH_FILE = "$env:APPDATA\xdg.data\com.vercel.cli\auth.json"
if (-not (Test-Path $AUTH_FILE)) {
    Write-Host "auth.json nao encontrado — rodar: vercel login"
    exit 1
}
$authData = Get-Content $AUTH_FILE -Raw | ConvertFrom-Json
$TOKEN = $authData.token
if (-not $TOKEN) {
    Write-Host "Token nao encontrado — rodar: vercel login"
    exit 1
}

$logDir = Split-Path $LOG
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

function L($m) {
    $t = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    ("$t  $m") | Out-File -Append -FilePath $LOG -Encoding utf8
    Write-Host "$t  $m"
}

L "Deploy iniciado"

# 1. Gera snapshots localmente (tem acesso a docs/)
Set-Location $ADMIN
L "Gerando snapshots..."
$s = & $NODE scripts/generate-snapshots.mjs 2>&1
L ($s -join " ")

# 2. Vercel pull (baixa configurações do projeto)
L "Fazendo vercel pull..."
$VERCEL_PS1 = "C:\Users\MF PRINTER\AppData\Roaming\npm\vercel.ps1"
$pullOut = & powershell.exe -ExecutionPolicy Bypass -File $VERCEL_PS1 pull --yes --environment=production --token=$TOKEN 2>&1
L ($pullOut -join " ")

# 3. Build local (tem acesso a docs/ — snapshots corretos serão bundled)
L "Fazendo vercel build local..."
$buildOut = & powershell.exe -ExecutionPolicy Bypass -File $VERCEL_PS1 build --prod --token=$TOKEN 2>&1
$buildCode = $LASTEXITCODE
if ($buildCode -ne 0) {
    L ("ERRO no build (exit " + $buildCode + "): " + ($buildOut -join " "))
    exit 1
}
L "Build OK"

# 4. Deploy do artefato prebuilt (sem re-build remoto)
L "Fazendo deploy prebuilt..."
Remove-Item Env:VERCEL_ORG_ID     -ErrorAction SilentlyContinue
Remove-Item Env:VERCEL_PROJECT_ID  -ErrorAction SilentlyContinue

$out  = & powershell.exe -ExecutionPolicy Bypass -File $VERCEL_PS1 deploy --prebuilt --prod --token=$TOKEN 2>&1
$code = $LASTEXITCODE

# Extrai URL do JSON de resposta
$url = $null
foreach ($line in $out) {
    if ($line -match '"url"\s*:\s*"(https://[^"]+)"') {
        $url = $Matches[1]
    }
}
if (-not $url) {
    $url = ($out | Where-Object { $_ -match "^https://sindicompany" } | Select-Object -Last 1)
}

if ($code -ne 0) {
    L ("ERRO deploy (exit " + $code + ")")
    $out | ForEach-Object { L ("  " + $_) }
    exit 1
}

L ("Deploy OK: " + $url)

# 5. Promove alias
if ($url) {
    $host2 = $url -replace "^https://", ""
    L ("Promovendo " + $host2 + " -> " + $ALIAS)
    $aOut = & powershell.exe -ExecutionPolicy Bypass -File $VERCEL_PS1 alias set $host2 $ALIAS --yes 2>&1
    L ($aOut -join " ")
}

L ("Concluido: https://" + $ALIAS)
