param(
  [Parameter(Mandatory=$true)][string]$PairingFile,
  [switch]$BuildEngine,
  [switch]$ConfigureFirewall
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PairingFile = (Resolve-Path -LiteralPath $PairingFile).Path
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$PythonW = Join-Path $Venv 'Scripts\pythonw.exe'

function Run-Native([scriptblock]$Action) {
  & $Action
  if ($LASTEXITCODE -ne 0) { throw "Native command failed with exit $LASTEXITCODE" }
}

if (-not (Test-Path -LiteralPath $Python)) {
  Run-Native { py -3 -m venv $Venv }
}
Run-Native { & $Python -m pip install -r (Join-Path $Root 'requirements-windows.txt') }
if ($BuildEngine) { Run-Native { & $Python (Join-Path $PSScriptRoot 'build-engine.py') } }
Run-Native { & $Python (Join-Path $PSScriptRoot 'configure-windows.py') --pairing $PairingFile }
Run-Native { & $Python (Join-Path $Root 'lan-bridge.py') doctor }

$Private = Join-Path $env:LOCALAPPDATA 'LanBridge'
$Account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
# Keep pairing, queues and local state readable only by this account and SYSTEM.
Run-Native { icacls $Private /inheritance:r /grant:r "${Account}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' /T /Q }

if ($ConfigureFirewall) {
  & (Join-Path $PSScriptRoot 'configure-firewall.ps1') -PairingFile $PairingFile
}

# Gracefully stop a previous companion before replacing its scheduled action.
$Stop = Join-Path $Private 'state\stop.request'
New-Item -ItemType Directory -Force (Split-Path -Parent $Stop) | Out-Null
New-Item -ItemType File -Force $Stop | Out-Null
Start-Sleep -Seconds 2
$Existing = Get-ScheduledTask -TaskName 'Lan Bridge' -ErrorAction SilentlyContinue
if ($Existing) { Stop-ScheduledTask -TaskName 'Lan Bridge' }
Get-Process -Name 'lan-mouse' -ErrorAction SilentlyContinue | Stop-Process
Remove-Item -LiteralPath $Stop -ErrorAction SilentlyContinue

$Arguments = '"' + (Join-Path $Root 'lan-bridge.py') + '" windows-agent'
$Action = New-ScheduledTaskAction -Execute $PythonW -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Account
$Principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Seconds 10) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Lan Bridge' -Action $Action -Trigger $Trigger -Principal $Principal `
  -Settings $Settings -Description 'Integrated Lan Mouse, clipboard, files, sync and two remote displays' -Force | Out-Null

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Lan Bridge.lnk'))
$Shortcut.TargetPath = $PythonW
$Shortcut.Arguments = '"' + (Join-Path $Root 'lan-bridge.py') + '" panel'
$Shortcut.WorkingDirectory = $Root
$Shortcut.Save()
Start-ScheduledTask -TaskName 'Lan Bridge'
Write-Host 'Windows companion installed and started. Open Lan Bridge from Start for files and settings.'
Write-Host 'Disable any old independent Lan Mouse startup entries; the companion now owns its input engine.'
Write-Host 'If not configured yet, run configure-firewall.ps1 as Administrator with the same PairingFile.'
Write-Host 'Next, perform every check in docs/ACCEPTANCE.md; native Windows behavior is not validated by installation alone.'
