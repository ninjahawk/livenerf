# Register, remove or inspect the hourly livenerf task on Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 install
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 status
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 disable
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 uninstall
#
# The task runs at minute 7 of every hour while you are logged on (it needs the Claude Code login),
# hidden (conhost --headless, so no console window flashes), never more than one at a time, and it
# does not catch up on hours missed while the PC was off or asleep. It is a clock trigger, not a
# logon trigger: nothing starts at boot. Output goes to logs\hourly.log and logs\hourly.jsonl.

param(
    [Parameter(Position = 0)][ValidateSet("install", "status", "disable", "enable", "uninstall")][string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$Name = "livenerf hourly"
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"

switch ($Command) {
    "install" {
        if (-not (Test-Path $Python)) { throw "No venv at $Python. Run 'uv sync' in $Repo first." }
        New-Item -ItemType Directory -Force (Join-Path $Repo "logs") | Out-Null
        $inner = "`"$Python`" -m livenerf.hourly >> logs\hourly.log 2>&1"
        $action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd.exe /c $inner" -WorkingDirectory $Repo
        $start = (Get-Date).Date.AddHours((Get-Date).Hour + 1).AddMinutes(7)
        $trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 1)
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 55) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $settings.StartWhenAvailable = $false
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
            -Description "livenerf: one hourly benchmark batch against Claude Opus 5.5 ($Repo)" -Force | Out-Null
        Write-Output "Registered '$Name': one batch at minute 7 of every hour (rates in data\standard_panel.json), first run $start."
    }
    "status" {
        $t = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if (-not $t) { Write-Output "'$Name' is not registered."; break }
        $i = Get-ScheduledTaskInfo -TaskName $Name
        Write-Output "state: $($t.State)  last run: $($i.LastRunTime)  last result: $($i.LastTaskResult)  next run: $($i.NextRunTime)"
    }
    "disable" { Disable-ScheduledTask -TaskName $Name | Out-Null; Write-Output "Disabled '$Name'." }
    "enable" { Enable-ScheduledTask -TaskName $Name | Out-Null; Write-Output "Enabled '$Name'." }
    "uninstall" { Unregister-ScheduledTask -TaskName $Name -Confirm:$false; Write-Output "Removed '$Name'." }
}
