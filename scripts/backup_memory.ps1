[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$EnvFile = '',
    [string]$OutputDir = '',
    [int]$Keep = 20,
    [Alias('h', '?')]
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

function Show-Usage {
    @'
Usage: .\scripts\backup_memory.ps1 [-EnvFile <path>] [-OutputDir <path>]
                               [-Keep <count>]

Creates a consistent SQLite backup using Python's sqlite3 backup API.
Use `-Keep 0` to disable backup rotation. Default: 20.
'@
}

if ($RemainingArgs -contains '--help') {
    $Help = $true
}

if ($Help) {
    Show-Usage
    exit 0
}

if ($RemainingArgs.Count -gt 0) {
    Write-Error ("Unknown argument(s): {0}" -f ($RemainingArgs -join ' '))
    Show-Usage
    exit 2
}

if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $projectRoot '.env'
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $projectRoot 'backups'
}

if (-not (Test-Path $EnvFile)) {
    Write-Error "Environment file not found: $EnvFile"
    exit 1
}

if ($Keep -lt 0) {
    Write-Error "-Keep must be a non-negative integer."
    exit 2
}

function Normalize-EnvValue {
    param([string]$Value)

    $normalized = $Value.Trim()
    if ($normalized.Length -ge 2) {
        $startsWithSingle = $normalized.StartsWith("'")
        $endsWithSingle = $normalized.EndsWith("'")
        $startsWithDouble = $normalized.StartsWith('"')
        $endsWithDouble = $normalized.EndsWith('"')
        if (($startsWithSingle -and $endsWithSingle) -or ($startsWithDouble -and $endsWithDouble)) {
            $normalized = $normalized.Substring(1, $normalized.Length - 2)
        }
    }
    return $normalized
}

function Read-DatabaseUrlFromEnvFile {
    param([string]$Path)

    $databaseUrl = $null
    [System.IO.File]::ReadAllLines($Path, [System.Text.UTF8Encoding]::new($false)) | ForEach-Object {
        if ($_ -match "^\s*([^#=]+)\s*=\s*(.*)\s*$") {
            $key = $matches[1].Trim()
            if ($key -ne 'DATABASE_URL') {
                return
            }
            $databaseUrl = Normalize-EnvValue -Value $matches[2]
        }
    }
    return $databaseUrl
}

function Resolve-SqlitePathFromDatabaseUrl {
    param([string]$DatabaseUrl)

    $prefixes = @(
        'sqlite+aiosqlite:///',
        'sqlite:///'
    )
    $matchedPrefix = $prefixes | Where-Object { $DatabaseUrl.StartsWith($_) } | Select-Object -First 1
    if (-not $matchedPrefix) {
        throw "DATABASE_URL must start with 'sqlite+aiosqlite:///' or 'sqlite:///'"
    }

    $rawPath = $DatabaseUrl.Substring($matchedPrefix.Length)
    $queryIndex = $rawPath.IndexOf('?')
    if ($queryIndex -ge 0) {
        $rawPath = $rawPath.Substring(0, $queryIndex)
    }
    $fragmentIndex = $rawPath.IndexOf('#')
    if ($fragmentIndex -ge 0) {
        $rawPath = $rawPath.Substring(0, $fragmentIndex)
    }
    $rawPath = [System.Uri]::UnescapeDataString($rawPath.Trim())
    if ([string]::IsNullOrWhiteSpace($rawPath)) {
        throw "DATABASE_URL does not contain a valid sqlite file path"
    }

    if ([System.IO.Path]::IsPathRooted($rawPath)) {
        return $rawPath
    }

    return (Join-Path $projectRoot $rawPath)
}

function Resolve-PythonCommand {
    $explicitCandidates = @(
        (Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'),
        (Join-Path $projectRoot 'backend/.venv/bin/python')
    )

    foreach ($candidate in $explicitCandidates) {
        if (Test-Path -Path $candidate -PathType Leaf) {
            return $candidate
        }
    }

    foreach ($candidateName in @('python.exe', 'python3', 'python', 'py')) {
        $command = Get-Command $candidateName -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $command) {
            continue
        }

        $source = $command.Source
        if ([string]::IsNullOrWhiteSpace($source)) {
            continue
        }
        if ($source -like '*\WindowsApps\*') {
            continue
        }
        return $source
    }

    return $null
}

$databaseUrl = Read-DatabaseUrlFromEnvFile -Path $EnvFile
if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
    Write-Error "DATABASE_URL is missing in $EnvFile"
    exit 1
}

try {
    $sqlitePath = Resolve-SqlitePathFromDatabaseUrl -DatabaseUrl $databaseUrl
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}

if (-not (Test-Path $sqlitePath)) {
    Write-Error "SQLite database file not found: $sqlitePath"
    exit 1
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd_HHmmss")
$destFile = Join-Path $OutputDir ("memory_palace_backup_{0}.db" -f $timestamp)

$pythonCmd = Resolve-PythonCommand
if ([string]::IsNullOrWhiteSpace($pythonCmd)) {
    Write-Error "Python is required for consistent SQLite backup but was not found in the repo venv or PATH."
    exit 1
}

$env:MEMORY_PALACE_BACKUP_SOURCE = $sqlitePath
$env:MEMORY_PALACE_BACKUP_TARGET = $destFile
$backupScript = @'
import os
import sqlite3

source = os.environ["MEMORY_PALACE_BACKUP_SOURCE"]
target = os.environ["MEMORY_PALACE_BACKUP_TARGET"]

try:
    with sqlite3.connect(source, timeout=30.0) as source_conn:
        source_conn.execute("PRAGMA busy_timeout = 30000")
        with sqlite3.connect(target, timeout=30.0) as target_conn:
            target_conn.execute("PRAGMA busy_timeout = 30000")
            source_conn.backup(target_conn, pages=256, sleep=0.05)
except (OSError, sqlite3.Error):
    try:
        os.remove(target)
    except OSError:
        pass
    raise
'@

& $pythonCmd -c $backupScript
if ($LASTEXITCODE -ne 0) {
    Write-Error "Backup failed for ${sqlitePath}: sqlite backup command returned non-zero exit code."
    exit 1
}

Write-Host "Backup completed." -ForegroundColor Green
Write-Host "Source: $sqlitePath"
Write-Host "Target: $destFile"

if ($Keep -gt 0) {
    $backups = @(Get-ChildItem -Path $OutputDir -Filter 'memory_palace_backup_*.db' | Sort-Object Name)
    if ($backups.Count -gt $Keep) {
        $toRemove = @($backups | Select-Object -First ($backups.Count - $Keep))
        foreach ($item in $toRemove) {
            Remove-Item -Path $item.FullName -Force -ErrorAction SilentlyContinue
        }
        Write-Host ("Rotation: kept {0} backup(s), removed {1}." -f $Keep, $toRemove.Count)
    }
    else {
        Write-Host ("Rotation: kept {0} backup(s), removed 0." -f $backups.Count)
    }
}
