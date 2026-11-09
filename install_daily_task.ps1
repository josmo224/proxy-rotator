# Registers a Windows Scheduled Task that refreshes the proxy pool every hour.
#
#   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1
#   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1 -Remove
#
# Each run downloads fresh lists, adds new proxies, re-checks the live ones,
# and rebuilds proxies.txt with only high-quality (fast + repeatedly proven)
# proxies.
param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "ProxyRotator Hourly Refresh"
$oldName = "ProxyRotator Daily Refresh"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $oldName -Confirm:$false -ErrorAction SilentlyContinue
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
    -Argument ($prefix + "fetch_proxies.py --hourly --recheck-hours 1 --concurrency 400 --timeout 6") `
    -WorkingDirectory $proj

$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Unregister-ScheduledTask -TaskName $oldName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Refreshes the free proxy pool hourly, keeping only fast, repeatedly proven proxies." `
    -Force | Out-Null

Write-Host "Registered '$taskName' - runs every hour."
Write-Host "Run it now:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove it:   powershell -ExecutionPolicy Bypass -File install_daily_task.ps1 -Remove"
