param(
    [string]$Profile = 'b',

    [string]$FrontendPort = '',

    [string]$BackendPort = '',

    [switch]$NoAutoPort,

    [switch]$NoBuild,

    [switch]$AllowRuntimeEnvInjection
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$script:PortProbeFallbackWarned = $false
$script:FrontendPortLockDir = $null
$script:BackendPortLockDir = $null
$script:DeploymentLockDir = $null
$script:GeneratedDockerEnvFile = $null
$script:PreviousDockerEnvFile = $null

function Exit-ValidationError {
    param([string]$Message)

    [Console]::Error.WriteLine($Message)
    exit 2
}

function Assert-ValidProfile {
    param([string]$ProfileName)

    if ([string]::IsNullOrWhiteSpace($ProfileName)) {
        Exit-ValidationError "Profile is required. Expected one of: a | b | c | d"
    }

    $normalizedProfile = $ProfileName.Trim().ToLowerInvariant()
    if ($normalizedProfile -notin @('a', 'b', 'c', 'd')) {
        Exit-ValidationError "Unsupported profile: $normalizedProfile. Expected one of: a | b | c | d"
    }

    return $normalizedProfile
}

function Resolve-PortValue {
    param(
        [string]$Value,
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        Exit-ValidationError "$Name is required"
    }

    $trimmedValue = $Value.Trim()
    $parsedValue = 0
    if (-not [int]::TryParse($trimmedValue, [ref]$parsedValue)) {
        Exit-ValidationError "$Name must be an integer, got $trimmedValue"
    }

    return $parsedValue
}

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

function Resolve-StableEnvFilePath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $Path
    }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Get-DefaultComposeProjectName {
    $projectSlug = (Split-Path -Leaf $projectRoot).ToLower() -replace '[^a-z0-9]+', '-'
    $projectSlug = $projectSlug.Trim('-')
    if ([string]::IsNullOrWhiteSpace($projectSlug)) {
        $projectSlug = 'memory-palace'
    }

    $normalizedProjectRoot = $projectRoot -replace '\\', '/'
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalizedProjectRoot)
    $hashBytes = [System.Security.Cryptography.SHA256]::HashData($bytes)
    $hash = ([System.BitConverter]::ToString($hashBytes)).Replace('-', '').Substring(0, 8).ToLower()
    return "$projectSlug-$hash"
}

function Test-PortInUse {
    param([int]$Port)

    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "Invalid port: $Port"
    }

    $getNetTcpConnection = Get-Command -Name 'Get-NetTCPConnection' -ErrorAction SilentlyContinue
    if ($getNetTcpConnection) {
        try {
            $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
            return ($listeners.Count -gt 0)
        }
        catch {
            if (-not $script:PortProbeFallbackWarned) {
                Write-Warning "Port probe fallback engaged: Get-NetTCPConnection failed unexpectedly; trying ss-based probing before fail-closed fallback. detail=$($_.Exception.Message)"
                $script:PortProbeFallbackWarned = $true
            }
        }
    }

    $ssCommand = Get-Command -Name 'ss' -ErrorAction SilentlyContinue
    if ($ssCommand) {
        $ssOutput = & ss -ltnH "( sport = :$Port )" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (-not [string]::IsNullOrWhiteSpace(($ssOutput | Out-String).Trim()))
        }
        if (-not $script:PortProbeFallbackWarned) {
            Write-Warning "Port probe fallback engaged: ss probing returned exit code $LASTEXITCODE; fail-closed probing is enabled."
            $script:PortProbeFallbackWarned = $true
        }
        return $true
    }

    if (-not $script:PortProbeFallbackWarned) {
        Write-Warning "Port probe fallback engaged: neither Get-NetTCPConnection nor ss is available; fail-closed probing is enabled."
        $script:PortProbeFallbackWarned = $true
    }
    # Fail-closed to avoid selecting potentially occupied ports when probe is unavailable.
    return $true
}

function Try-AcquirePathLock {
    param([string]$TargetPath)

    $lockDir = "${TargetPath}.lockdir"
    $ownerFile = Join-Path $lockDir 'owner_pid'
    $parentDir = Split-Path -Parent $TargetPath
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }

    try {
        New-Item -ItemType Directory -Path $lockDir -ErrorAction Stop | Out-Null
        Set-Content -Path $ownerFile -Value "$PID" -NoNewline
        return $lockDir
    }
    catch {
    }

    if (Test-Path $ownerFile) {
        $ownerPid = (Get-Content -Path $ownerFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        $ownerProcess = $null
        if ($ownerPid) {
            $ownerProcess = Get-Process -Id ([int]$ownerPid) -ErrorAction SilentlyContinue
        }
        if (-not $ownerProcess) {
            Remove-Item -Path $lockDir -Recurse -Force -ErrorAction SilentlyContinue
            try {
                New-Item -ItemType Directory -Path $lockDir -ErrorAction Stop | Out-Null
                Set-Content -Path $ownerFile -Value "$PID" -NoNewline
                return $lockDir
            }
            catch {
            }
        }
    }

    return $null
}

function Release-PathLock {
    param([string]$LockDir)

    if (-not [string]::IsNullOrWhiteSpace($LockDir)) {
        Remove-Item -Path $LockDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-FreePort {
    param(
        [int]$StartPort,
        [int]$MaxScan = 200,
        [Nullable[int]]$ExcludePort = $null
    )

    for ($i = 0; $i -le $MaxScan; $i++) {
        $candidate = $StartPort + $i
        if ($candidate -gt 65535) {
            break
        }
        if ($ExcludePort.HasValue -and $candidate -eq $ExcludePort.Value) {
            continue
        }
        if (-not (Test-PortInUse -Port $candidate)) {
            $lockDir = Try-AcquirePathLock -TargetPath (Join-Path ([System.IO.Path]::GetTempPath()) "memory-palace-port-locks/port-$candidate")
            if ($lockDir) {
                if (-not (Test-PortInUse -Port $candidate)) {
                    return @{
                        Port = $candidate
                        LockDir = $lockDir
                    }
                }
                Release-PathLock -LockDir $lockDir
            }
        }
    }

    throw "Failed to find free port near $StartPort"
}

function Assert-ValidPort {
    param(
        [int]$Port,
        [string]$Name
    )

    if ($Port -lt 1 -or $Port -gt 65535) {
        Exit-ValidationError "$Name must be in range [1, 65535], got $Port"
    }
}

function Resolve-DataVolume {
    if ($env:MEMORY_PALACE_DATA_VOLUME) {
        return $env:MEMORY_PALACE_DATA_VOLUME
    }
    if ($env:NOCTURNE_DATA_VOLUME) {
        return $env:NOCTURNE_DATA_VOLUME
    }

    $projectName = $composeProjectName
    if ([string]::IsNullOrWhiteSpace($projectName)) {
        $projectName = Get-DefaultComposeProjectName
    }

    $newVolume = "${projectName}_data"
    $legacyCandidates = @(
        'memory_palace_data',
        'nocturne_data',
        'nocturne_memory_data'
    )

    docker volume inspect $newVolume 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return $newVolume
    }

    foreach ($legacyVolume in $legacyCandidates) {
        docker volume inspect $legacyVolume 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            continue
        }
        Write-Host "[compat] found legacy shared docker volume '$legacyVolume', but defaulting to isolated volume '$newVolume'. Set MEMORY_PALACE_DATA_VOLUME=$legacyVolume to reuse old data intentionally."
        break
    }

    return $newVolume
}

function Resolve-SnapshotsVolume {
    if ($env:MEMORY_PALACE_SNAPSHOTS_VOLUME) {
        return $env:MEMORY_PALACE_SNAPSHOTS_VOLUME
    }
    if ($env:NOCTURNE_SNAPSHOTS_VOLUME) {
        return $env:NOCTURNE_SNAPSHOTS_VOLUME
    }

    $projectName = $composeProjectName
    if ([string]::IsNullOrWhiteSpace($projectName)) {
        $projectName = Get-DefaultComposeProjectName
    }

    $newVolume = "${projectName}_snapshots"
    docker volume inspect $newVolume 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return $newVolume
    }

    $legacyCandidates = @(
        'memory_palace_snapshots',
        'nocturne_snapshots'
    )
    foreach ($legacyVolume in $legacyCandidates) {
        docker volume inspect $legacyVolume 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            continue
        }
        Write-Host "[compat] found legacy shared docker volume '$legacyVolume', but defaulting to isolated volume '$newVolume'. Set MEMORY_PALACE_SNAPSHOTS_VOLUME=$legacyVolume to reuse old snapshots intentionally."
        break
    }

    return $newVolume
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
    $line = Read-LinesUtf8 -FilePath $FilePath | Where-Object { $_ -match "^${escaped}=" } | Select-Object -Last 1
    if (-not $line) {
        return ''
    }
    return ($line -replace "^${escaped}=", '')
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
    $newLines = foreach ($line in $lines) {
        if ($line -match "^${escaped}=") {
            if (-not $updated) {
                $updated = $true
                "$Key=$Value"
            }
        }
        else {
            $line
        }
    }

    if (-not $updated) {
        $newLines += "$Key=$Value"
    }

    Write-LinesUtf8 -FilePath $FilePath -Lines $newLines
}

function Get-HostnameFromUrl {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return ''
    }

    try {
        $uri = [System.Uri]$Url
    }
    catch {
        return ''
    }

    return ([string]$uri.Host).Trim().ToLowerInvariant()
}

function Rewrite-LoopbackApiBaseForDocker {
    param([string]$ApiBase)

    if ([string]::IsNullOrWhiteSpace($ApiBase)) {
        return ''
    }

    try {
        $builder = [System.UriBuilder]$ApiBase
    }
    catch {
        return $ApiBase
    }

    $host = ([string]$builder.Host).Trim().ToLowerInvariant()
    if ($host -notin @('127.0.0.1', 'localhost', '::1')) {
        return $ApiBase
    }

    $builder.Host = 'host.docker.internal'
    return $builder.Uri.GetLeftPart([System.UriPartial]::Path).TrimEnd('/')
}

function Append-EnvCsvValueInFile {
    param(
        [string]$FilePath,
        [string]$Key,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    $entries = New-Object System.Collections.Generic.List[string]
    foreach ($rawGroup in @((Get-EnvValueFromFile -FilePath $FilePath -Key $Key), $Value)) {
        foreach ($rawEntry in [string]$rawGroup -split ',') {
            $entry = $rawEntry.Trim()
            if ([string]::IsNullOrWhiteSpace($entry)) {
                continue
            }
            if (-not $entries.Contains($entry)) {
                [void]$entries.Add($entry)
            }
        }
    }

    $updatedValue = $entries -join ','
    if ($updatedValue -eq (Get-EnvValueFromFile -FilePath $FilePath -Key $Key)) {
        return $false
    }

    Set-EnvValueInFile -FilePath $FilePath -Key $Key -Value $updatedValue
    return $true
}

function Rewrite-EnvApiBaseForDocker {
    param(
        [string]$EnvFile,
        [string]$Key
    )

    $currentValue = Get-EnvValueFromFile -FilePath $EnvFile -Key $Key
    if ([string]::IsNullOrWhiteSpace($currentValue)) {
        return
    }

    $rewrittenValue = Rewrite-LoopbackApiBaseForDocker -ApiBase $currentValue
    if ([string]::IsNullOrWhiteSpace($rewrittenValue) -or $rewrittenValue -eq $currentValue) {
        return
    }

    Set-EnvValueInFile -FilePath $EnvFile -Key $Key -Value $rewrittenValue
    Write-Host "[override] $Key mapped loopback host to host.docker.internal for docker runtime injection."
}

function Append-ProviderAllowlistHostFromApiBase {
    param(
        [string]$EnvFile,
        [string]$ApiBase,
        [string]$SourceKey
    )

    $providerHost = Get-HostnameFromUrl -Url $ApiBase
    if ([string]::IsNullOrWhiteSpace($providerHost)) {
        return
    }
    if ($providerHost -in @('127.0.0.1', '::1', 'localhost')) {
        return
    }

    if (Append-EnvCsvValueInFile -FilePath $EnvFile -Key 'MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS' -Value $providerHost) {
        Write-Host "[override] MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS appended $providerHost from $SourceKey."
    }
}

function Apply-ProfileRuntimeOverrides {
    param(
        [string]$EnvFile,
        [string]$SelectedProfile
    )

    $overrideKeys = @(
        'ROUTER_API_BASE',
        'ROUTER_API_KEY',
        'ROUTER_CHAT_MODEL',
        'ROUTER_EMBEDDING_MODEL',
        'ROUTER_RERANKER_MODEL',
        'RETRIEVAL_EMBEDDING_BACKEND',
        'RETRIEVAL_EMBEDDING_API_BASE',
        'RETRIEVAL_EMBEDDING_API_KEY',
        'RETRIEVAL_EMBEDDING_DIM',
        'RETRIEVAL_EMBEDDING_MODEL',
        'RETRIEVAL_RERANKER_ENABLED',
        'RETRIEVAL_RERANKER_API_BASE',
        'RETRIEVAL_RERANKER_API_KEY',
        'RETRIEVAL_RERANKER_MODEL',
        'WRITE_GUARD_LLM_ENABLED',
        'WRITE_GUARD_LLM_API_BASE',
        'WRITE_GUARD_LLM_API_KEY',
        'WRITE_GUARD_LLM_MODEL',
        'COMPACT_GIST_LLM_ENABLED',
        'COMPACT_GIST_LLM_API_BASE',
        'COMPACT_GIST_LLM_API_KEY',
        'COMPACT_GIST_LLM_MODEL',
        'INTENT_LLM_ENABLED',
        'INTENT_LLM_API_BASE',
        'INTENT_LLM_API_KEY',
        'INTENT_LLM_MODEL',
        'MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS',
        'MCP_API_KEY',
        'MCP_API_KEY_ALLOW_INSECURE_LOCAL'
    )

    foreach ($key in $overrideKeys) {
        $overrideValue = [System.Environment]::GetEnvironmentVariable($key)
        if (-not [string]::IsNullOrWhiteSpace($overrideValue)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key $key -Value $overrideValue
            Write-Host "[override] $key applied to $EnvFile"
        }
    }

    if ($SelectedProfile -in @('c', 'd')) {
        Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_EMBEDDING_BACKEND' -Value 'api'
        Write-Host "[override] RETRIEVAL_EMBEDDING_BACKEND=api forced for local profile $SelectedProfile runtime injection."

        $routerApiBase = [System.Environment]::GetEnvironmentVariable('ROUTER_API_BASE')
        $routerApiKey = [System.Environment]::GetEnvironmentVariable('ROUTER_API_KEY')
        $routerEmbeddingModel = [System.Environment]::GetEnvironmentVariable('ROUTER_EMBEDDING_MODEL')
        $routerRerankerModel = [System.Environment]::GetEnvironmentVariable('ROUTER_RERANKER_MODEL')
        $embeddingApiBase = [System.Environment]::GetEnvironmentVariable('RETRIEVAL_EMBEDDING_API_BASE')
        $embeddingApiKey = [System.Environment]::GetEnvironmentVariable('RETRIEVAL_EMBEDDING_API_KEY')
        $embeddingModel = [System.Environment]::GetEnvironmentVariable('RETRIEVAL_EMBEDDING_MODEL')
        $rerankerApiBase = [System.Environment]::GetEnvironmentVariable('RETRIEVAL_RERANKER_API_BASE')
        $rerankerApiKey = [System.Environment]::GetEnvironmentVariable('RETRIEVAL_RERANKER_API_KEY')
        $rerankerModel = [System.Environment]::GetEnvironmentVariable('RETRIEVAL_RERANKER_MODEL')

        if ([string]::IsNullOrWhiteSpace($embeddingApiBase) -and -not [string]::IsNullOrWhiteSpace($routerApiBase)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_EMBEDDING_API_BASE' -Value $routerApiBase
            Write-Host "[override] RETRIEVAL_EMBEDDING_API_BASE copied from ROUTER_API_BASE for local profile $SelectedProfile runtime injection."
        }
        if ([string]::IsNullOrWhiteSpace($embeddingApiKey) -and -not [string]::IsNullOrWhiteSpace($routerApiKey)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_EMBEDDING_API_KEY' -Value $routerApiKey
            Write-Host "[override] RETRIEVAL_EMBEDDING_API_KEY copied from ROUTER_API_KEY for local profile $SelectedProfile runtime injection."
        }
        if ([string]::IsNullOrWhiteSpace($embeddingModel) -and -not [string]::IsNullOrWhiteSpace($routerEmbeddingModel)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_EMBEDDING_MODEL' -Value $routerEmbeddingModel
            Write-Host "[override] RETRIEVAL_EMBEDDING_MODEL copied from ROUTER_EMBEDDING_MODEL for local profile $SelectedProfile runtime injection."
        }
        if ([string]::IsNullOrWhiteSpace($rerankerApiBase) -and -not [string]::IsNullOrWhiteSpace($routerApiBase)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_RERANKER_API_BASE' -Value $routerApiBase
            Write-Host "[override] RETRIEVAL_RERANKER_API_BASE copied from ROUTER_API_BASE for local profile $SelectedProfile runtime injection."
        }
        if ([string]::IsNullOrWhiteSpace($rerankerApiKey) -and -not [string]::IsNullOrWhiteSpace($routerApiKey)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_RERANKER_API_KEY' -Value $routerApiKey
            Write-Host "[override] RETRIEVAL_RERANKER_API_KEY copied from ROUTER_API_KEY for local profile $SelectedProfile runtime injection."
        }
        if ([string]::IsNullOrWhiteSpace($rerankerModel) -and -not [string]::IsNullOrWhiteSpace($routerRerankerModel)) {
            Set-EnvValueInFile -FilePath $EnvFile -Key 'RETRIEVAL_RERANKER_MODEL' -Value $routerRerankerModel
            Write-Host "[override] RETRIEVAL_RERANKER_MODEL copied from ROUTER_RERANKER_MODEL for local profile $SelectedProfile runtime injection."
        }

        Rewrite-EnvApiBaseForDocker -EnvFile $EnvFile -Key 'ROUTER_API_BASE'
        Rewrite-EnvApiBaseForDocker -EnvFile $EnvFile -Key 'RETRIEVAL_EMBEDDING_API_BASE'
        Rewrite-EnvApiBaseForDocker -EnvFile $EnvFile -Key 'RETRIEVAL_RERANKER_API_BASE'
        Rewrite-EnvApiBaseForDocker -EnvFile $EnvFile -Key 'WRITE_GUARD_LLM_API_BASE'
        Rewrite-EnvApiBaseForDocker -EnvFile $EnvFile -Key 'COMPACT_GIST_LLM_API_BASE'
        Rewrite-EnvApiBaseForDocker -EnvFile $EnvFile -Key 'INTENT_LLM_API_BASE'

        Append-ProviderAllowlistHostFromApiBase -EnvFile $EnvFile -ApiBase (Get-EnvValueFromFile -FilePath $EnvFile -Key 'RETRIEVAL_EMBEDDING_API_BASE') -SourceKey 'RETRIEVAL_EMBEDDING_API_BASE'
        Append-ProviderAllowlistHostFromApiBase -EnvFile $EnvFile -ApiBase (Get-EnvValueFromFile -FilePath $EnvFile -Key 'RETRIEVAL_RERANKER_API_BASE') -SourceKey 'RETRIEVAL_RERANKER_API_BASE'
        Append-ProviderAllowlistHostFromApiBase -EnvFile $EnvFile -ApiBase (Get-EnvValueFromFile -FilePath $EnvFile -Key 'WRITE_GUARD_LLM_API_BASE') -SourceKey 'WRITE_GUARD_LLM_API_BASE'
        Append-ProviderAllowlistHostFromApiBase -EnvFile $EnvFile -ApiBase (Get-EnvValueFromFile -FilePath $EnvFile -Key 'COMPACT_GIST_LLM_API_BASE') -SourceKey 'COMPACT_GIST_LLM_API_BASE'
        Append-ProviderAllowlistHostFromApiBase -EnvFile $EnvFile -ApiBase (Get-EnvValueFromFile -FilePath $EnvFile -Key 'INTENT_LLM_API_BASE') -SourceKey 'INTENT_LLM_API_BASE'
        Append-ProviderAllowlistHostFromApiBase -EnvFile $EnvFile -ApiBase (Get-EnvValueFromFile -FilePath $EnvFile -Key 'ROUTER_API_BASE') -SourceKey 'ROUTER_API_BASE'
    }
}

function Test-TruthyValue {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    $normalized = $Value.Trim().ToLower()
    return @('1', 'true', 'yes', 'on', 'enabled') -contains $normalized
}

function Test-UnresolvedPlaceholder {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $true
    }

    return (
        $Value.Contains('replace-with-your-key') -or
        $Value.Contains('replace-with-your-embedding-dim') -or
        $Value.Contains('<provider-vector-dim>') -or
        $Value.Contains('<your-router-host>') -or
        $Value.Contains('host.docker.internal:PORT') -or
        $Value.Contains('your-embedding-model-id') -or
        $Value.Contains('your-reranker-model-id') -or
        ($Value -match ':PORT($|/)')
    )
}

function Assert-ProfileExternalSettingsReady {
    param(
        [string]$EnvFile,
        [string]$SelectedProfile
    )

    if ($SelectedProfile -notin @('c', 'd')) {
        return
    }

    $embeddingBackend = (Get-EnvValueFromFile -FilePath $EnvFile -Key 'RETRIEVAL_EMBEDDING_BACKEND').ToLower()
    $rerankerEnabled = Get-EnvValueFromFile -FilePath $EnvFile -Key 'RETRIEVAL_RERANKER_ENABLED'
    $requiredKeys = New-Object System.Collections.Generic.List[string]

    switch ($embeddingBackend) {
        'router' {
            $requiredKeys.Add('ROUTER_API_BASE')
            $requiredKeys.Add('ROUTER_API_KEY')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_MODEL')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_DIM')
        }
        'api' {
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_API_BASE')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_API_KEY')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_MODEL')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_DIM')
        }
        'openai' {
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_API_BASE')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_API_KEY')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_MODEL')
            $requiredKeys.Add('RETRIEVAL_EMBEDDING_DIM')
        }
        'hash' { }
        'none' { }
        default {
            if (-not [string]::IsNullOrWhiteSpace($embeddingBackend)) {
                $requiredKeys.Add('RETRIEVAL_EMBEDDING_API_BASE')
                $requiredKeys.Add('RETRIEVAL_EMBEDDING_API_KEY')
                $requiredKeys.Add('RETRIEVAL_EMBEDDING_MODEL')
                $requiredKeys.Add('RETRIEVAL_EMBEDDING_DIM')
            }
        }
    }

    if (Test-TruthyValue -Value $rerankerEnabled) {
        $requiredKeys.Add('RETRIEVAL_RERANKER_API_BASE')
        $requiredKeys.Add('RETRIEVAL_RERANKER_API_KEY')
        $requiredKeys.Add('RETRIEVAL_RERANKER_MODEL')
    }

    $hasIssue = $false
    foreach ($key in $requiredKeys) {
        $value = Get-EnvValueFromFile -FilePath $EnvFile -Key $key
        if ([string]::IsNullOrWhiteSpace($value)) {
            Write-Error "[profile-check] Missing required value for $key ($SelectedProfile)"
            $hasIssue = $true
            continue
        }
        if (Test-UnresolvedPlaceholder -Value $value) {
            Write-Error "[profile-check] Unresolved placeholder for $key ($SelectedProfile): $value"
            $hasIssue = $true
        }
    }

    if ($hasIssue) {
        throw "Profile $SelectedProfile has unresolved external settings in $EnvFile"
    }
}

function Get-ResolvedEnvValue {
    param(
        [string]$EnvFile,
        [string]$Key,
        [string]$DefaultValue = ''
    )

    $runtimeValue = [System.Environment]::GetEnvironmentVariable($Key)
    if (-not [string]::IsNullOrWhiteSpace($runtimeValue)) {
        return $runtimeValue
    }

    $fileValue = Get-EnvValueFromFile -FilePath $EnvFile -Key $Key
    if (-not [string]::IsNullOrWhiteSpace($fileValue)) {
        return $fileValue
    }

    return $DefaultValue
}

function Get-ComposeConfigText {
    param(
        [string]$ComposeProjectName = '',
        [string]$EnvFile = ''
    )

    $previousComposeProjectName = $env:COMPOSE_PROJECT_NAME
    $effectiveComposeArgs = @()

    try {
        if (-not [string]::IsNullOrWhiteSpace($ComposeProjectName)) {
            $env:COMPOSE_PROJECT_NAME = $ComposeProjectName
        }
        if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
            $effectiveComposeArgs += @('--env-file', $EnvFile)
        }
        $effectiveComposeArgs += @('-f', 'docker-compose.yml', 'config')

        if ($script:UseComposePlugin) {
            $composeOutput = & docker compose @effectiveComposeArgs 2>&1
        }
        else {
            $composeOutput = & docker-compose @effectiveComposeArgs 2>&1
        }
    }
    finally {
        if ([string]::IsNullOrWhiteSpace($previousComposeProjectName)) {
            Remove-Item Env:COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
        }
        else {
            $env:COMPOSE_PROJECT_NAME = $previousComposeProjectName
        }
    }

    $detail = ($composeOutput | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose config failed: $($effectiveComposeArgs -join ' ')`n$($detail.Trim())"
    }

    return $detail
}

function Normalize-ComposeScalar {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ''
    }

    return $Value.Trim().Trim([char[]]@([char]39, [char]34))
}

function Get-BindSourceFromVolumeShorthand {
    param([string]$RawEntry)

    if ([string]::IsNullOrWhiteSpace($RawEntry)) {
        return ''
    }

    $candidate = $RawEntry.Trim()
    foreach ($targetMarker in @(':/app/data:', ':/app/data')) {
        $markerIndex = $candidate.LastIndexOf($targetMarker, [System.StringComparison]::Ordinal)
        if ($markerIndex -gt 0) {
            return $candidate.Substring(0, $markerIndex)
        }
    }

    return ''
}

function Get-BackendDataBindMountSourcesFromComposeConfig {
    param(
        [string]$ComposeProjectName = '',
        [string]$EnvFile = ''
    )

    $configText = Get-ComposeConfigText -ComposeProjectName $ComposeProjectName -EnvFile $EnvFile
    $lines = $configText -split "`r?`n"
    $sources = New-Object System.Collections.Generic.List[string]
    $inBackend = $false
    $inVolumes = $false
    $entryType = ''
    $entrySource = ''
    $entryTarget = ''

    foreach ($line in $lines) {
        if (-not $inBackend) {
            if ($line -match '^\s{2}backend:\s*$') {
                $inBackend = $true
            }
            continue
        }

        if ($line -match '^\s{2}[A-Za-z0-9_-]+:\s*$') {
            if (
                $entryTarget -eq '/app/data' -and
                $entryType -eq 'bind' -and
                -not [string]::IsNullOrWhiteSpace($entrySource)
            ) {
                [void]$sources.Add($entrySource)
            }
            break
        }

        if (-not $inVolumes) {
            if ($line -match '^\s{4}volumes:\s*$') {
                $inVolumes = $true
            }
            continue
        }

        if ($line -match '^\s{4}[A-Za-z0-9_-]+:\s*$') {
            if (
                $entryTarget -eq '/app/data' -and
                $entryType -eq 'bind' -and
                -not [string]::IsNullOrWhiteSpace($entrySource)
            ) {
                [void]$sources.Add($entrySource)
            }
            $entryType = ''
            $entrySource = ''
            $entryTarget = ''
            $inVolumes = $false
            continue
        }

        if ($line -match '^\s{6}-\s*(.+?)\s*$') {
            if (
                $entryTarget -eq '/app/data' -and
                $entryType -eq 'bind' -and
                -not [string]::IsNullOrWhiteSpace($entrySource)
            ) {
                [void]$sources.Add($entrySource)
            }
            $entryType = ''
            $entrySource = ''
            $entryTarget = ''
            $volumeValue = Normalize-ComposeScalar -Value $Matches[1]
            if ($volumeValue -match '^type:\s*(.+?)\s*$') {
                $entryType = (Normalize-ComposeScalar -Value $Matches[1]).ToLowerInvariant()
            }
            else {
                $bindSource = Get-BindSourceFromVolumeShorthand -RawEntry $volumeValue
                if (-not [string]::IsNullOrWhiteSpace($bindSource)) {
                    $entryType = 'bind'
                    $entrySource = Normalize-ComposeScalar -Value $bindSource
                    $entryTarget = '/app/data'
                }
            }
            continue
        }

        if ($line -match '^\s{8}type:\s*(.+?)\s*$') {
            $entryType = (Normalize-ComposeScalar -Value $Matches[1]).ToLowerInvariant()
            continue
        }

        if ($line -match '^\s{8}source:\s*(.+?)\s*$') {
            $entrySource = Normalize-ComposeScalar -Value $Matches[1]
            continue
        }

        if ($line -match '^\s{8}target:\s*(.+?)\s*$') {
            $entryTarget = Normalize-ComposeScalar -Value $Matches[1]
            continue
        }
    }

    if (
        $entryTarget -eq '/app/data' -and
        $entryType -eq 'bind' -and
        -not [string]::IsNullOrWhiteSpace($entrySource)
    ) {
        [void]$sources.Add($entrySource)
    }
    return $sources
}

function Resolve-ExistingPathForFilesystemProbe {
    param([string]$PathValue)

    $candidate = Normalize-ComposeScalar -Value $PathValue
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        return ''
    }

    $candidate = [System.Environment]::ExpandEnvironmentVariables($candidate)
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $candidate))
    }

    while (-not [string]::IsNullOrWhiteSpace($candidate)) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }

        $parent = Split-Path -Parent $candidate
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $candidate) {
            break
        }
        $candidate = $parent
    }

    return ''
}

function Get-FilesystemProbeSignal {
    param([string]$PathValue)

    $normalizedPath = Normalize-ComposeScalar -Value $PathValue
    if ([string]::IsNullOrWhiteSpace($normalizedPath)) {
        return ''
    }

    $normalizedPath = [System.Environment]::ExpandEnvironmentVariables($normalizedPath)
    if ($normalizedPath -match '^(\\\\|//)') {
        return 'unc'
    }

    $probePath = Resolve-ExistingPathForFilesystemProbe -PathValue $normalizedPath
    if ([string]::IsNullOrWhiteSpace($probePath)) {
        return ''
    }

    $isWindowsHost = $false
    if ($PSVersionTable.PSVersion.Major -lt 6 -or $env:OS -eq 'Windows_NT') {
        $isWindowsHost = $true
    }

    if ($isWindowsHost) {
        try {
            $root = [System.IO.Path]::GetPathRoot($probePath)
            if (-not [string]::IsNullOrWhiteSpace($root)) {
                $driveInfo = [System.IO.DriveInfo]::new($root)
                if ($driveInfo.DriveType -eq [System.IO.DriveType]::Network) {
                    return 'network'
                }
            }
        }
        catch {
        }

        if ($probePath -match '^([A-Za-z]):') {
            $driveName = $Matches[1]
            $psDrive = Get-PSDrive -Name $driveName -PSProvider FileSystem -ErrorAction SilentlyContinue
            if ($psDrive -and -not [string]::IsNullOrWhiteSpace($psDrive.DisplayRoot)) {
                return 'network'
            }
        }

        return ''
    }

    try {
        $bsdStat = & stat -f %T $probePath 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($bsdStat)) {
            return ($bsdStat | Out-String).Trim()
        }
    }
    catch {
    }

    try {
        $gnuStat = & stat -f -L -c %T $probePath 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($gnuStat)) {
            return ($gnuStat | Out-String).Trim()
        }
    }
    catch {
    }

    return ''
}

function Test-NetworkFilesystemSignal {
    param(
        [string]$SourcePath,
        [string]$FilesystemSignal
    )

    $normalizedPath = Normalize-ComposeScalar -Value $SourcePath
    if ([string]::IsNullOrWhiteSpace($normalizedPath)) {
        return $false
    }

    if ($normalizedPath -match '^(\\\\|//)') {
        return $true
    }

    $normalizedSignal = Normalize-ComposeScalar -Value $FilesystemSignal
    if ([string]::IsNullOrWhiteSpace($normalizedSignal)) {
        return $false
    }

    $normalizedSignal = $normalizedSignal.ToLowerInvariant()
    if ($normalizedSignal -eq 'network') {
        return $true
    }

    return ($normalizedSignal -match '(?<![a-z])(nfs|nfs4|cifs|smb|smbfs|sshfs|fuse\.sshfs|webdav|davfs|ceph|glusterfs)(?![a-z])')
}

function Assert-BackendDataBindMountWalSafety {
    param(
        [string]$ComposeProjectName,
        [string]$EnvFile
    )

    $walEnabledRaw = Get-ResolvedEnvValue -EnvFile $EnvFile -Key 'MEMORY_PALACE_DOCKER_WAL_ENABLED' -DefaultValue 'true'
    $journalModeRaw = Get-ResolvedEnvValue -EnvFile $EnvFile -Key 'MEMORY_PALACE_DOCKER_JOURNAL_MODE' -DefaultValue 'wal'
    $walEnabled = Test-TruthyValue -Value $walEnabledRaw
    $requestedJournalMode = if ([string]::IsNullOrWhiteSpace($journalModeRaw)) {
        'wal'
    }
    else {
        $journalModeRaw.Trim().ToLowerInvariant()
    }
    $effectiveJournalMode = if ($walEnabled -and $requestedJournalMode -eq 'wal') {
        'wal'
    }
    else {
        'delete'
    }

    if ($effectiveJournalMode -ne 'wal') {
        return
    }

    $bindSources = Get-BackendDataBindMountSourcesFromComposeConfig -ComposeProjectName $ComposeProjectName -EnvFile $EnvFile
    foreach ($bindSource in $bindSources) {
        $filesystemSignal = Get-FilesystemProbeSignal -PathValue $bindSource
        if (Test-NetworkFilesystemSignal -SourcePath $bindSource -FilesystemSignal $filesystemSignal) {
            throw "[compose-preflight] Refusing to start Memory Palace with WAL enabled on backend /app/data bind mount '$bindSource' (signal=$filesystemSignal). Use a Docker named volume instead, or disable WAL with MEMORY_PALACE_DOCKER_WAL_ENABLED=false and MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete before retrying."
        }
    }
}

function Invoke-Compose {
    param(
        [string[]]$ComposeArgs,
        [string]$ComposeProjectName = '',
        [string]$EnvFile = ''
    )

    $composeOutput = @()
    $previousComposeProjectName = $env:COMPOSE_PROJECT_NAME
    $effectiveComposeArgs = @()
    try {
        if (-not [string]::IsNullOrWhiteSpace($ComposeProjectName)) {
            $env:COMPOSE_PROJECT_NAME = $ComposeProjectName
        }
        if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
            $effectiveComposeArgs += @('--env-file', $EnvFile)
        }
        $effectiveComposeArgs += $ComposeArgs

        if ($script:UseComposePlugin) {
            $composeOutput = & docker compose @effectiveComposeArgs 2>&1
        }
        else {
            $composeOutput = & docker-compose @effectiveComposeArgs 2>&1
        }
    }
    finally {
        if ([string]::IsNullOrWhiteSpace($previousComposeProjectName)) {
            Remove-Item Env:COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
        }
        else {
            $env:COMPOSE_PROJECT_NAME = $previousComposeProjectName
        }
    }

    if ($composeOutput.Count -gt 0) {
        $composeOutput | ForEach-Object { Write-Output $_ }
    }

    if ($LASTEXITCODE -ne 0) {
        $detail = ($composeOutput | Out-String).Trim()
        throw "docker compose command failed: $($effectiveComposeArgs -join ' ')`n$detail"
    }
}

function Test-ComposeRetryableError {
    param([string]$Message)

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return $false
    }

    $patterns = @(
        'No such container',
        'dependency failed to start',
        'toomanyrequests',
        'TLS handshake timeout',
        'connection reset by peer',
        'i/o timeout',
        'context canceled',
        'EOF'
    )

    foreach ($pattern in $patterns) {
        if ($Message -like "*$pattern*") {
            return $true
        }
    }

    return $false
}

function Invoke-ComposeWithRetry {
    param(
        [string[]]$ComposeArgs,
        [string]$ComposeProjectName = '',
        [int]$MaxAttempts = 3,
        [string]$EnvFile = ''
    )

    $attempt = 0
    while ($attempt -lt $MaxAttempts) {
        $attempt += 1
        try {
            Invoke-Compose -ComposeArgs $ComposeArgs -ComposeProjectName $ComposeProjectName -EnvFile $EnvFile
            return
        }
        catch {
            $detail = $_.Exception.Message
            $retryable = Test-ComposeRetryableError -Message $detail
            if ($attempt -ge $MaxAttempts -or -not $retryable) {
                throw
            }

            $sleepSeconds = 2 * $attempt
            Write-Warning "[compose-retry] transient compose up failure ($attempt/$MaxAttempts), retrying in ${sleepSeconds}s."
            Start-Sleep -Seconds $sleepSeconds
            try {
                Invoke-Compose -ComposeArgs @('-f', 'docker-compose.yml', 'down', '--remove-orphans') -ComposeProjectName $ComposeProjectName -EnvFile $EnvFile
            }
            catch {
                # Keep retry path best-effort; next attempt will surface a hard failure.
            }
        }
    }
}

function Get-HttpStatusCode {
    param([string]$Url)

    $NoProxyValue = Get-EffectiveNoProxyValue
    $previousNoProxyUpper = $env:NO_PROXY
    $previousNoProxyLower = $env:no_proxy
    $hadNoProxyUpper = Test-Path Env:NO_PROXY
    $hadNoProxyLower = Test-Path Env:no_proxy

    try {
        $env:NO_PROXY = $NoProxyValue
        $env:no_proxy = $NoProxyValue
        $code = & curl.exe --noproxy $NoProxyValue -sS -o NUL -w '%{http_code}' $Url 2>$null
        if ([string]::IsNullOrWhiteSpace($code)) {
            return 0
        }
        return [int]$code
    }
    catch {
        return 0
    }
    finally {
        if ($hadNoProxyUpper) {
            $env:NO_PROXY = $previousNoProxyUpper
        }
        else {
            Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue
        }
        if ($hadNoProxyLower) {
            $env:no_proxy = $previousNoProxyLower
        }
        else {
            Remove-Item Env:no_proxy -ErrorAction SilentlyContinue
        }
    }
}

function Get-EffectiveNoProxyValue {
    $entries = New-Object System.Collections.Generic.List[string]

    foreach ($rawGroup in @($env:NO_PROXY, $env:no_proxy, '127.0.0.1', 'localhost', '::1', 'host.docker.internal')) {
        foreach ($rawEntry in [string]$rawGroup -split ',') {
            $entry = $rawEntry.Trim()
            if ([string]::IsNullOrWhiteSpace($entry)) {
                continue
            }
            if (-not $entries.Contains($entry)) {
                [void]$entries.Add($entry)
            }
        }
    }

    return ($entries -join ',')
}

function Wait-DeploymentReady {
    param(
        [int]$FrontendPort,
        [int]$BackendPort,
        [int]$Attempts = 30,
        [int]$SleepSeconds = 2
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $backendCode = Get-HttpStatusCode -Url "http://127.0.0.1:$BackendPort/health"
        $frontendCode = Get-HttpStatusCode -Url "http://127.0.0.1:$FrontendPort/"
        $sseCode = Get-HttpStatusCode -Url "http://127.0.0.1:$FrontendPort/sse"
        if ($backendCode -eq 200 -and $frontendCode -eq 200 -and @('200', '401') -contains "$sseCode") {
            return $true
        }
        Start-Sleep -Seconds $SleepSeconds
    }

    return $false
}

function Test-ComposeProjectHasAnyContainer {
    param(
        [string]$ComposeProjectName,
        [string]$Service
    )

    $containers = docker ps -a `
        --filter "label=com.docker.compose.project=$ComposeProjectName" `
        --filter "label=com.docker.compose.service=$Service" `
        --format '{{.Names}}' 2>$null | Select-Object -First 1

    return (-not [string]::IsNullOrWhiteSpace(($containers | Out-String).Trim()))
}

function Get-ComposePublishedPort {
    param(
        [string]$ComposeProjectName,
        [string]$EnvFile,
        [string]$Service,
        [int]$TargetPort,
        [int]$FallbackPort,
        [int]$Attempts = 10
    )

    $previousComposeProjectName = $env:COMPOSE_PROJECT_NAME
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $portsOutput = docker ps `
                --filter "label=com.docker.compose.project=$ComposeProjectName" `
                --filter "label=com.docker.compose.service=$Service" `
                --format '{{.Ports}}' 2>$null | Select-Object -First 1
            if ($LASTEXITCODE -eq 0 -and $portsOutput) {
                $portsLine = $portsOutput.ToString().Trim()
                if ($portsLine -match ":(\d+)->$TargetPort/tcp") {
                    return [int]$Matches[1]
                }
            }

            $containerName = docker ps `
                --filter "label=com.docker.compose.project=$ComposeProjectName" `
                --filter "label=com.docker.compose.service=$Service" `
                --format '{{.Names}}' 2>$null | Select-Object -First 1
            if ($LASTEXITCODE -eq 0 -and $containerName) {
                $mappedPort = docker port $containerName $TargetPort 2>$null | Select-Object -First 1
                if ($LASTEXITCODE -eq 0 -and $mappedPort) {
                    $line = $mappedPort.ToString().Trim()
                    if ($line -match ':(\d+)\s*$') {
                        return [int]$Matches[1]
                    }
                }
            }

            if (-not [string]::IsNullOrWhiteSpace($ComposeProjectName)) {
                $env:COMPOSE_PROJECT_NAME = $ComposeProjectName
            }

            $portArgs = @()
            if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
                $portArgs += @('--env-file', $EnvFile)
            }
            $portArgs += @('-f', 'docker-compose.yml', 'port', $Service, "$TargetPort")

            if ($script:UseComposePlugin) {
                $output = & docker compose @portArgs 2>$null
            }
            else {
                $output = & docker-compose @portArgs 2>$null
            }

            if ($LASTEXITCODE -eq 0 -and $output) {
                $line = ($output | Select-Object -First 1).ToString().Trim()
                if ($line -match ':(\d+)\s*$') {
                    return [int]$Matches[1]
                }
            }
        }
        catch {
            # Fall back to the planned port when compose cannot report a binding.
        }
        finally {
            if ([string]::IsNullOrWhiteSpace($previousComposeProjectName)) {
                Remove-Item Env:COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
            }
            else {
                $env:COMPOSE_PROJECT_NAME = $previousComposeProjectName
            }
        }

        if ($attempt -lt $Attempts) {
            Start-Sleep -Seconds 1
        }
    }

    return $FallbackPort
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$profileLower = Assert-ValidProfile -ProfileName $Profile

if (-not $PSBoundParameters.ContainsKey('FrontendPort')) {
    if ($env:MEMORY_PALACE_FRONTEND_PORT) {
        $FrontendPort = $env:MEMORY_PALACE_FRONTEND_PORT
    }
    elseif ($env:NOCTURNE_FRONTEND_PORT) {
        $FrontendPort = $env:NOCTURNE_FRONTEND_PORT
    }
    else {
        $FrontendPort = '3000'
    }
}

if (-not $PSBoundParameters.ContainsKey('BackendPort')) {
    if ($env:MEMORY_PALACE_BACKEND_PORT) {
        $BackendPort = $env:MEMORY_PALACE_BACKEND_PORT
    }
    elseif ($env:NOCTURNE_BACKEND_PORT) {
        $BackendPort = $env:NOCTURNE_BACKEND_PORT
    }
    else {
        $BackendPort = '18000'
    }
}

$FrontendPort = Resolve-PortValue -Value $FrontendPort -Name 'FrontendPort'
$BackendPort = Resolve-PortValue -Value $BackendPort -Name 'BackendPort'

Assert-ValidPort -Port $FrontendPort -Name 'FrontendPort'
Assert-ValidPort -Port $BackendPort -Name 'BackendPort'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker is not installed or not in PATH"
    exit 1
}

$script:UseComposePlugin = $false
try {
    docker compose version | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $script:UseComposePlugin = $true
    }
}
catch {
    $script:UseComposePlugin = $false
}

if (-not $script:UseComposePlugin -and -not (Get-Command docker-compose -ErrorAction SilentlyContinue)) {
    Write-Error "Neither 'docker compose' nor 'docker-compose' is available"
    exit 1
}

$script:DeploymentLockDir = Try-AcquirePathLock -TargetPath (Join-Path ([System.IO.Path]::GetTempPath()) "memory-palace-deploy-locks/$(Get-DefaultComposeProjectName)")
if (-not $script:DeploymentLockDir) {
    throw "[deploy-lock] another docker_one_click deployment is already running for this checkout; wait for it to finish before retrying."
}

$script:PreviousDockerEnvFile = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_DOCKER_ENV_FILE')
$envFile = $script:PreviousDockerEnvFile
if ([string]::IsNullOrWhiteSpace($envFile)) {
    $envFile = Join-Path ([System.IO.Path]::GetTempPath()) ("memory-palace-docker-env-$profileLower-$([System.Guid]::NewGuid().ToString('N')).env")
    $script:GeneratedDockerEnvFile = $envFile
}
$envFile = Resolve-StableEnvFilePath -Path $envFile
$env:MEMORY_PALACE_DOCKER_ENV_FILE = $envFile
Write-Host "[env-file] using $envFile"
if ($AllowRuntimeEnvInjection.IsPresent -and $profileLower -notin @('c', 'd')) {
    Write-Error "-AllowRuntimeEnvInjection is only supported for profile c/d; profile $profileLower keeps its documented defaults."
    exit 1
}
$previousAllowUnresolvedProfilePlaceholders = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS')
try {
    if ($AllowRuntimeEnvInjection.IsPresent -and $profileLower -in @('c', 'd')) {
        $env:MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS = '1'
    }
    & (Join-Path $scriptDir 'apply_profile.ps1') -Platform docker -Profile $profileLower -Target $envFile
}
finally {
    if ([string]::IsNullOrWhiteSpace($previousAllowUnresolvedProfilePlaceholders)) {
        Remove-Item Env:MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS -ErrorAction SilentlyContinue
    }
    else {
        $env:MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS = $previousAllowUnresolvedProfilePlaceholders
    }
}
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if ($AllowRuntimeEnvInjection.IsPresent) {
    Apply-ProfileRuntimeOverrides -EnvFile $envFile -SelectedProfile $profileLower
}
else {
    Write-Host "[override] runtime env injection disabled by default; pass -AllowRuntimeEnvInjection to opt in."
}
Assert-ProfileExternalSettingsReady -EnvFile $envFile -SelectedProfile $profileLower

Push-Location $projectRoot
try {
    $composeProjectName = [System.Environment]::GetEnvironmentVariable('COMPOSE_PROJECT_NAME')
    if ([string]::IsNullOrWhiteSpace($composeProjectName)) {
        $composeProjectName = Get-DefaultComposeProjectName
    }
    $localImageNamespace = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_LOCAL_IMAGE_NAMESPACE')
    if ([string]::IsNullOrWhiteSpace($localImageNamespace)) {
        $localImageNamespace = Get-DefaultComposeProjectName
    }
    $backendImage = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_BACKEND_IMAGE')
    if ([string]::IsNullOrWhiteSpace($backendImage)) {
        $backendImage = "$localImageNamespace-backend:latest"
    }
    $frontendImage = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_FRONTEND_IMAGE')
    if ([string]::IsNullOrWhiteSpace($frontendImage)) {
        $frontendImage = "$localImageNamespace-frontend:latest"
    }
    $env:MEMORY_PALACE_BACKEND_IMAGE = $backendImage
    $env:MEMORY_PALACE_FRONTEND_IMAGE = $frontendImage

    if (-not $NoAutoPort) {
        $frontendReservation = Resolve-FreePort -StartPort $FrontendPort
        $script:FrontendPortLockDir = $frontendReservation.LockDir
        $resolvedFrontendPort = [int]$frontendReservation.Port
        $backendReservation = Resolve-FreePort -StartPort $BackendPort -ExcludePort $resolvedFrontendPort
        $script:BackendPortLockDir = $backendReservation.LockDir
        $resolvedBackendPort = [int]$backendReservation.Port

        if ($resolvedFrontendPort -ne $FrontendPort) {
            Write-Host "[port-adjust] frontend $FrontendPort is occupied, switched to $resolvedFrontendPort"
        }
        if ($resolvedBackendPort -ne $BackendPort) {
            Write-Host "[port-adjust] backend $BackendPort is occupied, switched to $resolvedBackendPort"
        }

        $FrontendPort = $resolvedFrontendPort
        $BackendPort = $resolvedBackendPort
    }

    $dataVolume = Resolve-DataVolume
    $snapshotsVolume = Resolve-SnapshotsVolume
    Set-EnvValueInFile -FilePath $envFile -Key 'MEMORY_PALACE_FRONTEND_PORT' -Value "$FrontendPort"
    Set-EnvValueInFile -FilePath $envFile -Key 'MEMORY_PALACE_BACKEND_PORT' -Value "$BackendPort"
    Set-EnvValueInFile -FilePath $envFile -Key 'MEMORY_PALACE_DATA_VOLUME' -Value "$dataVolume"
    Set-EnvValueInFile -FilePath $envFile -Key 'MEMORY_PALACE_SNAPSHOTS_VOLUME' -Value "$snapshotsVolume"
    Set-EnvValueInFile -FilePath $envFile -Key 'NOCTURNE_FRONTEND_PORT' -Value "$FrontendPort"
    Set-EnvValueInFile -FilePath $envFile -Key 'NOCTURNE_BACKEND_PORT' -Value "$BackendPort"
    Set-EnvValueInFile -FilePath $envFile -Key 'NOCTURNE_DATA_VOLUME' -Value "$dataVolume"
    Set-EnvValueInFile -FilePath $envFile -Key 'NOCTURNE_SNAPSHOTS_VOLUME' -Value "$snapshotsVolume"
    $plannedFrontendPort = Get-EnvValueFromFile -FilePath $envFile -Key 'MEMORY_PALACE_FRONTEND_PORT'
    $plannedBackendPort = Get-EnvValueFromFile -FilePath $envFile -Key 'MEMORY_PALACE_BACKEND_PORT'
    if ([string]::IsNullOrWhiteSpace($plannedFrontendPort)) {
        $plannedFrontendPort = "$FrontendPort"
    }
    if ([string]::IsNullOrWhiteSpace($plannedBackendPort)) {
        $plannedBackendPort = "$BackendPort"
    }
    $env:MEMORY_PALACE_FRONTEND_PORT = "$FrontendPort"
    $env:MEMORY_PALACE_BACKEND_PORT = "$BackendPort"
    $env:MEMORY_PALACE_DATA_VOLUME = "$dataVolume"
    $env:MEMORY_PALACE_SNAPSHOTS_VOLUME = "$snapshotsVolume"
    $env:NOCTURNE_FRONTEND_PORT = "$FrontendPort"
    $env:NOCTURNE_BACKEND_PORT = "$BackendPort"
    $env:NOCTURNE_DATA_VOLUME = "$dataVolume"
    $env:NOCTURNE_SNAPSHOTS_VOLUME = "$snapshotsVolume"
    Assert-BackendDataBindMountWalSafety -ComposeProjectName $composeProjectName -EnvFile $envFile

    try {
        Invoke-Compose -ComposeArgs @('-f', 'docker-compose.yml', 'down', '--remove-orphans') -ComposeProjectName $composeProjectName -EnvFile $envFile
    }
    catch {
        throw "[compose-down] pre-cleanup failed; aborting to match fail-closed deployment behavior. detail=$($_.Exception.Message)"
    }

    $composeUpArgs = @('-f', 'docker-compose.yml', 'up', '-d', '--wait', '--wait-timeout', '120', '--force-recreate', '--remove-orphans')
    if (-not $NoBuild) {
        $composeUpArgs = @('-f', 'docker-compose.yml', 'up', '-d', '--build', '--wait', '--wait-timeout', '120', '--force-recreate', '--remove-orphans')
    }
    try {
        Invoke-ComposeWithRetry -ComposeArgs $composeUpArgs -ComposeProjectName $composeProjectName -MaxAttempts 3 -EnvFile $envFile
    }
    catch {
        $hasBackendContainer = Test-ComposeProjectHasAnyContainer -ComposeProjectName $composeProjectName -Service 'backend'
        $hasFrontendContainer = Test-ComposeProjectHasAnyContainer -ComposeProjectName $composeProjectName -Service 'frontend'
        if (-not ($hasBackendContainer -or $hasFrontendContainer)) {
            throw "[compose-up] docker compose failed before creating any service container; skipping readiness probe. detail=$($_.Exception.Message)"
        }
        Write-Warning "[compose-up] docker compose returned non-zero; probing backend/frontend readiness via proxied /sse..."
        $probeFrontendPort = Get-ComposePublishedPort -ComposeProjectName $composeProjectName -EnvFile $envFile -Service 'frontend' -TargetPort 8080 -FallbackPort ([int]$plannedFrontendPort)
        $probeBackendPort = Get-ComposePublishedPort -ComposeProjectName $composeProjectName -EnvFile $envFile -Service 'backend' -TargetPort 8000 -FallbackPort ([int]$plannedBackendPort)
        if (-not (Wait-DeploymentReady -FrontendPort $probeFrontendPort -BackendPort $probeBackendPort)) {
            throw
        }
        Write-Warning "[compose-up] services became ready after compose reported failure; continuing."
    }

    $reportedFrontendPort = Get-ComposePublishedPort -ComposeProjectName $composeProjectName -EnvFile $envFile -Service 'frontend' -TargetPort 8080 -FallbackPort ([int]$plannedFrontendPort)
    $reportedBackendPort = Get-ComposePublishedPort -ComposeProjectName $composeProjectName -EnvFile $envFile -Service 'backend' -TargetPort 8000 -FallbackPort ([int]$plannedBackendPort)
}
finally {
    Release-PathLock -LockDir $script:DeploymentLockDir
    Release-PathLock -LockDir $script:FrontendPortLockDir
    Release-PathLock -LockDir $script:BackendPortLockDir
    if ([string]::IsNullOrWhiteSpace($script:PreviousDockerEnvFile)) {
        Remove-Item Env:MEMORY_PALACE_DOCKER_ENV_FILE -ErrorAction SilentlyContinue
    }
    else {
        $env:MEMORY_PALACE_DOCKER_ENV_FILE = $script:PreviousDockerEnvFile
    }
    if (-not [string]::IsNullOrWhiteSpace($script:GeneratedDockerEnvFile) -and (Test-Path $script:GeneratedDockerEnvFile)) {
        Remove-Item $script:GeneratedDockerEnvFile -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}

Write-Host ""
Write-Host "Memory Palace is starting with docker profile $profileLower."
Write-Host "Frontend: http://localhost:$reportedFrontendPort"
Write-Host "Backend API: http://localhost:$reportedBackendPort"
Write-Host "SSE Endpoint: http://localhost:$reportedFrontendPort/sse"
Write-Host "Health: http://localhost:$reportedBackendPort/health"
Write-Host "Compose project: $composeProjectName"
