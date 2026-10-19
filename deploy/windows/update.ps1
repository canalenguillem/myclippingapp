<# Actualiza la app: trae el código nuevo, reconstruye y reinicia (las migraciones de la BD se aplican solas al arrancar). #>
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root
& (Join-Path $PSScriptRoot "backup.ps1")          # copia de la BD antes de tocar nada
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "git pull falló (¿cambios locales o sin conexión?). No se ha tocado nada más." }
docker compose up -d --build
docker image prune -f | Out-Null
docker compose ps
