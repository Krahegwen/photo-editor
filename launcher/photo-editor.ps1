# Arranca el motor de photo-editor (sirviendo app/dist) y abre el navegador.
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$py = Join-Path $repo 'engine\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "No existe engine\.venv — ejecuta 'uv sync' en engine\" }
$port = if ($env:PHOTOED_PORT) { $env:PHOTOED_PORT } else { 8177 }

$up = $false
try { Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 2 | Out-Null; $up = $true } catch {}
if (-not $up) {
  Start-Process -FilePath $py -ArgumentList '-m', 'photoeditor' -WorkingDirectory $repo -WindowStyle Hidden
  foreach ($i in 1..30) {
    Start-Sleep -Milliseconds 500
    try { Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 2 | Out-Null; break } catch {}
  }
}
Start-Process "http://127.0.0.1:$port/"
