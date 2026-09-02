# Registra photo-editor como servidor MCP en Claude Desktop y vigila que la
# entrada sobreviva: Desktop reescribe claude_desktop_config.json con su copia
# en memoria al guardar preferencias y se lleva por delante lo que se anada
# con la app abierta. Este script repone la entrada cada 2 s durante
# -Minutos (por defecto 20): ejecutalo, cierra Claude Desktop del todo (icono
# de la bandeja > Salir) y vuelve a abrirlo; al arrancar leera la entrada.
# ASCII puro a proposito (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
param([int]$Minutos = 20)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$py = Join-Path $repo 'engine\.venv\Scripts\python.exe'
$cfg = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
if (-not (Test-Path $py)) { throw "No existe engine\.venv (ejecuta launcher\setup.ps1)" }

$snippet = @"
import json, sys
p = sys.argv[1]
cfg = json.load(open(p, encoding='utf-8'))
cfg.setdefault('mcpServers', {})['photo-editor'] = {
    'command': sys.argv[2],
    'args': ['-m', 'photoeditor.mcp_server'],
    'env': {'PHOTOED_URL': 'http://127.0.0.1:8177'},
}
json.dump(cfg, open(p, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
"@
$tmp = Join-Path $env:TEMP 'pe_mcp_register.py'
Set-Content -Path $tmp -Value $snippet -Encoding ASCII

$fin = (Get-Date).AddMinutes($Minutos)
$veces = 0
Write-Host "Vigilando $cfg durante $Minutos min. Cierra Claude Desktop del todo y vuelve a abrirlo."
while ((Get-Date) -lt $fin) {
  $ok = (Test-Path $cfg) -and ((Get-Content $cfg -Raw) -like '*"photo-editor"*')
  if (-not $ok) {
    & $py $tmp $cfg $py
    $veces++
    Write-Host ("{0}  entrada repuesta (x{1})" -f (Get-Date).ToString('HH:mm:ss'), $veces)
  }
  Start-Sleep -Seconds 2
}
Write-Host "Fin de la vigilancia. Entrada presente: $((Get-Content $cfg -Raw) -like '*""photo-editor""*')"
