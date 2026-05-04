param(
    [string]$RepoPath = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [int]$DebounceSeconds = 60
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($DebounceSeconds -lt 5) {
    throw 'DebounceSeconds must be 5 or greater.'
}

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncScript = Join-Path $scriptRoot 'git_auto_sync.ps1'

if (-not (Test-Path -LiteralPath $syncScript)) {
    throw 'git_auto_sync.ps1 was not found.'
}

function Test-IgnoredPath {
    param(
        [AllowNull()]
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $true
    }

    $normalizedPath = $Path.Replace('/', '\')
    $ignoredFragments = @(
        '\.git\',
        '\build\',
        '\package\',
        '\data\',
        '\__pycache__\'
    )

    foreach ($fragment in $ignoredFragments) {
        if ($normalizedPath -like ('*' + $fragment + '*')) {
            return $true
        }
    }

    return (
        $normalizedPath -like '*.tmp' -or
        $normalizedPath -like '*.swp' -or
        $normalizedPath -like '*~'
    )
}

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $resolvedRepoPath
$watcher.IncludeSubdirectories = $true
$watcher.InternalBufferSize = 32768
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, DirectoryName, LastWrite, CreationTime'

$sourcePrefix = 'KoukuKinouGitWatch'
$subscriptions = @(
    (Register-ObjectEvent -InputObject $watcher -EventName Changed -SourceIdentifier ($sourcePrefix + 'Changed')),
    (Register-ObjectEvent -InputObject $watcher -EventName Created -SourceIdentifier ($sourcePrefix + 'Created')),
    (Register-ObjectEvent -InputObject $watcher -EventName Deleted -SourceIdentifier ($sourcePrefix + 'Deleted')),
    (Register-ObjectEvent -InputObject $watcher -EventName Renamed -SourceIdentifier ($sourcePrefix + 'Renamed'))
)

$watcher.EnableRaisingEvents = $true
$syncDeadlineUtc = $null

try {
    while ($true) {
        $event = Wait-Event -Timeout 5
        if ($event) {
            $fullPath = $null
            if ($event.SourceEventArgs -and $event.SourceEventArgs.FullPath) {
                $fullPath = $event.SourceEventArgs.FullPath
            }

            if (-not (Test-IgnoredPath -Path $fullPath)) {
                $syncDeadlineUtc = [DateTime]::UtcNow.AddSeconds($DebounceSeconds)
            }

            Remove-Event -EventIdentifier $event.EventIdentifier
        }

        if ($syncDeadlineUtc -and [DateTime]::UtcNow -ge $syncDeadlineUtc) {
            $syncDeadlineUtc = $null
            & powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $syncScript -RepoPath $resolvedRepoPath -Quiet
        }
    }
}
finally {
    foreach ($subscription in $subscriptions) {
        Unregister-Event -SubscriptionId $subscription.Id -ErrorAction SilentlyContinue
        Remove-Job -Id $subscription.Id -Force -ErrorAction SilentlyContinue
    }

    $watcher.Dispose()
}