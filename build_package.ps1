param(
    [switch]$SkipDocs
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildRoot = Join-Path $projectRoot 'build'
$packageRoot = Join-Path $projectRoot 'package'
$docsScript = Join-Path $projectRoot 'build_docs.py'

function Resolve-PythonCommand {
    $configuredPython = $env:KOUKU_KINOU_PYTHON
    $candidates = @(
        $configuredPython,
        (Join-Path $projectRoot '.venv\Scripts\python.exe')
    )

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return @($candidate)
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, '-3')
    }

    throw 'Python was not found. Set KOUKU_KINOU_PYTHON to a local python.exe, activate a local venv, or create a .venv before running build_package.cmd.'
}

function Resolve-EdgePath {
    $candidates = @(
        'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $edge = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($edge) {
        return $edge.Source
    }

    throw 'Microsoft Edge was not found. Install Edge to regenerate PDF files.'
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$WorkingDirectory = $projectRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw ("Command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($Arguments -join ' '))
        }
    }
    finally {
        Pop-Location
    }
}

function Copy-PackageFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetDir,
        [Parameter(Mandatory = $true)]
        [string[]]$Files,
        [string[]]$Directories = @()
    )

    if (Test-Path $TargetDir) {
        Remove-Item -LiteralPath $TargetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $TargetDir | Out-Null

    foreach ($file in $Files) {
        $literalPath = Join-Path $projectRoot $file
        $resolvedLiteralPath = $literalPath

        if ($file.EndsWith('.pdf')) {
            $updatedLiteralPath = Join-Path $projectRoot (([System.IO.Path]::GetFileNameWithoutExtension($file)) + '.updated.pdf')
            if (Test-Path -LiteralPath $updatedLiteralPath) {
                if ((-not (Test-Path -LiteralPath $literalPath)) -or ((Get-Item -LiteralPath $updatedLiteralPath).LastWriteTime -ge (Get-Item -LiteralPath $literalPath).LastWriteTime)) {
                    $resolvedLiteralPath = $updatedLiteralPath
                }
            }
        }

        if (Test-Path -LiteralPath $resolvedLiteralPath) {
            $sourceItem = Get-Item -LiteralPath $resolvedLiteralPath
            $destinationPath = Join-Path $TargetDir $file
        }
        else {
            $matchedFiles = @(Get-ChildItem -Path $projectRoot -File -Filter $file)
            if ($matchedFiles.Count -ne 1) {
                throw ("Expected exactly one file match for '{0}', but found {1}." -f $file, $matchedFiles.Count)
            }

            $sourceItem = $matchedFiles[0]
            $destinationPath = Join-Path $TargetDir $sourceItem.Name
        }

        $destinationParent = Split-Path -Parent $destinationPath
        if ($destinationParent -and -not (Test-Path -LiteralPath $destinationParent)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourceItem.FullName -Destination $destinationPath
    }

    foreach ($directory in $Directories) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $directory) -Destination (Join-Path $TargetDir $directory) -Recurse
    }
}

function New-ZipArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDir,
        [Parameter(Mandatory = $true)]
        [string]$ZipPath
    )

    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }

    Compress-Archive -Path (Join-Path $SourceDir '*') -DestinationPath $ZipPath -CompressionLevel Optimal
}

$pythonCommand = @(Resolve-PythonCommand)
$edgePath = Resolve-EdgePath

if (Test-Path $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}

if (-not (Test-Path $packageRoot)) {
    New-Item -ItemType Directory -Path $packageRoot | Out-Null
}

$pythonArgs = @()
if ($pythonCommand.Length -gt 1) {
    $pythonArgs += $pythonCommand[1..($pythonCommand.Length - 1)]
}
$pythonArgs += @($docsScript, '--edge-path', $edgePath)

if (-not $SkipDocs) {
    Invoke-NativeCommand -FilePath $pythonCommand[0] -Arguments $pythonArgs
}

$adminDir = Join-Path $packageRoot 'kouku-kinou-admin-deploy'
$windowsDir = Join-Path $packageRoot 'kouku-kinou-windows-client'
$tabletDir = Join-Path $packageRoot 'kouku-kinou-tablet-handout'

Copy-PackageFiles -TargetDir $adminDir -Files @(
    '.env.example',
    'compose.yaml',
    'DEPLOY_SYNOLOGY_JA.html',
    'DEPLOY_SYNOLOGY_JA.md',
    'DEPLOY_SYNOLOGY_JA.pdf',
    'Dockerfile',
    'README.md',
    'README.html',
    'README.pdf',
    'OPERATIONS_MANUAL_PDF_JA.html',
    'OPERATIONS_MANUAL_JA.md',
    'OPERATIONS_MANUAL_JA.pdf',
    'seed_sample_records.py',
    'server.py',
    'TAILSCALE_CLIENT_GUIDE_JA.html',
    'TAILSCALE_CLIENT_GUIDE_JA.md',
    'TAILSCALE_CLIENT_GUIDE_JA.pdf',
    'TAILSCALE_TABLET_GUIDE_JA.html',
    'TAILSCALE_TABLET_GUIDE_JA.md',
    'TAILSCALE_TABLET_GUIDE_JA.pdf',
    'TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html',
    'TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md',
    'TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.pdf',
    'TAILSCALE_TABLET_QR_SHEET_JA.html',
    'TAILSCALE_TABLET_QR_SHEET_JA.md',
    'TAILSCALE_TABLET_QR_SHEET_JA.pdf',
    'TailscaleClientLauncher.cmd',
    'TailscaleClientLauncher.ps1',
    'TailscaleClientLauncher.settings.json',
    'Tailscale*NAS*.md',
    'index.html',
    'build_package.cmd',
    'build_package.ps1',
    'build_docs.py',
    'setup_shared_dev_pc.cmd',
    'setup_shared_dev_pc.ps1',
    'setup_github_auto_sync.cmd',
    'setup_github_auto_sync.ps1',
    'sync_to_github_now.cmd',
    'git_auto_sync.ps1',
    'watch_github_auto_sync.ps1'
) -Directories @('assets')

Copy-PackageFiles -TargetDir $windowsDir -Files @(
    'TAILSCALE_CLIENT_GUIDE_JA.html',
    'TAILSCALE_CLIENT_GUIDE_JA.pdf',
    'TailscaleClientLauncher.cmd',
    'TailscaleClientLauncher.ps1',
    'TailscaleClientLauncher.settings.json'
)

Copy-PackageFiles -TargetDir $tabletDir -Files @(
    'TAILSCALE_TABLET_GUIDE_JA.html',
    'TAILSCALE_TABLET_GUIDE_JA.pdf',
    'TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html',
    'TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.pdf',
    'TAILSCALE_TABLET_QR_SHEET_JA.html',
    'TAILSCALE_TABLET_QR_SHEET_JA.pdf'
)

New-ZipArchive -SourceDir $adminDir -ZipPath (Join-Path $packageRoot 'kouku-kinou-admin-deploy.zip')
New-ZipArchive -SourceDir $windowsDir -ZipPath (Join-Path $packageRoot 'kouku-kinou-windows-client.zip')
New-ZipArchive -SourceDir $tabletDir -ZipPath (Join-Path $packageRoot 'kouku-kinou-tablet-handout.zip')

Write-Host 'Package build completed.'
Write-Host "Admin package:   $adminDir"
Write-Host "Windows package: $windowsDir"
Write-Host "Tablet package:  $tabletDir"