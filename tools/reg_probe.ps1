# Register and start the message probe as a scheduled task (ASCII only).
$py = $env:SOUL_PY
if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "找不到 python.exe，请设置 SOUL_PY 环境变量指向你的解释器" }
$arg = 'E:\soul1.0\tools\msg_probe.py --every 15 --sla 60 --fresh 600'

# Delete old task if present (ignore all errors)
try { schtasks /Delete /TN "SoulMsgProbe" /F 2>&1 | Out-Null } catch { }

$action = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory "E:\soul1.0"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName "SoulMsgProbe" -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Highest -Force | Out-Null

Start-ScheduledTask -TaskName "SoulMsgProbe"
Start-Sleep -Seconds 3

$t = Get-ScheduledTask -TaskName "SoulMsgProbe"
$i = Get-ScheduledTaskInfo -TaskName "SoulMsgProbe"
Write-Output ("TaskState=" + $t.State + " LastResult=" + $i.LastTaskResult + " NextRun=" + $i.NextRunTime)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*msg_probe*" } |
    Select-Object ProcessId, CommandLine | Format-List
