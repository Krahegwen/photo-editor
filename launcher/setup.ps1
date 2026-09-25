# Instala/actualiza photo-editor: motor Python (uv) y UI (pnpm).
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

# pnpm, el del PATH: desde la 9.7 lee el packageManager de app\package.json y cambia solo a esa
# version. Uno anterior no cambia, y con el lockfile de la app fallaria a medias: mejor pararlo aqui.
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { throw "No encuentro pnpm. Instalalo: https://pnpm.io/installation" }
$app = Join-Path $repo 'app'
$want = (Get-Content (Join-Path $app 'package.json') -Raw | ConvertFrom-Json).packageManager -replace '^pnpm@' -replace '\+.*$'
Push-Location $app
try { $have = & pnpm -v | Select-Object -Last 1 } finally { Pop-Location }
if ($have -ne $want) { throw "En app\ pnpm da $have y el repo pide $want. Actualiza pnpm (pnpm self-update): desde la 9.7 cambia solo de version." }

$args = @('sync')
if ($Gpu) { $args += @('--extra', 'gpu') }
Write-Host "== motor: $($uv -join ' ') $($args -join ' ')  (en engine\)"
& $uv[0] @($uv[1..($uv.Count-1)] + $args) --directory (Join-Path $repo 'engine')
if ($LASTEXITCODE -ne 0) { throw "uv sync fallo ($LASTEXITCODE)" }

Write-Host "== UI: pnpm install + build  (en app\)"
Push-Location $app
try {
  & pnpm install
  if ($LASTEXITCODE -ne 0) { throw "pnpm install fallo" }
  & pnpm run build
  if ($LASTEXITCODE -ne 0) { throw "pnpm build fallo" }
} finally { Pop-Location }

Write-Host "== listo. Arranca con launcher\photo-editor.ps1 (o el acceso directo del escritorio)."
