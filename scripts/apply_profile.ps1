<#
.SYNOPSIS
Generate a Memory Palace env file from a base template plus a deployment profile.

.DESCRIPTION
Appends a selected profile template onto `.env.example`, applies small
platform-specific autofills, validates unresolved placeholders, and can print
the generated env to stdout without touching the target file.

.EXAMPLE
./scripts/apply_profile.ps1 -Platform windows -Profile b

.EXAMPLE
./scripts/apply_profile.ps1 -Platform docker -Profile c -Target .env.docker -DryRun
#>

param(
    [ValidateSet('macos', 'linux', 'windows', 'docker')]
    [string]$Platform = 'windows',

    [ValidateSet('a', 'b', 'c', 'd', 'A', 'B', 'C', 'D')]
    [string]$Profile = 'b',

    [string]$Target = '',

    [switch]$DryRun,

    [Alias('Help', 'h', '?')]
    [switch]$ShowHelp
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$Platform = $Platform.ToLowerInvariant()
$profileLower = $Profile.ToLower()
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

if ($ShowHelp.IsPresent) {
    @'
Usage: ./scripts/apply_profile.ps1 [-Platform <macos|linux|windows|docker>] [-Profile <a|b|c|d>] [-Target <path>] [-DryRun]

Examples:
  ./scripts/apply_profile.ps1 -Platform windows -Profile b
  ./scripts/apply_profile.ps1 -Platform docker -Profile c -Target .env.docker -DryRun
'@ | Write-Host
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Target)) {
    if ($Platform -eq 'docker') {
        $Target = Join-Path $projectRoot '.env.docker'
    } else {
        $Target = Join-Path $projectRoot '.env'
    }
}

$baseEnv = Join-Path $projectRoot '.env.example'
$overrideEnv = Join-Path $projectRoot (
    "deploy/profiles/{0}/profile-{1}.env" -f $Platform, $profileLower
)

function Read-LinesUtf8 {
    param([string]$FilePath)

    if (-not (Test-Path $FilePath)) {
        return @()
    }

    return [System.IO.File]::ReadAllLines($FilePath, $utf8NoBom)
}

function Write-LinesUtf8 {
    param(
        [string]$FilePath,
        [string[]]$Lines
    )

    $parent = Split-Path -Parent $FilePath
    if (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    [System.IO.File]::WriteAllLines($FilePath, $Lines, $utf8NoBom)
}

function New-AdjacentTempFile {
    param(
        [string]$TargetPath,
        [string]$Label = 'tmp'
    )

    $parent = Split-Path -Parent $TargetPath
    if ([string]::IsNullOrWhiteSpace($parent)) {
        $parent = (Get-Location).Path
    }
    elseif (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $targetName = [System.IO.Path]::GetFileName($TargetPath)
    do {
        $candidate = Join-Path $parent (".{0}.{1}.{2}" -f $targetName, $Label, [guid]::NewGuid().ToString('N'))
    } while (Test-Path $candidate)

    return $candidate
}

function Acquire-TargetFileLock {
    param([string]$TargetPath)

    $parent = Split-Path -Parent $TargetPath
    if (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $lockPath = "$TargetPath.lock"
    try {
        $stream = New-TargetFileLockStream -LockPath $lockPath
    }
    catch {
        $ownerPid = Get-TargetFileLockOwnerPid -LockPath $lockPath
        if ($null -eq $ownerPid -and (Test-Path $lockPath)) {
            Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
            try {
                $stream = New-TargetFileLockStream -LockPath $lockPath
            }
            catch {
                Throw-TargetFileLockBusy -TargetPath $TargetPath
            }
        }
        elseif ($null -ne $ownerPid) {
            $ownerProcess = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($null -eq $ownerProcess) {
                Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
                try {
                    $stream = New-TargetFileLockStream -LockPath $lockPath
                }
                catch {
                    Throw-TargetFileLockBusy -TargetPath $TargetPath
                }
            }
        }

        if ($null -eq $stream) {
            Throw-TargetFileLockBusy -TargetPath $TargetPath
        }
    }

    try {
        $stream.SetLength(0)
        $payload = $PID.ToString()
        $bytes = $utf8NoBom.GetBytes($payload)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
    }
    catch {
        $stream.Dispose()
        Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
        throw
    }

    return @{
        Stream = $stream
        Path = $lockPath
    }
}

function Release-TargetFileLock {
    param($LockInfo)

    if ($null -eq $LockInfo) {
        return
    }

    try {
        if ($null -ne $LockInfo.Stream) {
            $LockInfo.Stream.Dispose()
        }
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($LockInfo.Path)) {
            Remove-Item -Path $LockInfo.Path -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-TargetFileLockStream {
    param([string]$LockPath)

    return [System.IO.File]::Open(
        $LockPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
}

function Get-TargetFileLockOwnerPid {
    param([string]$LockPath)

    if (-not (Test-Path $LockPath)) {
        return $null
    }

    try {
        $ownerText = ([System.IO.File]::ReadAllText($LockPath, $utf8NoBom)).Trim()
    }
    catch {
        return $null
    }

    $ownerPid = 0
    if (-not [int]::TryParse($ownerText, [ref]$ownerPid)) {
        return $null
    }
    if ($ownerPid -le 0) {
        return $null
    }

    return $ownerPid
}

function Throw-TargetFileLockBusy {
    param([string]$TargetPath)

    throw "[apply-profile-lock] another apply_profile.ps1 process is already writing $TargetPath; wait for it to finish before retrying."
}

function Test-RetryableFileCommitException {
    param([System.Exception]$Exception)

    if ($null -eq $Exception) {
        return $false
    }

    if ($Exception -is [System.UnauthorizedAccessException]) {
        return $true
    }

    if ($Exception -isnot [System.IO.IOException]) {
        return $false
    }

    $win32Code = $Exception.HResult -band 0xFFFF
    if ($win32Code -in @(5, 32, 33)) {
        return $true
    }

    return $Exception.Message -match '(?i)being used by another process|access to the path .* is denied'
}

function Invoke-FileCommitWithRetry {
    param(
        [scriptblock]$Operation,
        [string]$TargetPath,
        [int]$MaxAttempts = 3,
        [int]$BaseDelayMilliseconds = 50
    )

    $lastError = $null
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            & $Operation
            return
        }
        catch {
            $lastError = if ($null -ne $_.Exception) { $_.Exception } else { $_ }
            if (
                -not (Test-RetryableFileCommitException -Exception $lastError) `
                -or $attempt -ge $MaxAttempts
            ) {
                throw
            }
            Start-Sleep -Milliseconds ($BaseDelayMilliseconds * $attempt)
        }
    }

    if ($null -ne $lastError) {
        throw $lastError
    }
}

function Finalize-GeneratedEnvFile {
    param(
        [string]$TempPath,
        [string]$DestinationPath
    )

    $parent = Split-Path -Parent $DestinationPath
    if (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (Test-Path $DestinationPath) {
        $backupPath = "$DestinationPath.bak"
        Invoke-FileCommitWithRetry -TargetPath $DestinationPath -Operation {
            if (Test-Path $backupPath) {
                Remove-Item -Path $backupPath -Force -ErrorAction SilentlyContinue
            }
            [System.IO.File]::Replace($TempPath, $DestinationPath, $backupPath, $true)
        }
        Write-Host "[backup] Existing $DestinationPath saved to $backupPath"
        return
    }

    Invoke-FileCommitWithRetry -TargetPath $DestinationPath -Operation {
        [System.IO.File]::Move($TempPath, $DestinationPath)
    }
}

function Set-EnvValueInFile {
    param(
        [string]$FilePath,
        [string]$Key,
        [string]$Value
    )

    $lines = @(Read-LinesUtf8 -FilePath $FilePath)

    $escaped = [regex]::Escape($Key)
    $updated = $false
    $newLines = [System.Collections.Generic.List[string]]::new()

    foreach ($line in $lines) {
        if ($line -match "^\s*${escaped}\s*=") {
            if (-not $updated) {
                $updated = $true
                [void]$newLines.Add("$Key=$Value")
            }
            continue
        }

        [void]$newLines.Add([string]$line)
    }

    if (-not $updated) {
        [void]$newLines.Add("$Key=$Value")
    }

    Write-LinesUtf8 -FilePath $FilePath -Lines $newLines.ToArray()
}

function Dedupe-EnvKeys {
    param([string]$FilePath)

    if (-not (Test-Path $FilePath)) {
        return
    }

    $lines = @(Read-LinesUtf8 -FilePath $FilePath)
    $lastValues = [System.Collections.Generic.Dictionary[string, string]]::new()
    $firstSeen = [System.Collections.Generic.HashSet[string]]::new()
    $deduped = [System.Collections.Generic.List[string]]::new()

    foreach ($line in $lines) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=') {
            $key = $Matches[1]
            $value = ($line -split '=', 2)[1].TrimStart()
            $lastValues[$key] = $value
            if ($firstSeen.Contains($key)) {
                continue
            }
            [void]$firstSeen.Add($key)
            [void]$deduped.Add($key)
            continue
        }
        [void]$deduped.Add([string]$line)
    }

    $finalLines = [System.Collections.Generic.List[string]]::new()
    foreach ($item in $deduped) {
        if ($firstSeen.Contains($item) -and $lastValues.ContainsKey($item)) {
            [void]$finalLines.Add(("{0}={1}" -f $item, $lastValues[$item]))
            continue
        }
        [void]$finalLines.Add([string]$item)
    }

    Write-LinesUtf8 -FilePath $FilePath -Lines $finalLines.ToArray()
}

function Ensure-DefaultEnvValue {
    param(
        [string]$FilePath,
        [string]$Key,
        [string]$Value
    )

    $currentValue = (Get-EnvValueFromFile -FilePath $FilePath -Key $Key).Trim()
    if (-not [string]::IsNullOrWhiteSpace($currentValue)) {
        return
    }

    Set-EnvValueInFile -FilePath $FilePath -Key $Key -Value $Value
}

function Assert-ResolvedDatabaseUrlPlaceholder {
    param(
        [string]$FilePath,
        [string]$DisplayPath
    )

    if (-not (Test-Path $FilePath)) {
        return
    }

    $databaseUrlLine = Read-LinesUtf8 -FilePath $FilePath |
        Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } |
        Select-Object -Last 1

    if (-not $databaseUrlLine) {
        return
    }

    if (
        $databaseUrlLine.Contains('__REPLACE_ME__') `
        -or $databaseUrlLine -match '<[^>]+>' `
        -or $databaseUrlLine -match '(?i)placeholder'
    ) {
        [Console]::Error.WriteLine(
            "Generated {0}, but DATABASE_URL still contains unresolved placeholders:" -f $DisplayPath
        )
        [Console]::Error.WriteLine("  {0}" -f $databaseUrlLine)
        [Console]::Error.WriteLine(
            "Replace DATABASE_URL with a real host sqlite path before using this env file."
        )
        throw "Fill the DATABASE_URL placeholder before using this env file."
    }
}

function Get-EnvValueFromFile {
    param(
        [string]$FilePath,
        [string]$Key
    )

    if (-not (Test-Path $FilePath)) {
        return ''
    }

    $escaped = [regex]::Escape($Key)
    $lastLine = Read-LinesUtf8 -FilePath $FilePath |
        Where-Object { $_ -match "^\s*${escaped}\s*=" } |
        Select-Object -Last 1

    if (-not $lastLine) {
        return ''
    }

    return ($lastLine -split '=', 2)[1].TrimStart()
}

function Sync-DockerWalOverrides {
    param([string]$FilePath)

    $walEnabled = (Get-EnvValueFromFile -FilePath $FilePath -Key 'RUNTIME_WRITE_WAL_ENABLED').Trim()
    $journalMode = (Get-EnvValueFromFile -FilePath $FilePath -Key 'RUNTIME_WRITE_JOURNAL_MODE').Trim()

    if (-not [string]::IsNullOrWhiteSpace($walEnabled)) {
        Set-EnvValueInFile -FilePath $FilePath -Key 'MEMORY_PALACE_DOCKER_WAL_ENABLED' -Value $walEnabled
    }
    if (-not [string]::IsNullOrWhiteSpace($journalMode)) {
        Set-EnvValueInFile -FilePath $FilePath -Key 'MEMORY_PALACE_DOCKER_JOURNAL_MODE' -Value $journalMode
    }
}

function New-DockerMcpApiKey {
    $bytes = [byte[]]::new(24)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToHexString($bytes).ToLowerInvariant()
}

function Assert-ResolvedProfilePlaceholders {
    param(
        [string]$FilePath,
        [string]$ResolvedProfile
    )

    if ($ResolvedProfile -notin @('c', 'd')) {
        return
    }

    $unresolved = [System.Collections.Generic.List[string]]::new()
    foreach ($line in Read-LinesUtf8 -FilePath $FilePath) {
        if (
            $line -match '^\s*(ROUTER_API_BASE|RETRIEVAL_EMBEDDING_API_BASE|RETRIEVAL_RERANKER_API_BASE)\s*=\s*.*:PORT/' `
            -or $line -match '=\s*replace-with-your-key(\s+#.*)?\s*$' `
            -or $line -match '=\s*replace-with-your-embedding-dim(\s+#.*)?\s*$' `
            -or $line -match '=\s*<provider-vector-dim>(\s+#.*)?\s*$' `
            -or $line -match '=\s*your-embedding-model-id(\s+#.*)?\s*$' `
            -or $line -match '=\s*your-reranker-model-id(\s+#.*)?\s*$' `
            -or $line -match '=\s*([a-z][a-z0-9+.-]*://)?router\.example\.com([/:?#\s]|$)'
        ) {
            [void]$unresolved.Add($line)
        }
    }

    if ($unresolved.Count -eq 0) {
        return
    }

    [Console]::Error.WriteLine(
        ("Generated {0}, but profile {1} still contains unresolved placeholders:" -f $FilePath, $ResolvedProfile)
    )
    foreach ($item in $unresolved) {
        [Console]::Error.WriteLine("  {0}" -f $item)
    }
    throw "Fill the placeholder values before using profile $ResolvedProfile."
}

if (-not (Test-Path $baseEnv)) {
    throw "Missing base env template: $baseEnv"
}

if (-not (Test-Path $overrideEnv)) {
    throw "Missing profile template: $overrideEnv"
}

$workingTarget = $Target
$workingTargetIsTemporary = $false
$targetLock = $null
$dryRunOutput = $null
$errorMessage = $null

try {
    if ($DryRun.IsPresent) {
        $workingTarget = [System.IO.Path]::GetTempFileName()
        $workingTargetIsTemporary = $true
    }
    else {
        $targetLock = Acquire-TargetFileLock -TargetPath $Target
        $workingTarget = New-AdjacentTempFile -TargetPath $Target -Label 'staged'
        $workingTargetIsTemporary = $true
    }

    $combinedLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in Read-LinesUtf8 -FilePath $baseEnv) {
        [void]$combinedLines.Add([string]$line)
    }
    [void]$combinedLines.Add("")
    [void]$combinedLines.Add("# -----------------------------------------------------------------------------")
    [void]$combinedLines.Add("# Appended profile overrides ($Platform/profile-$profileLower)")
    [void]$combinedLines.Add("# -----------------------------------------------------------------------------")
    foreach ($line in Read-LinesUtf8 -FilePath $overrideEnv) {
        [void]$combinedLines.Add([string]$line)
    }
    Write-LinesUtf8 -FilePath $workingTarget -Lines $combinedLines.ToArray()

    if ($Platform -in @('macos', 'linux')) {
        $placeholderPattern = '^\s*DATABASE_URL\s*=\s*sqlite\+aiosqlite:////(Users|home)/[^/]+/memory_palace/agent_memory\.db(\s+#.*)?\s*$'
        if (Select-String -Path $workingTarget -Pattern $placeholderPattern -Quiet) {
            $dbPath = (Join-Path $projectRoot 'demo.db') -replace '\\', '/'
            if ($dbPath -match '^[A-Za-z]:/') {
                $dbUrl = 'DATABASE_URL=sqlite+aiosqlite:///' + $dbPath
            }
            else {
                $dbUrl = 'DATABASE_URL=sqlite+aiosqlite:////' + $dbPath.TrimStart('/')
            }
            Set-EnvValueInFile -FilePath $workingTarget -Key 'DATABASE_URL' -Value $dbUrl.Substring('DATABASE_URL='.Length)
            Write-Host "[auto-fill] DATABASE_URL set to $dbPath"
        }
    }

    if ($Platform -eq 'windows') {
        $placeholderPattern = '^\s*DATABASE_URL\s*=\s*sqlite\+aiosqlite:///C:/memory_palace/agent_memory\.db(\s+#.*)?\s*$'
        if (Select-String -Path $workingTarget -Pattern $placeholderPattern -Quiet) {
            $dbPath = (Join-Path $projectRoot 'demo.db') -replace '\\', '/'
            if ($dbPath -match '^/([a-zA-Z])/(.*)$') {
                $drive = $Matches[1].ToUpperInvariant()
                $dbPath = "${drive}:/$($Matches[2])"
            }
            elseif ($dbPath -match '^/mnt/([a-zA-Z])/(.*)$') {
                $drive = $Matches[1].ToUpperInvariant()
                $dbPath = "${drive}:/$($Matches[2])"
            }
            elseif ($dbPath -notmatch '^[A-Za-z]:/') {
                $dbPath = 'C:/memory_palace/demo.db'
            }
            $dbUrl = 'DATABASE_URL=sqlite+aiosqlite:///' + $dbPath
            Set-EnvValueInFile -FilePath $workingTarget -Key 'DATABASE_URL' -Value $dbUrl.Substring('DATABASE_URL='.Length)
            Write-Host "[auto-fill] DATABASE_URL set to $dbPath"
        }
    }

    if ($Platform -eq 'docker') {
        $currentApiKey = Get-EnvValueFromFile -FilePath $workingTarget -Key 'MCP_API_KEY'
        if ([string]::IsNullOrWhiteSpace($currentApiKey)) {
            $generatedApiKey = New-DockerMcpApiKey
            Set-EnvValueInFile -FilePath $workingTarget -Key 'MCP_API_KEY' -Value $generatedApiKey
            Write-Host "[auto-fill] MCP_API_KEY generated for docker profile"
        }
        Sync-DockerWalOverrides -FilePath $workingTarget
    }

    Ensure-DefaultEnvValue -FilePath $workingTarget -Key 'RUNTIME_AUTO_FLUSH_ENABLED' -Value 'true'
    Dedupe-EnvKeys -FilePath $workingTarget
    Assert-ResolvedDatabaseUrlPlaceholder -FilePath $workingTarget -DisplayPath $Target
    $allowUnresolvedProfilePlaceholders = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS')
    if ($allowUnresolvedProfilePlaceholders -eq '1') {
        Write-Host "[placeholder-guard] deferred profile placeholder validation to caller"
    }
    else {
        Assert-ResolvedProfilePlaceholders -FilePath $workingTarget -ResolvedProfile $profileLower
    }

    if ($DryRun.IsPresent) {
        $dryRunOutput = [System.IO.File]::ReadAllText($workingTarget, $utf8NoBom)
    }
    else {
        Finalize-GeneratedEnvFile -TempPath $workingTarget -DestinationPath $Target
        Write-Host "Generated $Target from $overrideEnv"
    }
}
catch {
    if ($null -ne $_.Exception -and -not [string]::IsNullOrWhiteSpace($_.Exception.Message)) {
        $errorMessage = $_.Exception.Message
    }
    else {
        $errorMessage = $_.ToString()
    }
}
finally {
    if ($workingTargetIsTemporary -and (Test-Path $workingTarget)) {
        Remove-Item -Path $workingTarget -Force -ErrorAction SilentlyContinue
    }
    if (-not $DryRun.IsPresent) {
        Release-TargetFileLock -LockInfo $targetLock
    }
}

if (-not [string]::IsNullOrWhiteSpace($errorMessage)) {
    [Console]::Error.WriteLine($errorMessage)
    exit 1
}

if ($DryRun.IsPresent) {
    [Console]::Out.Write($dryRunOutput)
    exit 0
}
