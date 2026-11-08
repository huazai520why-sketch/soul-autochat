# Restart soul1.0 daemon (do NOT touch db cache)
# ASCII only: GBK console chokes on Chinese/emoji in ps1
#
# 2026-11-04:
#  - old start_daemon.ps1 used "*>>" (PowerShell redirection) -> the child's
#    UTF-8 bytes got re-encoded as UTF-16LE -> daemon.out became mixed encoding
#    and every UTF-8 diagnostic tool broke. start_daemon.ps1 now uses cmd
#    redirection (byte pass-through).
#  - therefore ALWAYS rotate daemon.out here: a mixed file can never be read
#    correctly again. Keep the last 5 rotated files.
$ErrorActionPreference = "Continue"
Set-Location "E:\soul1.0"

Write-Output "--- stop old daemon ---"
$killed = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*run.py*daemon*" } |
    ForEach-Object {
        Write-Output ("  kill pid=" + $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
if ($killed -eq 0) { Write-Output "  no daemon running" }
Start-Sleep -Seconds 2
Remove-Item "E:\soul1.0\data\state\daemon.lock" -Force -ErrorAction SilentlyContinue

# 2026-11-04: a stale -shm (older than -wal) makes SQLite truncate the wal tail,
# so a read-only connection never sees the newest session rows (unread=2 became 0).
# The daemon holds the shm file open, so it can only be removed AFTER the kill.
Write-Output "--- clean stale shm ---"
Get-ChildItem "E:\soul1.0\data\cache" -Recurse -Filter "*-DATA.db-shm" -ErrorAction SilentlyContinue |
    ForEach-Object {
        try {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            Write-Output ("  removed " + $_.Name)
        } catch {
            Write-Output ("  keep " + $_.Name)
        }
    }

$log = "E:\soul1.0\logs\daemon.out"
if (Test-Path $log) {
    $dst = "E:\soul1.0\logs\daemon.out.bak-" + (Get-Date -Format "MMdd-HHmmss")
    try {
        Move-Item $log $dst -Force
        Write-Output ("  rotated log -> " + $dst)
    } catch {
        Write-Output "  WARN: log rotate failed"
    }
}
$old = Get-ChildItem "E:\soul1.0\logs\daemon.out.bak-*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip 5
$old | ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }

Write-Output "--- start ---"
$arg = @{
    CommandLine      = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\soul1.0\tools\start_daemon.ps1"
    CurrentDirectory = "E:\soul1.0"
}
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $arg
Write-Output ("  WMI Create ReturnValue=" + $r.ReturnValue + "  PID=" + $r.ProcessId)

Start-Sleep -Seconds 14
Write-Output "--- verify ---"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine | Format-List | Out-String -Width 200
if (Test-Path $log) {
    $fi = Get-Item $log
    Write-Output ("  log size=" + $fi.Length)
    $bytes = [System.IO.File]::ReadAllBytes($log)
    $n = [Math]::Min(200, $bytes.Length)
    $head = ($bytes[0..($n-1)] | ForEach-Object { $_.ToString("X2") }) -join " "
    Write-Output ("  head hex=" + $head)
}
