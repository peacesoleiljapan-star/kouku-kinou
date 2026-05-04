param(
    [string]$PythonPath = $env:KOUKU_KINOU_PYTHON
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath((Split-Path -Parent $MyInvocation.MyCommand.Path))

if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    throw 'git.exe was not found. Install Git for Windows first.'
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $PythonPath = $python.Source
    }
}

if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Python was not found. Run this script with -PythonPath C:\path\to\python.exe or set KOUKU_KINOU_PYTHON first.'
}

$gitConfigPath = Join-Path $HOME '.gitconfig'
$safeDirectory = $repoRoot -replace '\\', '/'
$safeDirectoryLine = 'directory = ' + $safeDirectory
if (-not ((Test-Path -LiteralPath $gitConfigPath) -and (Select-String -Path $gitConfigPath -SimpleMatch $safeDirectoryLine -Quiet))) {
    git config --global --add safe.directory $safeDirectory | Out-Null
}

setx KOUKU_KINOU_PYTHON $PythonPath | Out-Null

Write-Host ('Configured safe.directory: ' + $safeDirectory)
Write-Host ('Configured KOUKU_KINOU_PYTHON: ' + $PythonPath)
Write-Host 'Next steps:'
Write-Host '1. Open this shared folder in VS Code.'
Write-Host '2. Run git pull before editing.'
Write-Host '3. Run build_package.ps1 when you need new package output.'
Write-Host '4. Run setup_github_auto_sync.cmd once if you want automatic GitHub uploads.'
