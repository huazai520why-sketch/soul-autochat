<#
    repo_sync.ps1 -- keep every machine identical with the same GitHub repo.

    Why ASCII only: Windows PowerShell 5.1 decodes UTF-8 without BOM incorrectly,
    so a Chinese comment here would turn into garbage or break parsing.

    Usage (run from anywhere, the script locates the repo root itself):

        powershell -ExecutionPolicy Bypass -File scripts\repo_sync.ps1 -Check
        powershell -ExecutionPolicy Bypass -File scripts\repo_sync.ps1 -Pull
        powershell -ExecutionPolicy Bypass -File scripts\repo_sync.ps1 -Push "feat: ..."

    -Check  : show drift vs origin, and scan tracked files for secrets.
              Exit code 0 = in sync and clean, 1 = drift or secrets found.
    -Pull   : fast-forward only. Refuses if local has uncommitted changes.
    -Push   : secret scan -> git add -A -> commit -> push.

    Secret scan is a guard rail, not a proof. It catches the obvious leaks
    (api keys, phone numbers, private IPs, personal user paths). Always run
    -Check before -Push.
#>

param(
    [switch]$Check,
    [switch]$Pull,
    [string]$Push = ""
)

$ErrorActionPreference = "Stop"

# Repo root = parent of the folder this script lives in
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Fail($msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}

function Git($args) {
    $out = & git @args 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') -> $out" }
    return $out
}

# ---------------------------------------------------------------- secret scan
# Values that are intentionally public in this repo (examples in docs/templates)
$Whitelist = @(
    '13800138000',            # example contact number in the template / defaults
    'C:\Users\me',            # example path in a docstring
    'sk-[A-Za-z0-9_-]{16,}'   # the pattern itself, appears in this script
)

$Patterns = @(
    @{ Name = 'api key';     Rx = 'sk-[A-Za-z0-9_-]{20,}' },
    @{ Name = 'bearer';      Rx = 'Bearer\s+[A-Za-z0-9._-]{20,}' },
    @{ Name = 'cn mobile';   Rx = '(?<!\d)1[3-9]\d{9}(?!\d)' },
    @{ Name = 'private ip';  Rx = '192\.168\.\d{1,3}\.\d{1,3}' },
    @{ Name = 'user path';   Rx = 'C:\\\\?Users\\\\?[A-Za-z0-9_.-]+' },
    @{ Name = 'soul uid';    Rx = 'uid=\d{7,11}' }
)

function Get-TrackedFiles {
    $files = & git ls-files 2>$null
    if ($LASTEXITCODE -ne 0) { return @() }
    return $files | Where-Object { $_ -and (Test-Path $_) }
}

function Invoke-SecretScan {
    $files = Get-TrackedFiles
    if ($files.Count -eq 0) { return }
    $hits = 0
    foreach ($f in $files) {
        # only text-ish files
        if ($f -match '\.(png|jpg|jpeg|webp|wav|mp3|db|apk|b64|pyc)$') { continue }
        try { $lines = Get-Content -LiteralPath $f -Encoding UTF8 -ErrorAction Stop }
        catch { continue }
        $i = 0
        foreach ($line in $lines) {
            $i++
            foreach ($p in $Patterns) {
                if ($line -match $p.Rx) {
                    $skip = $false
                    foreach ($w in $Whitelist) { if ($line -match [regex]::Escape($w)) { $skip = $true } }
                    if ($skip) { continue }
                    Write-Host ("  [{0}] {1}:{2}  {3}" -f $p.Name, $f, $i, $line.Trim()) -ForegroundColor Yellow
                    $hits++
                }
            }
        }
    }
    if ($hits -gt 0) {
        Write-Host "SECRET SCAN: $hits suspicious line(s). Fix before pushing." -ForegroundColor Red
        exit 1
    }
    Write-Host "SECRET SCAN: clean" -ForegroundColor Green
}

# ---------------------------------------------------------------- actions
if ($Check) {
    Write-Host "== repo: $Root" -ForegroundColor Cyan
    $branch = & git rev-parse --abbrev-ref HEAD 2>$null
    if (-not $branch) { Fail "not a git repository" }
    Write-Host "branch: $branch"

    $dirty = & git status --porcelain
    if ($dirty) {
        Write-Host "uncommitted changes:" -ForegroundColor Yellow
        $dirty | ForEach-Object { Write-Host "  $_" }
    } else {
        Write-Host "working tree clean" -ForegroundColor Green
    }

    $local = (& git rev-parse HEAD).Trim()
    $remoteRef = (& git rev-parse "origin/$branch" 2>$null)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "origin/$branch unknown (run: git fetch)" -ForegroundColor Yellow
    } else {
        $remote = $remoteRef.Trim()
        if ($local -eq $remote) {
            Write-Host "in sync with origin/$branch  ($($local.Substring(0,8)))" -ForegroundColor Green
        } else {
            Write-Host "DRIFT: local=$($local.Substring(0,8)) origin=$($remote.Substring(0,8))" -ForegroundColor Yellow
            & git log --oneline "$remote..$local" 2>$null | ForEach-Object { Write-Host "  ahead:  $_" }
            & git log --oneline "$local..$remote" 2>$null | ForEach-Object { Write-Host "  behind: $_" }
        }
    }
    Invoke-SecretScan
    exit 0
}

if ($Pull) {
    $dirty = & git status --porcelain
    if ($dirty) { Fail "working tree not clean; commit or stash first" }
    Git @('fetch', '--all', '--prune')
    Git @('pull', '--ff-only')
    Write-Host "pulled. HEAD = $((& git rev-parse --short HEAD))" -ForegroundColor Green
    exit 0
}

if ($Push -ne "") {
    Invoke-SecretScan
    Git @('add', '-A')
    $staged = & git diff --cached --name-only
    if (-not $staged) {
        Write-Host "nothing to commit" -ForegroundColor Yellow
        exit 0
    }
    Write-Host "staged:" -ForegroundColor Cyan
    $staged | ForEach-Object { Write-Host "  $_" }
    Git @('commit', '-m', $Push)
    Git @('push', 'origin', 'HEAD')
    Write-Host "pushed. HEAD = $((& git rev-parse --short HEAD))" -ForegroundColor Green
    exit 0
}

Write-Host "usage:" -ForegroundColor Cyan
Write-Host "  repo_sync.ps1 -Check"
Write-Host "  repo_sync.ps1 -Pull"
Write-Host '  repo_sync.ps1 -Push "message"'
exit 2
