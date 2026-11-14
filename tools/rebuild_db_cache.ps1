# 重建本地库缓存：停 daemon -> 删坏缓存 -> 用新 sync 重拉 -> 验证
$ErrorActionPreference = "Continue"
Set-Location "E:\soul1.0"
$py = $env:SOUL_PY
if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "找不到 python.exe，请设置 SOUL_PY 环境变量指向你的解释器" }

Write-Output "--- 1) 停 daemon ---"
# 2026-11-14（E-09）：原版无差别杀全部 python（watchdog/msg_probe/silent_launch
#   一起陪葬，守护层全灭）。只杀真正的 daemon（命令行含 run.py daemon）。
Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'run\.py\s+daemon' } | ForEach-Object {
    Write-Output ("  kill daemon pid=" + $_.ProcessId)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Remove-Item "E:\soul1.0\data\state\daemon.lock" -Force -ErrorAction SilentlyContinue

Write-Output "--- 2) 删坏缓存 ---"
Remove-Item -Recurse -Force "E:\soul1.0\data\cache" -ErrorAction SilentlyContinue
Write-Output "  已删 data\cache"

Write-Output "--- 3) 用新 sync 重拉（open_account 会触发）---"
& $py -c "import sys; sys.path.insert(0, r'E:\soul1.0'); from core.device import Device; from data.imdb import open_account; db=open_account(Device.get()); print('uid=', db.uid, 'sessions=', db.stats().get('sessions')); print('unread=', db.con.execute('SELECT COUNT(*) FROM session WHERE unReadCount>0').fetchone()[0])" 2>&1

Write-Output "--- 4) 完整性验证 ---"
& $py tests\t_dbcheck.py 2>&1 | Select-String -Pattern "cache|malformed|integrity|chatmsg|wal" | Select-Object -First 12
