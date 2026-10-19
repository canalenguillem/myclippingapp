<#
.SYNOPSIS
  Instala ClippingVideos en Windows 11 con Docker Desktop: elige un puerto libre, genera los secretos, crea .env y levanta todo.

.DESCRIPTION
  Ejecútalo desde PowerShell en la carpeta del proyecto (p. ej. D:\ClippingVideos):
      powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1
  Parámetros opcionales:
      -Port 8090              puerto del frontend (por defecto, el primer libre desde 8090)
      -PublicUrl https://clipp.enguillem.es   URL pública (por defecto http://<IP de la LAN>:<puerto>)
      -MediaDir D:\ClippingVideos\media       dónde se guardan los vídeos (por defecto, ./media)
  No sobrescribe un .env existente.
#>
param(
  [int]$Port = 0,
  [string]$PublicUrl = "",
  [string]$MediaDir = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root
Write-Host "Proyecto en $root" -ForegroundColor Cyan

# --- 1. Requisitos ------------------------------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "No encuentro Docker. Instala Docker Desktop (con WSL 2) y vuelve a ejecutar este script." }
try { docker info *> $null; if ($LASTEXITCODE -ne 0) { throw } } catch { throw "Docker está instalado pero no responde: abre Docker Desktop, espera a que diga 'Engine running' y repite." }
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { throw "Falta 'docker compose' (viene con Docker Desktop reciente)." }
$drive = (Get-Item $root).PSDrive
if ($drive.Free -lt 15GB) { Write-Warning ("Quedan solo {0:N1} GB libres en {1}: las imágenes de Docker y los vídeos necesitan bastante (recomendado > 30 GB)." -f ($drive.Free / 1GB), $drive.Name + ":") }

# --- 2. Puerto libre ---------------------------------------------------------------------------
function Test-PortFree([int]$p) {
  $busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($busy) { return $false }
  try { $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $p); $l.Start(); $l.Stop(); return $true } catch { return $false }
}
if ($Port -eq 0) {
  $Port = (8090..8199 | Where-Object { Test-PortFree $_ } | Select-Object -First 1)
  if (-not $Port) { throw "No hay ningún puerto libre entre 8090 y 8199: indica uno con -Port." }
} elseif (-not (Test-PortFree $Port)) { throw "El puerto $Port ya está en uso. Elige otro con -Port." }
Write-Host "Puerto del frontend: $Port" -ForegroundColor Green

# --- 3. .env -----------------------------------------------------------------------------------
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  Write-Host ".env ya existe: no lo toco. (Cambia FRONTEND_PORT / PUBLIC_BASE_URL a mano si hace falta.)" -ForegroundColor Yellow
} else {
  function New-Secret([int]$bytes) { $b = New-Object byte[] $bytes; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); return ([Convert]::ToBase64String($b)).Replace('+', '-').Replace('/', '_') }
  function New-Password { return ((New-Secret 18).Replace('=', '').Replace('-', 'x').Replace('_', 'y')) }
  function Read-Optional([string]$prompt) {
    $s = Read-Host -AsSecureString $prompt
    $p = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
    return $p
  }
  if (-not $PublicUrl) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" -or $_.IPAddress -like "172.16.*" } | Select-Object -First 1).IPAddress
    if (-not $ip) { $ip = "localhost" }
    $PublicUrl = "http://${ip}:$Port"
  }
  $mediaForDocker = ""
  if ($MediaDir) { New-Item -ItemType Directory -Force -Path $MediaDir | Out-Null; $mediaForDocker = ($MediaDir -replace '\\', '/') }
  $rootPw = New-Password; $dbPw = New-Password
  Write-Host "Claves de API (se guardan solo en .env; Intro para dejarlas vacías y ponerlas luego):" -ForegroundColor Cyan
  $openai = Read-Optional "OPENAI_API_KEY"
  $aai = Read-Optional "AAI_API_KEY (AssemblyAI)"
  $lines = @(
    "# Generado por deploy/windows/install.ps1. NO lo subas a git.",
    "MARIADB_ROOT_PASSWORD=$rootPw",
    "MARIADB_DATABASE=clipping",
    "MARIADB_USER=clipping",
    "MARIADB_PASSWORD=$dbPw",
    "DATABASE_URL=mysql+pymysql://clipping:$dbPw@mariadb:3306/clipping?charset=utf8mb4",
    "JWT_SECRET=$(New-Secret 48)",
    "APP_ENCRYPTION_KEY=$(New-Secret 32)",
    "ALLOW_REGISTRATION=true",
    "PUBLIC_BASE_URL=$PublicUrl",
    "OPENAI_API_KEY=$openai",
    "OPENAI_CLIP_MODEL=gpt-4o",
    "AAI_API_KEY=$aai",
    "WORKER_CONCURRENCY=2",
    "FX_WORKER_URL=http://fx_worker:3000",
    "MEDIA_DIR=/media",
    "FRONTEND_PORT=$Port",
    "MEDIA_HOST_DIR=$mediaForDocker"
  )
  [IO.File]::WriteAllText($envFile, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
  Write-Host ".env creado con secretos nuevos (PUBLIC_BASE_URL=$PublicUrl)." -ForegroundColor Green
}

# --- 4. Cortafuegos de Windows: abrir el puerto solo a la red local ----------------------------
$rule = "ClippingVideos $Port"
if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
  try { New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Action Allow | Out-Null; Write-Host "Regla de cortafuegos creada para la red local (puerto $Port)." -ForegroundColor Green }
  catch { Write-Warning "No pude crear la regla del cortafuegos (¿PowerShell sin permisos de administrador?). Si desde otro equipo no se ve, ábrelo a mano." }
}

# --- 5. Construir y levantar -------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path (Join-Path $root "media") | Out-Null
Write-Host "Construyendo y arrancando (la primera vez tarda 10-20 min: descarga imágenes y compila)..." -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw "docker compose falló. Mira el mensaje de arriba." }

# --- 6. Esperar a que responda -----------------------------------------------------------------
$port = ((Get-Content $envFile | Where-Object { $_ -like "FRONTEND_PORT=*" }) -replace "FRONTEND_PORT=", "")
if (-not $port) { $port = $Port }
$ok = $false
foreach ($i in 1..60) {
  try { $r = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$port/api/health" -TimeoutSec 3; if ($r.StatusCode -eq 200) { $ok = $true; break } } catch { }
  Start-Sleep -Seconds 3
}
if ($ok) { Write-Host "`nListo: http://localhost:$port  (y desde la red: $((Get-Content $envFile | Where-Object { $_ -like 'PUBLIC_BASE_URL=*' }) -replace 'PUBLIC_BASE_URL=', ''))" -ForegroundColor Green }
else { Write-Warning "No responde todavía. Mira los logs: docker compose logs --tail 50 backend" }
Write-Host @"

Siguientes pasos:
  1. Abre la URL y regístrate: el PRIMER usuario es el administrador.
  2. Pon ALLOW_REGISTRATION=false en .env y ejecuta:  docker compose up -d backend   (para que nadie más se registre).
  3. Para publicar con https, apunta tu proxy a este equipo:$port y cambia PUBLIC_BASE_URL en .env a la URL https
     (con http las cookies de sesión seguras no funcionan en https y viceversa). Después:  docker compose up -d backend worker
"@
