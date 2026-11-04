param([Parameter(Mandatory=$true)][string]$PairingFile)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Pair = Get-Content -Raw -LiteralPath $PairingFile | ConvertFrom-Json
if ($Pair.protocol -ne 1) { throw 'Unsupported pairing protocol' }
$Address = [System.Net.IPAddress]::Parse($Pair.linux_address).ToString()
$Admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $Admin) { throw 'Run this firewall helper in an Administrator PowerShell on the same Windows account' }
$Rules = @(@{ Name='LanBridge-TLS'; Protocol='TCP' }, @{ Name='LanBridge-Input'; Protocol='UDP' })
foreach ($Rule in $Rules) {
  Get-NetFirewallRule -Name $Rule.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  New-NetFirewallRule -Name $Rule.Name -DisplayName $Rule.Name -Direction Inbound -Action Allow `
    -Protocol $Rule.Protocol -LocalPort 4242 -Profile Private -RemoteAddress $Address | Out-Null
}
Write-Host 'Allowed TCP/UDP 4242 only from the paired Linux IP on Private networks.'
Write-Host 'Check the active home network is Private; no router port-forwarding is needed.'
