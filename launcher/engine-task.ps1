# Registra la tarea programada "photo-editor-engine", que arranca el motor
# fuera de cualquier sesion (sobrevive a cerrar Claude, terminales, etc.).
#   launcher\engine-task.ps1                 -> crea/actualiza la tarea y arranca el motor
#   launcher\engine-task.ps1 -AlIniciarSesion -> ademas, que arranque al iniciar sesion
#   launcher\engine-task.ps1 -Quitar          -> elimina la tarea
# La tarea llama a photo-editor.ps1 -SoloMotor (python oculto + espera de salud).
# ASCII puro a proposito (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
param([switch]$AlIniciarSesion, [switch]$Quitar)
$ErrorActionPreference = 'Stop'
$nombre = 'photo-editor-engine'
if ($Quitar) {
  schtasks /Delete /TN $nombre /F | Out-Null
  Write-Host "Tarea $nombre eliminada."
  exit 0
}
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$launcher = Join-Path $PSScriptRoot 'photo-editor.ps1'
$tr = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" -SoloMotor"
$sc = if ($AlIniciarSesion) { @('/SC', 'ONLOGON') } else { @('/SC', 'ONCE', '/ST', '00:00') }
$out = & schtasks /Create /TN $nombre /TR $tr @sc /F 2>&1
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear la tarea: $out" }
& schtasks /Run /TN $nombre | Out-Null
$up = $false
foreach ($i in 1..60) {
  Start-Sleep -Milliseconds 500
  try { Invoke-RestMethod 'http://127.0.0.1:8177/api/health' -TimeoutSec 2 | Out-Null; $up = $true; break } catch {}
}
if ($up) { Write-Host "Motor arrancado por la tarea $nombre." } else { Write-Host "La tarea existe pero el motor no responde en 8177." }
