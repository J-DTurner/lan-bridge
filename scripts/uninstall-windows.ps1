# Removes only Lan Bridge startup/firewall integration. Personal files and keys stay.
$ErrorActionPreference = 'Stop'
$Private = Join-Path $env:LOCALAPPDATA 'LanBridge'
New-Item -ItemType Directory -Force (Join-Path $Private 'state') | Out-Null
New-Item -ItemType File -Force (Join-Path $Private 'state\stop.request') | Out-Null
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName 'Lan Bridge' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
Get-NetFirewallRule -Name 'LanBridge-TLS','LanBridge-Input' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'Lan Bridge.lnk') -ErrorAction SilentlyContinue
Write-Host 'Lan Bridge integration removed. Restart the original Lan Mouse app to resume its prior input setup.'
