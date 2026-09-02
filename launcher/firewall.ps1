# Abre el puerto del motor en el cortafuegos de Windows para usar la app desde
# el movil en la red local. Se eleva solo (pide UAC). Regla de entrada TCP.
# ASCII puro a proposito (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
param([int]$Port = 8177)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Port $Port"
  exit
}
$name = "photo-editor $Port"
netsh advfirewall firewall delete rule name="$name" | Out-Null
netsh advfirewall firewall add rule name="$name" dir=in action=allow protocol=TCP localport=$Port profile=private,public
Write-Host ""
Write-Host "Regla '$name' creada: el movil ya puede entrar por el puerto $Port en la misma red."
Write-Host "Pulsa Enter para cerrar."
Read-Host | Out-Null
