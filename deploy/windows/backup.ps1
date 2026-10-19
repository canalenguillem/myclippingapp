<# Copia de seguridad de la base de datos en .\backups (mantiene las 14 últimas). Los vídeos viven en MEDIA_HOST_DIR: cópialos aparte si los quieres. #>
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root
$dir = Join-Path $root "backups"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$file = Join-Path $dir ("clipping_{0}.sql" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
docker compose exec -T mariadb sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction --routines clipping' | Out-File -Encoding utf8 $file
if ($LASTEXITCODE -ne 0 -or (Get-Item $file).Length -lt 1000) { Remove-Item $file -ErrorAction SilentlyContinue; throw "La copia de la base de datos falló (¿está arrancada la app?)." }
Get-ChildItem $dir -Filter "clipping_*.sql" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14 | Remove-Item
Write-Host "Copia guardada: $file" -ForegroundColor Green
