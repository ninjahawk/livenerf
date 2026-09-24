# Register, remove or inspect the daily livenerf task on Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 install
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 status
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 disable
#   powershell -ExecutionPolicy Bypass -File scripts\windows_task.ps1 uninstall
#
# One run a day (PREREGISTRATION.md, schedule): the task fires at 05:07 and then every hour until
# 23:07, and livenerf.daily does nothing once today's run is in. A day blocked by the usage guard, or
# missed while the PC slept, catches up at the next hourly attempt. It runs only while you are logged
# on (it needs the Claude Code login), hidden (conhost --headless, so no console window flashes),
# never more than one at a time. It is a clock trigger, not a logon trigger: nothing starts at boot.
# Output goes to logs\daily.log and logs\daily.jsonl.

param(
    [Parameter(Position = 0)][ValidateSet("install", "status", "disable", "enable", "uninstall")][string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$Name = "livenerf daily"
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo ".venv\Scripts\python.exe"

switch ($Command) {
    "install" {
        if (-not (Test-Path $Python)) { throw "No venv at $Python. Run 'uv sync' in $Repo first." }
        New-Item -ItemType Directory -Force (Join-Path $Repo "logs") | Out-Null
        $inner = "`"$Python`" -m livenerf.daily >> logs\daily.log 2>&1"
        $action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd.exe /c $inner" -WorkingDirectory $Repo
        $trigger = New-ScheduledTaskTrigger -Daily -At "05:07"
        $repeat = New-ScheduledTaskTrigger -Once -At "05:07" -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 18)
        $trigger.Repetition = $repeat.Repetition
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 55) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $settings.StartWhenAvailable = $false
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
            -Description "livenerf: one daily benchmark run against Claude Opus 5.5 ($Repo)" -Force | Out-Null
        Write-Output "Registered '$Name': daily at 05:07, retrying hourly until 23:07 until the day's run is in."
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
