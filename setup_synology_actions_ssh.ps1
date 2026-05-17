param(
    [string]$SynologyHost = 'diskstation.tail632bc4.ts.net',
    [int]$Port = 123,
    [string]$User = 'Ao1mini5trAtor',
    [string]$KeyPath = (Join-Path $HOME '.ssh\kouku_kinou_synology_ci'),
    [string]$RepoDir = '/volume1/docker/kouku-kinou',
    [string]$Comment = 'github-actions-kouku-kinou',
    [string]$GitHubSshUser = '',
    [switch]$RegisterRootKey,
    [switch]$SkipRemoteSetup,
    [switch]$PrintGitHubValues,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ('==> ' + $Message) -ForegroundColor Cyan
}

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw ($Name + ' was not found. Install Windows OpenSSH client first.')
    }
}

function New-LocalKeyPair {
    param(
        [string]$PrivateKeyPath,
        [string]$KeyComment,
        [switch]$PreviewOnly
    )

    $publicKeyPath = $PrivateKeyPath + '.pub'
    if ((Test-Path -LiteralPath $PrivateKeyPath) -and (Test-Path -LiteralPath $publicKeyPath)) {
        Write-Host ('Reusing existing key pair: ' + $PrivateKeyPath)
        return
    }

    if ((Test-Path -LiteralPath $PrivateKeyPath) -or (Test-Path -LiteralPath $publicKeyPath)) {
        throw 'A partial key pair already exists. Delete both files or fix them before running this script again.'
    }

    if ($PreviewOnly) {
        Write-Host ('Would generate key pair at: ' + $PrivateKeyPath)
        return
    }

    $keyDir = Split-Path -Parent $PrivateKeyPath
    if (-not (Test-Path -LiteralPath $keyDir)) {
        New-Item -ItemType Directory -Path $keyDir | Out-Null
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = 'ssh-keygen.exe'
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in @('-t', 'ed25519', '-f', $PrivateKeyPath, '-C', $KeyComment)) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $process.StandardInput.WriteLine('')
    $process.StandardInput.WriteLine('')
    $process.StandardInput.Close()

    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($stdout) {
        Write-Host $stdout.TrimEnd()
    }
    if ($stderr) {
        Write-Host $stderr.TrimEnd()
    }

    if ($process.ExitCode -ne 0) {
        throw ('ssh-keygen failed with exit code ' + $process.ExitCode)
    }
}

function Invoke-RemotePublicKeyInstall {
    param(
        [string]$PrivateKeyPath,
        [string]$RemoteUser,
        [string]$RemoteHost,
        [int]$RemotePort,
        [switch]$PreviewOnly
    )

    $publicKeyPath = $PrivateKeyPath + '.pub'
    $publicKey = (Get-Content -LiteralPath $publicKeyPath -Raw).Trim()
    $remoteCommand = 'read -r public_key; umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; grep -qxF "$public_key" ~/.ssh/authorized_keys || printf ''%s\n'' "$public_key" >> ~/.ssh/authorized_keys'
    if ($PreviewOnly) {
        Write-Host ('Would append the local public key to ' + $RemoteUser + '@' + $RemoteHost + ':' + $RemotePort)
        return
    }

    $sshArgs = @('-p', $RemotePort.ToString(), '-o', 'StrictHostKeyChecking=accept-new', ($RemoteUser + '@' + $RemoteHost), $remoteCommand)
    $publicKey | & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to append the public key on Synology.'
    }
}

function Invoke-RemotePermissionRepair {
    param(
        [string]$RemoteUser,
        [string]$RemoteHost,
        [int]$RemotePort,
        [switch]$PreviewOnly
    )

    $remoteHome = '/var/services/homes/' + $RemoteUser
    $remoteSshDir = $remoteHome + '/.ssh'
    $remoteAuthorizedKeys = $remoteSshDir + '/authorized_keys'
    $remoteCommand = @"
sudo sh -c 'mkdir -p "$remoteSshDir" && touch "$remoteAuthorizedKeys" && chown -R "$RemoteUser:users" "$remoteSshDir" && chmod 755 "$remoteHome" && chmod 700 "$remoteSshDir" && chmod 600 "$remoteAuthorizedKeys" && ls -ld "$remoteHome" "$remoteSshDir" "$remoteAuthorizedKeys"'
"@
    if ($PreviewOnly) {
        Write-Host ('Would repair permissions under: ' + $remoteHome)
        return
    }

    $sshArgs = @('-tt', '-p', $RemotePort.ToString(), '-o', 'StrictHostKeyChecking=accept-new', ($RemoteUser + '@' + $RemoteHost), $remoteCommand)
    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to repair Synology SSH permissions.'
    }
}

function Invoke-RootPublicKeyInstall {
    param(
        [string]$PrivateKeyPath,
        [string]$RemoteUser,
        [string]$RemoteHost,
        [int]$RemotePort,
        [switch]$PreviewOnly
    )

    $publicKeyPath = $PrivateKeyPath + '.pub'
    $publicKey = (Get-Content -LiteralPath $publicKeyPath -Raw).Trim()
    $remoteCommand = @'
echo Enter_Ao1mini5trAtor_password_for_sudo_on_Synology; sudo sh -c 'read -r public_key; umask 077; mkdir -p /root/.ssh; touch /root/.ssh/authorized_keys; chmod 700 /root/.ssh; chmod 600 /root/.ssh/authorized_keys; grep -qxF "$public_key" /root/.ssh/authorized_keys || printf "%s\n" "$public_key" >> /root/.ssh/authorized_keys'
'@
    if ($PreviewOnly) {
        Write-Host ('Would append the local public key to root@' + $RemoteHost + ' via sudo from ' + $RemoteUser)
        return
    }

    $sshArgs = @(
        '-tt',
        '-p', $RemotePort.ToString(),
        '-i', $PrivateKeyPath,
        '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=yes',
        ($RemoteUser + '@' + $RemoteHost),
        $remoteCommand
    )
    $publicKey | & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to append the public key for root on Synology.'
    }
}

function Test-KeyLogin {
    param(
        [string]$PrivateKeyPath,
        [string]$RemoteUser,
        [string]$RemoteHost,
        [int]$RemotePort,
        [switch]$PreviewOnly
    )

    if ($PreviewOnly) {
        Write-Host ('Would test key login against ' + $RemoteUser + '@' + $RemoteHost + ':' + $RemotePort)
        return
    }

    $sshArgs = @(
        '-p', $RemotePort.ToString(),
        '-i', $PrivateKeyPath,
        '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=yes',
        ($RemoteUser + '@' + $RemoteHost),
        'id -un; hostname'
    )
    $output = & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Key login test failed.'
    }

    Write-Host 'Key login test succeeded:'
    Write-Host $output
}

function Show-GitHubValues {
    param(
        [string]$RemoteHost,
        [int]$RemotePort,
        [string]$GitHubUser,
        [string]$RemoteRepoDir,
        [string]$PrivateKeyPath,
        [switch]$IncludeSecretValues
    )

    Push-Location $env:SystemRoot
    try {
        $knownHostsText = cmd.exe /d /c ("ssh-keyscan -p " + $RemotePort + " " + $RemoteHost + " 2>nul")
    }
    finally {
        Pop-Location
    }
    $knownHosts = ($knownHostsText -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch '^#') }) -join [Environment]::NewLine

    Write-Host ''
    Write-Host 'GitHub Variables:' -ForegroundColor Yellow
    Write-Host ('TS_NAS_HOST=' + $RemoteHost)
    Write-Host ('TS_NAS_SSH_PORT=' + $RemotePort)
    Write-Host ('TS_NAS_SSH_USER=' + $GitHubUser)
    Write-Host ('TS_REPO_DIR=' + $RemoteRepoDir)

    Write-Host ''
    Write-Host 'GitHub Secrets:' -ForegroundColor Yellow
    Write-Host ('TS_NAS_SSH_PRIVATE_KEY -> ' + $PrivateKeyPath)
    Write-Host 'TS_NAS_KNOWN_HOSTS -> use the ssh-keyscan output below'
    Write-Host $knownHosts

    if ($IncludeSecretValues) {
        Write-Host ''
        Write-Host 'TS_NAS_SSH_PRIVATE_KEY value:' -ForegroundColor Yellow
        Write-Host (Get-Content -LiteralPath $PrivateKeyPath -Raw).TrimEnd()
    }
}

Assert-Command 'ssh.exe'
Assert-Command 'ssh-keygen.exe'
Assert-Command 'ssh-keyscan.exe'

$resolvedGitHubSshUser = $GitHubSshUser
if (-not $resolvedGitHubSshUser) {
    if ($RegisterRootKey) {
        $resolvedGitHubSshUser = 'root'
    }
    else {
        $resolvedGitHubSshUser = $User
    }
}

Write-Step 'Ensuring the local SSH key pair exists'
New-LocalKeyPair -PrivateKeyPath $KeyPath -KeyComment $Comment -PreviewOnly:$DryRun

if (-not $SkipRemoteSetup) {
    Write-Step 'Appending the public key on Synology (SSH password prompt may appear)'
    Invoke-RemotePublicKeyInstall -PrivateKeyPath $KeyPath -RemoteUser $User -RemoteHost $SynologyHost -RemotePort $Port -PreviewOnly:$DryRun

    Write-Step 'Repairing Synology SSH permissions (SSH password and sudo password may appear)'
    Invoke-RemotePermissionRepair -RemoteUser $User -RemoteHost $SynologyHost -RemotePort $Port -PreviewOnly:$DryRun

    Write-Step 'Testing key login'
    Test-KeyLogin -PrivateKeyPath $KeyPath -RemoteUser $User -RemoteHost $SynologyHost -RemotePort $Port -PreviewOnly:$DryRun
}

if ($RegisterRootKey) {
    Write-Step 'Registering the same public key for root on Synology (sudo password may appear)'
    Invoke-RootPublicKeyInstall -PrivateKeyPath $KeyPath -RemoteUser $User -RemoteHost $SynologyHost -RemotePort $Port -PreviewOnly:$DryRun

    Write-Step 'Testing root key login'
    Test-KeyLogin -PrivateKeyPath $KeyPath -RemoteUser 'root' -RemoteHost $SynologyHost -RemotePort $Port -PreviewOnly:$DryRun
}

Write-Step 'Showing GitHub configuration values'
Show-GitHubValues -RemoteHost $SynologyHost -RemotePort $Port -GitHubUser $resolvedGitHubSshUser -RemoteRepoDir $RepoDir -PrivateKeyPath $KeyPath -IncludeSecretValues:$PrintGitHubValues

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green