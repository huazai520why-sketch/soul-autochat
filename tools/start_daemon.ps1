# Start soul1.0 daemon (background, detached)
#
# 2026-11-08 12:2x (report 16 section 6 item 4, previously never landed):
#   BEFORE: `& $py -u run.py daemon *>> $log` -- FOREGROUND BLOCKING.
#   daemon is a resident process, it never exits, so this script never returns.
#   Caller tools/msg_probe.py uses subprocess.run(..., timeout=90), so it
#   MATHEMATICALLY ALWAYS TimeoutExpired (measured 15/15):
#     - probe thinks "start failed"
#     - but daemon actually started
#     - next probe starts it again -> duplicate instances -> lock contention (26x)
#   NOW: Start-Process detached. Script returns immediately, daemon runs alone.
#   Parent is WmiPrvSE (created by scheduled task / WMI), survives SSH disconnect.
#
# NOTE: keep this file PURE ASCII. Chinese chars get mangled to GBK over scp
#       and cause "string missing terminator" parser errors on the remote host.
$ErrorActionPreference = "Continue"
Set-Location "E:\soul1.0"

$py = $env:SOUL_PY
if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "python.exe not found; set SOUL_PY env var to your interpreter" }
$log = "E:\soul1.0\logs\daemon.out"

function Write-Log([string]$msg) {
    # daemon.out is held open by the running daemon, so a plain Out-File can
    # fail with "being used by another process". That must NOT abort startup --
    # logging is best-effort here, the exit code carries the real result.
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    try {
        $fs = [System.IO.File]::Open($log, 'Append', 'Write', 'ReadWrite')
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($line + "`r`n")
        $fs.Write($bytes, 0, $bytes.Length)
        $fs.Close()
    } catch {
        Write-Output $line
    }
}

# Do not start a second instance if one is already running.
$existing = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'run\.py daemon' }
if ($existing) {
    $pids = ($existing | ForEach-Object { $_.ProcessId }) -join ','
    Write-Log "=== daemon already running (pid=$pids) -> skip ==="
    exit 0
}

Write-Log "=== daemon starting (detached) ==="

Start-Process -FilePath $py `
              -ArgumentList '-u', 'run.py', 'daemon' `
              -WorkingDirectory 'E:\soul1.0' `
              -WindowStyle Hidden

Start-Sleep -Seconds 2
$now = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
       Where-Object { $_.CommandLine -match 'run\.py daemon' }
if ($now) {
    $pids = ($now | ForEach-Object { $_.ProcessId }) -join ','
    Write-Log "=== daemon started pid=$pids ==="
    exit 0
} else {
    Write-Log "=== daemon NOT detected after start ==="
    exit 1
}
