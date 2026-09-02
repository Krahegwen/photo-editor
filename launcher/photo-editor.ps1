# Arranca el motor de photo-editor (si no esta) y abre la UI en Brave.
# ASCII puro a proposito: PowerShell 5.1 lee los .ps1 sin BOM como ANSI y
# cualquier caracter fuera de ASCII rompe el parser sin mensaje visible.
# -SoloMotor: arranca el motor si no esta y no abre el navegador (lo usa la
# tarea programada photo-editor-engine).
param([switch]$SoloMotor)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$py = Join-Path $repo 'engine\.venv\Scripts\python.exe'
$port = if ($env:PHOTOED_PORT) { $env:PHOTOED_PORT } else { 8177 }
$url = "http://127.0.0.1:$port/"

function Show-Error($text) {
  Add-Type -AssemblyName System.Windows.Forms
  [void][System.Windows.Forms.MessageBox]::Show($text, 'photo-editor', 'OK', 'Error')
}

try {
  if (-not (Test-Path $py)) {
    throw "No existe engine\.venv. Ejecuta launcher\setup.ps1 (o 'python -m uv sync' en engine\)."
  }

  $up = $false
  try { Invoke-RestMethod "${url}api/health" -TimeoutSec 2 | Out-Null; $up = $true } catch {}
  if (-not $up) {
    $proc = Start-Process -FilePath $py -ArgumentList '-m', 'photoeditor' -WorkingDirectory $repo -WindowStyle Hidden -PassThru
    $appdir = Join-Path $env:LOCALAPPDATA 'photo-editor'
    New-Item -ItemType Directory -Force $appdir | Out-Null
    $proc.Id | Set-Content (Join-Path $appdir 'engine.pid')
    foreach ($i in 1..60) {
      Start-Sleep -Milliseconds 500
      try { Invoke-RestMethod "${url}api/health" -TimeoutSec 2 | Out-Null; $up = $true; break } catch {}
    }
    if (-not $up) { throw "El motor no responde en $url tras 30 s." }
  }

  if ($SoloMotor) { exit 0 }

  # Brave en ventana de aplicacion; si no esta, el navegador predeterminado.
  $brave = @(
    "$env:ProgramFiles\BraveSoftware\Brave-Browser\Application\brave.exe",
    "${env:ProgramFiles(x86)}\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($brave) { Start-Process -FilePath $brave -ArgumentList "--app=$url" }
  else { Start-Process $url }
} catch {
  Show-Error $_.Exception.Message
  exit 1
}
