# Copia los datos de photo-editor (catalogo, config, manifiesto de favoritas,
# cache, galerias) desde la copia VIRTUALIZADA que ve Claude Desktop (app MSIX:
# AppData\Local\Packages\<app>\LocalCache\Local) al directorio real del perfil.
# Debe correr FUERA del contenedor: se registra como tarea programada y se
# lanza con /Run. El log va a C:\Users\Public (visible desde ambos lados).
# ASCII puro (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
param([switch]$Ejecutar, [string]$Paquete = 'Claude_pzs8sxrjxfjjc')
$dst = Join-Path $env:USERPROFILE 'AppData\Local\photo-editor'
$src = Join-Path $env:USERPROFILE "AppData\Local\Packages\$Paquete\LocalCache\Local\photo-editor"
$log = 'C:\Users\Public\pe_migrate.log'
if ($Ejecutar) {
  "== $(Get-Date -Format 'HH:mm:ss') migracion $src -> $dst" | Out-File $log -Encoding ascii
  if (-not (Test-Path $src)) { "no existe $src" | Out-File $log -Append -Encoding ascii; exit 1 }
  New-Item -ItemType Directory -Force $dst | Out-Null
  Remove-Item (Join-Path $dst 'catalog.db-wal'), (Join-Path $dst 'catalog.db-shm') -ErrorAction SilentlyContinue
  robocopy $src $dst catalog.db config.json favs.json deletions.log /R:1 /W:1 /NJH /NJS /NDL /NP | Out-File $log -Append -Encoding ascii
  robocopy (Join-Path $src 'cache') (Join-Path $dst 'cache') /E /XO /R:1 /W:1 /NJH /NJS /NDL /NP /NFL | Out-File $log -Append -Encoding ascii
  robocopy (Join-Path $src 'galleries') (Join-Path $dst 'galleries') /E /XO /R:1 /W:1 /NJH /NJS /NDL /NP /NFL | Out-File $log -Append -Encoding ascii
  "config real: " + (Get-Content (Join-Path $dst 'config.json') -Raw) | Out-File $log -Append -Encoding ascii
  "== fin $(Get-Date -Format 'HH:mm:ss')" | Out-File $log -Append -Encoding ascii
  exit 0
}
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tr = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -Ejecutar -Paquete $Paquete"
$ErrorActionPreference = 'Continue'
& schtasks /Create /TN "photo-editor-migrate" /TR $tr /SC ONCE /ST 00:00 /F 2>$null | Out-Null
& schtasks /Run /TN "photo-editor-migrate" 2>$null | Out-Null
foreach ($i in 1..90) { Start-Sleep 1; if ((Test-Path $log) -and ((Get-Content $log -Raw) -like '*== fin*')) { break } }
& schtasks /Delete /TN "photo-editor-migrate" /F 2>$null | Out-Null
if (Test-Path $log) { Get-Content $log } else { Write-Host "la tarea no escribio el log ($log)" }
