param(
    [string]$RepoPath = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [int]$DebounceSeconds = 60,
    [int]$SyncIntervalMinutes = 15
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($DebounceSeconds -lt 5) {
    throw 'DebounceSeconds must be 5 or greater.'
}

if ($SyncIntervalMinutes -lt 1) {
    throw 'SyncIntervalMinutes must be 1 or greater.'
}

$resolvedRepoPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RepoPath)
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncScript = Join-Path $scriptRoot 'git_auto_sync.ps1'
$mutex = New-Object System.Threading.Mutex($false, 'Global\KoukuKinouGitWatch')
$hasLock = $false

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
$nextPeriodicSyncUtc = [DateTime]::UtcNow

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        exit 0
    }

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
            $nextPeriodicSyncUtc = [DateTime]::UtcNow.AddMinutes($SyncIntervalMinutes)
        }

        if ([DateTime]::UtcNow -ge $nextPeriodicSyncUtc) {
            & powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $syncScript -RepoPath $resolvedRepoPath -Quiet
            $nextPeriodicSyncUtc = [DateTime]::UtcNow.AddMinutes($SyncIntervalMinutes)
        }
    }
}
finally {
    foreach ($subscription in $subscriptions) {
        Unregister-Event -SubscriptionId $subscription.Id -ErrorAction SilentlyContinue
        Remove-Job -Id $subscription.Id -Force -ErrorAction SilentlyContinue
    }

    $watcher.Dispose()

    if ($hasLock) {
        $mutex.ReleaseMutex() | Out-Null
    }

    $mutex.Dispose()
}