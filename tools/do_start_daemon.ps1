# 在副机上执行：清死锁 -> WMI 创建常驻 daemon -> 验证
$ErrorActionPreference = "Continue"
Set-Location "E:\soul1.0"

Remove-Item "E:\soul1.0\data\state\daemon.lock" -Force -ErrorAction SilentlyContinue

$arg = @{
    CommandLine      = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\soul1.0\tools\start_daemon.ps1"
    CurrentDirectory = "E:\soul1.0"
}
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $arg
Write-Output ("WMI Create: ReturnValue=" + $r.ReturnValue + "  PID=" + $r.ProcessId)

Start-Sleep -Seconds 10

Write-Output "--- python 进程 ---"
Get-Process python -ErrorAction SilentlyContinue |
    Select-Object Id, CPU, StartTime | Format-Table -AutoSize

Write-Output "--- 锁 ---"
if (Test-Path "E:\soul1.0\data\state\daemon.lock") {
    Get-Content "E:\soul1.0\data\state\daemon.lock"
} else {
    Write-Output "无锁文件"
}

Write-Output "--- daemon.out 尾部 ---"
if (Test-Path "E:\soul1.0\logs\daemon.out") {
    Get-Content "E:\soul1.0\logs\daemon.out" -Tail 8
} else {
    Write-Output "还没有 daemon.out"
}
