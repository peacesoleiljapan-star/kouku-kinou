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

$repoRoot = (Resolve-Path -LiteralPath $RepoPath).Path
$syncScript = Join-Path $repoRoot 'git_auto_sync.ps1'
$watchScript = Join-Path $repoRoot 'watch_github_auto_sync.ps1'

foreach ($requiredFile in @($syncScript, $watchScript)) {
    if (-not (Test-Path -LiteralPath $requiredFile)) {
        throw ('Required file was not found: ' + $requiredFile)
    }
}

$safeDirectory = $repoRoot -replace '\\', '/'
$existingSafeDirectories = @(git config --global --get-all safe.directory 2>$null)
if ($existingSafeDirectories -notcontains $safeDirectory) {
    git config --global --add safe.directory $safeDirectory | Out-Null
}

$principalUser = if ([string]::IsNullOrWhiteSpace($env:USERDOMAIN)) {
    $env:USERNAME
}
else {
    $env:USERDOMAIN + '\\' + $env:USERNAME
}

$syncArgument = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -RepoPath "{1}" -Quiet' -f $syncScript, $repoRoot
$watchArgument = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -RepoPath "{1}" -DebounceSeconds {2}' -f $watchScript, $repoRoot, $DebounceSeconds

$syncAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $syncArgument
$watchAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $watchArgument

$syncTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes $SyncIntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$watchTrigger = New-ScheduledTaskTrigger -AtLogOn

$syncSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$watchSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $principalUser -LogonType InteractiveToken -RunLevel Limited

$syncTaskName = 'KoukuKinou-GitHub-Sync'
$watchTaskName = 'KoukuKinou-GitHub-Watch'

Register-ScheduledTask -TaskName $syncTaskName -Action $syncAction -Trigger $syncTrigger -Settings $syncSettings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $watchTaskName -Action $watchAction -Trigger $watchTrigger -Settings $watchSettings -Principal $principal -Force | Out-Null

Start-ScheduledTask -TaskName $watchTaskName

Write-Host ('Configured safe.directory: ' + $safeDirectory)
Write-Host ('Created scheduled task: ' + $syncTaskName)
Write-Host ('Created scheduled task: ' + $watchTaskName)
Write-Host ('Sync interval: every ' + $SyncIntervalMinutes + ' minute(s)')
Write-Host ('Watch debounce: ' + $DebounceSeconds + ' second(s)')
Write-Host 'To push immediately, run sync_to_github_now.cmd.'