# Registers a Windows Scheduled Task that refreshes the proxy pool every day.
#
#   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1
#   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1 -At 04:30
#   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1 -Remove
#
param(
    [string]$At = "03:00",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "ProxyRotator Daily Refresh"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task: $taskName"
    exit 0
}

# Prefer the standard Windows launcher (py.exe); fall back to python.exe on PATH.
$pyLauncher = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if ($pyLauncher) {
    $exe = $pyLauncher
    $prefix = "-3 "
} elseif ($python) {
    $exe = $python
    $prefix = ""
} else {
    throw "Python not found. Install Python 3.11+ and retry."
}

$action = New-ScheduledTaskAction `
    -Execute $exe `
    -Argument ($prefix + "fetch_proxies.py --recheck-hours 24 --concurrency 1200 --timeout 5") `
    -WorkingDirectory $proj

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Downloads and validates free proxies daily, refreshing proxies.txt for Proxy Rotator." `
    -Force | Out-Null

Write-Host "Registered '$taskName' - runs daily at $At."
Write-Host "Run it now:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove it:   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1 -Remove"
