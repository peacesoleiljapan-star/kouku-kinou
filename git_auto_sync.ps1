param(
    [string]$RepoPath = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$CommitMessage,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-StateRoot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw 'LOCALAPPDATA is not available.'
    }

    $stateRoot = Join-Path $env:LOCALAPPDATA 'kouku-kinou\git-auto-sync'
    if (-not (Test-Path -LiteralPath $stateRoot)) {
        New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    }

    return $stateRoot
}

$stateRoot = Get-StateRoot
$logPath = Join-Path $stateRoot 'git-auto-sync.log'

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [string]$Level = 'INFO'
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = '{0} [{1}] {2}' -f $timestamp, $Level, $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8

    if (-not $Quiet) {
        Write-Host $line
    }
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $output = & git @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $message = ($output | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($message)) {
            $message = 'git command failed without output.'
        }

        throw ('git {0} failed: {1}' -f ($Arguments -join ' '), $message)
    }

    return @($output)
}

$mutex = New-Object System.Threading.Mutex($false, 'Global\KoukuKinouGitAutoSync')
$hasLock = $false

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-Log -Message 'Another sync is already running. Skipping this run.' -Level 'WARN'
        exit 0
    }

    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        throw 'git.exe was not found. Install Git for Windows first.'
    }

    $resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path

    Push-Location $resolvedRepoPath
    try {
        $insideWorkTree = ((Invoke-Git -Arguments @('rev-parse', '--is-inside-work-tree')) | Out-String).Trim()
        if ($insideWorkTree -ne 'true') {
            throw ('{0} is not a Git working tree.' -f $resolvedRepoPath)
        }

        $branchName = ((Invoke-Git -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')) | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($branchName)) {
            throw 'Failed to determine the current branch name.'
        }

        $statusLines = @(Invoke-Git -Arguments @('status', '--porcelain'))
        if ($statusLines.Count -eq 0 -or [string]::IsNullOrWhiteSpace(($statusLines | Out-String).Trim())) {
            Write-Log -Message 'No local file changes found. Nothing to sync.'
            exit 0
        }

        Write-Log -Message ('Pulling latest changes for branch ' + $branchName + '.')
        Invoke-Git -Arguments @('pull', '--rebase', '--autostash', 'origin', $branchName) | Out-Null

        Write-Log -Message 'Staging local file changes.'
        Invoke-Git -Arguments @('add', '-A') | Out-Null

        & git diff --cached --quiet --exit-code
        $cachedExitCode = $LASTEXITCODE
        if ($cachedExitCode -eq 0) {
            Write-Log -Message 'Only ignored files changed. Nothing to commit.'
            exit 0
        }

        if ($cachedExitCode -ne 1) {
            throw 'git diff --cached --quiet failed.'
        }

        if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
            $CommitMessage = 'Auto sync ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        }

        Write-Log -Message ('Creating commit: ' + $CommitMessage)
        Invoke-Git -Arguments @('commit', '-m', $CommitMessage) | Out-Null

        Write-Log -Message 'Pushing to GitHub.'
        Invoke-Git -Arguments @('push', 'origin', ('HEAD:' + $branchName)) | Out-Null

        $headCommit = ((Invoke-Git -Arguments @('rev-parse', '--short', 'HEAD')) | Out-String).Trim()
        Write-Log -Message ('Sync completed successfully at commit ' + $headCommit + '.')
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Log -Message $_.Exception.Message -Level 'ERROR'
    exit 1
}
finally {
    if ($hasLock) {
        $mutex.ReleaseMutex() | Out-Null
    }

    $mutex.Dispose()
}