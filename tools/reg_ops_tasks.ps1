# Register ops helper tasks: logrotate / crash-alert / cost-watch / daily-review (ASCII only).
$py = $env:SOUL_PY
if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "找不到 python.exe，请设置 SOUL_PY 环境变量指向你的解释器" }
$root = "E:\soul1.0"

function Reg-Task($name, $arg, $sc, $mo, $st) {
    try { schtasks /Delete /TN $name /F 2>&1 | Out-Null } catch { }
    $action = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory $root
    if ($sc -eq "MINUTE") {
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes $mo) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $st
    }
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Days 3650)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Output ("registered " + $name)
}

Reg-Task "SoulLogRotate" "-X utf8 E:\soul1.0\tools\logrotate.py" "DAILY" 0 "03:00"
Reg-Task "SoulCrashAlert" "-X utf8 E:\soul1.0\tools\crash_alert.py --once" "MINUTE" 5 ""
Reg-Task "SoulCostWatch" "-X utf8 E:\soul1.0\tools\cost_watch.py" "DAILY" 0 "04:00"
Reg-Task "SoulDailyReview" "-X utf8 E:\soul1.0\tools\daily_review.py --json E:\soul1.0\data\state\daily_review.json" "DAILY" 0 "05:00"

Get-ScheduledTask | Where-Object { $_.TaskName -like "Soul*" } |
    Select-Object TaskName, State | Format-Table -AutoSize
