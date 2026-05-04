param(
    [string]$RepoPath = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [int]$SyncIntervalMinutes = 15,
    [int]$DebounceSeconds = 60
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($SyncIntervalMinutes -lt 1) {
    throw 'SyncIntervalMinutes must be 1 or greater.'
}

if ($DebounceSeconds -lt 5) {
    throw 'DebounceSeconds must be 5 or greater.'
}

if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    throw 'git.exe was not found. Install Git for Windows first.'
}

if (-not (Get-Command powershell.exe -ErrorAction SilentlyContinue)) {
    throw 'powershell.exe was not found.'
}

$repoRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RepoPath)
$syncScript = Join-Path $repoRoot 'git_auto_sync.ps1'
$watchScript = Join-Path $repoRoot 'watch_github_auto_sync.ps1'
$gitConfigPath = Join-Path $HOME '.gitconfig'
$startupFolder = [Environment]::GetFolderPath('Startup')
$startupLauncherPath = Join-Path $startupFolder 'KoukuKinou GitHub Auto Sync.lnk'
$legacyStartupLauncherPath = Join-Path $startupFolder 'KoukuKinou GitHub Auto Sync.cmd'

foreach ($requiredFile in @($syncScript, $watchScript)) {
    if (-not (Test-Path -LiteralPath $requiredFile)) {
        throw ('Required file was not found: ' + $requiredFile)
    }
}

$safeDirectory = $repoRoot -replace '\\', '/'
$safeDirectoryLine = 'directory = ' + $safeDirectory
if (-not ((Test-Path -LiteralPath $gitConfigPath) -and (Select-String -Path $gitConfigPath -SimpleMatch $safeDirectoryLine -Quiet))) {
    git config --global --add safe.directory $safeDirectory | Out-Null
}

if (Test-Path -LiteralPath $legacyStartupLauncherPath) {
    Remove-Item -LiteralPath $legacyStartupLauncherPath -Force
}

$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$startupShell = New-Object -ComObject WScript.Shell
$shortcut = $startupShell.CreateShortcut($startupLauncherPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -RepoPath "{1}" -DebounceSeconds {2} -SyncIntervalMinutes {3}' -f $watchScript, $repoRoot, $DebounceSeconds, $SyncIntervalMinutes
$shortcut.WorkingDirectory = $repoRoot
$shortcut.IconLocation = $powershellPath + ',0'
$shortcut.WindowStyle = 7
$shortcut.Save()

Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile',
    '-WindowStyle', 'Hidden',
    '-ExecutionPolicy', 'Bypass',
    '-File', $watchScript,
    '-RepoPath', $repoRoot,
    '-DebounceSeconds', $DebounceSeconds,
    '-SyncIntervalMinutes', $SyncIntervalMinutes
) -WindowStyle Hidden

Write-Host ('Configured safe.directory: ' + $safeDirectory)
Write-Host ('Created startup launcher: ' + $startupLauncherPath)
Write-Host ('Sync interval: every ' + $SyncIntervalMinutes + ' minute(s)')
Write-Host ('Watch debounce: ' + $DebounceSeconds + ' second(s)')
Write-Host 'The background watcher was started for this sign-in session.'
Write-Host 'To push immediately, run sync_to_github_now.cmd.'