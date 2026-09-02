# Instala/actualiza photo-editor: motor Python (uv) y UI (pnpm via corepack).
#   launcher\setup.ps1          -> solo CPU
#   launcher\setup.ps1 -Gpu     -> ademas CuPy + librerias CUDA (NVIDIA)
# ASCII puro a proposito (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
param([switch]$Gpu)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent

# uv puede estar en el PATH o solo como modulo de Python (python -m uv)
if (Get-Command uv -ErrorAction SilentlyContinue) { $uv = @('uv') }
elseif (& python -m uv --version 2>$null) { $uv = @('python', '-m', 'uv') }
else { throw "No encuentro uv. Instalalo: pip install uv  (o https://docs.astral.sh/uv/)" }

$args = @('sync')
if ($Gpu) { $args += @('--extra', 'gpu') }
Write-Host "== motor: $($uv -join ' ') $($args -join ' ')  (en engine\)"
& $uv[0] @($uv[1..($uv.Count-1)] + $args) --directory (Join-Path $repo 'engine')
if ($LASTEXITCODE -ne 0) { throw "uv sync fallo ($LASTEXITCODE)" }

Write-Host "== UI: corepack pnpm install + build  (en app\)"
$env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
Push-Location (Join-Path $repo 'app')
try {
  & corepack pnpm install
  if ($LASTEXITCODE -ne 0) { throw "pnpm install fallo" }
  & corepack pnpm build
  if ($LASTEXITCODE -ne 0) { throw "pnpm build fallo" }
} finally { Pop-Location }

Write-Host "== listo. Arranca con launcher\photo-editor.ps1 (o el acceso directo del escritorio)."
