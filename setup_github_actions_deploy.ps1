param(
    [string]$RepoOwner = '',
    [string]$RepoName = '',
    [string]$WorkflowId = 'deploy-synology.yml',
    [string]$Branch = 'main',
    [string]$SynologyHost = 'diskstation.tail632bc4.ts.net',
    [int]$Port = 123,
    [string]$User = 'Ao1mini5trAtor',
    [string]$RepoDir = '/volume1/docker/kouku-kinou',
    [string]$KeyPath = (Join-Path $HOME '.ssh\kouku_kinou_synology_ci'),
    [string]$TailscaleOAuthClientId = '',
    [string]$TailscaleAudience = '',
    [switch]$PromptForTailscaleAuthKey,
    [switch]$DispatchWorkflow,
    [switch]$ForceRebuild,
    [switch]$SkipVariables,
    [switch]$SkipSshSecrets,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step {
    param([string]$Message)
    Write-Host ('==> ' + $Message) -ForegroundColor Cyan
}

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw ($Name + ' was not found.')
    }
}

function Get-StatusCode {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    if ($null -eq $ErrorRecord.Exception.Response) {
        return $null
    }

    if ($ErrorRecord.Exception.Response -is [System.Net.HttpWebResponse]) {
        return [int]$ErrorRecord.Exception.Response.StatusCode
    }

    if ($null -ne $ErrorRecord.Exception.Response.StatusCode) {
        return [int]$ErrorRecord.Exception.Response.StatusCode.value__
    }

    return $null
}

function Get-GitHubRepository {
    param([string]$Owner, [string]$Name)

    if ($Owner -and $Name) {
        return @{ Owner = $Owner; Name = $Name }
    }

    $originUrl = (& git -C $ScriptRoot remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $originUrl) {
        throw 'Could not read the git origin URL.'
    }

    if ($originUrl -match '^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$') {
        return @{ Owner = $matches[1]; Name = $matches[2] }
    }

    if ($originUrl -match '^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$') {
        return @{ Owner = $matches[1]; Name = $matches[2] }
    }

    throw ('Could not parse a GitHub owner/repo from origin URL: ' + $originUrl)
}

function Get-GitHubHeaders {
    $credentialInput = "protocol=https`nhost=github.com`n`n"
    $credentialText = $credentialInput | git credential fill
    $credentialMap = @{}
    foreach ($line in ($credentialText -split "`r?`n")) {
        if ($line -match '^(.*?)=(.*)$') {
            $credentialMap[$matches[1]] = $matches[2]
        }
    }

    if (-not $credentialMap.ContainsKey('password')) {
        throw 'GitHub token was not returned by git credential fill.'
    }

    return @{
        Authorization = 'Bearer ' + $credentialMap['password']
        'User-Agent' = 'kouku-kinou-setup'
        Accept = 'application/vnd.github+json'
    }
}

function Invoke-GitHubApi {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        $Body
    )

    if ($PSBoundParameters.ContainsKey('Body')) {
        $jsonBody = $Body | ConvertTo-Json -Depth 10 -Compress
        return Invoke-RestMethod -Method $Method -Headers $Headers -Uri $Uri -ContentType 'application/json' -Body $jsonBody
    }

    return Invoke-RestMethod -Method $Method -Headers $Headers -Uri $Uri
}

function Set-GitHubVariable {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$Name,
        [string]$Repo,
        [string]$Value,
        [switch]$PreviewOnly
    )

    if ($PreviewOnly) {
        Write-Host ('Would set variable ' + $Name + '=' + $Value)
        return
    }

    $singleUri = 'https://api.github.com/repos/{0}/{1}/actions/variables/{2}' -f $Owner, $Repo, $Name
    $collectionUri = 'https://api.github.com/repos/{0}/{1}/actions/variables' -f $Owner, $Repo

    try {
        Invoke-GitHubApi -Method 'Patch' -Uri $singleUri -Headers $Headers -Body @{ name = $Name; value = $Value } | Out-Null
        Write-Host ('Updated variable: ' + $Name)
    }
    catch {
        if ((Get-StatusCode $_) -ne 404) {
            throw
        }

        Invoke-GitHubApi -Method 'Post' -Uri $collectionUri -Headers $Headers -Body @{ name = $Name; value = $Value } | Out-Null
        Write-Host ('Created variable: ' + $Name)
    }
}

function Get-GitHubSecretNames {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$Repo
    )

    $uri = 'https://api.github.com/repos/{0}/{1}/actions/secrets?per_page=100' -f $Owner, $Repo
    $response = Invoke-GitHubApi -Method 'Get' -Uri $uri -Headers $Headers
    return @($response.secrets | ForEach-Object { $_.name })
}

function Get-GitHubPublicKey {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$Repo
    )

    $uri = 'https://api.github.com/repos/{0}/{1}/actions/secrets/public-key' -f $Owner, $Repo
    return Invoke-GitHubApi -Method 'Get' -Uri $uri -Headers $Headers
}

function Get-PythonExecutable {
    $venvPython = Join-Path $ScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $command = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw 'python.exe was not found.'
}

function Ensure-PyNaCl {
    param([string]$PythonExe)

    $version = & $PythonExe -c "import nacl; print(nacl.__version__)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $version) {
        Write-Host ('Using PyNaCl ' + (($version | Out-String).Trim()))
        return
    }

    Write-Step 'Installing PyNaCl'
    & $PythonExe -m pip install PyNaCl
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to install PyNaCl.'
    }

    $version = & $PythonExe -c "import nacl; print(nacl.__version__)"
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw 'PyNaCl is still unavailable after installation.'
    }

    Write-Host ('Using PyNaCl ' + (($version | Out-String).Trim()))
}

function Protect-GitHubSecretValue {
    param(
        [string]$PythonExe,
        [string]$PublicKey,
        [string]$SecretValue
    )

    $pythonCode = @"
import base64
import os
import sys
from nacl import encoding, public

public_key = public.PublicKey(base64.b64decode(sys.argv[1]), encoder=encoding.RawEncoder)
secret_value = os.environ['GITHUB_SECRET_VALUE'].encode('utf-8')
sealed_box = public.SealedBox(public_key)
encrypted = sealed_box.encrypt(secret_value)
sys.stdout.write(base64.b64encode(encrypted).decode('ascii'))
"@

    $previousValue = [Environment]::GetEnvironmentVariable('GITHUB_SECRET_VALUE', 'Process')
    [Environment]::SetEnvironmentVariable('GITHUB_SECRET_VALUE', $SecretValue, 'Process')
    try {
        $encrypted = & $PythonExe -c $pythonCode $PublicKey
    }
    finally {
        [Environment]::SetEnvironmentVariable('GITHUB_SECRET_VALUE', $previousValue, 'Process')
    }

    if ($LASTEXITCODE -ne 0 -or -not $encrypted) {
        throw 'Failed to encrypt the GitHub secret value.'
    }

    return ($encrypted | Out-String).Trim()
}

function Set-GitHubSecret {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$Repo,
        [string]$Name,
        [string]$Value,
        [string]$PythonExe,
        [switch]$PreviewOnly
    )

    if ($PreviewOnly) {
        Write-Host ('Would set secret ' + $Name)
        return
    }

    Write-Host ('Uploading secret: ' + $Name)
    $publicKey = Get-GitHubPublicKey -Headers $Headers -Owner $Owner -Repo $Repo
    $encryptedValue = Protect-GitHubSecretValue -PythonExe $PythonExe -PublicKey $publicKey.key -SecretValue $Value
    $uri = 'https://api.github.com/repos/{0}/{1}/actions/secrets/{2}' -f $Owner, $Repo, $Name
    Invoke-GitHubApi -Method 'Put' -Uri $uri -Headers $Headers -Body @{ encrypted_value = $encryptedValue; key_id = $publicKey.key_id } | Out-Null
    Write-Host ('Set secret: ' + $Name)
}

function Get-KnownHostsValue {
    param(
        [string]$RemoteHost,
        [int]$RemotePort
    )

    Push-Location $env:SystemRoot
    try {
        $scanOutput = cmd.exe /d /c ('ssh-keyscan -p ' + $RemotePort + ' ' + $RemoteHost + ' 2>nul')
    }
    finally {
        Pop-Location
    }

    $knownHosts = ($scanOutput -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch '^#') }) -join [Environment]::NewLine
    if (-not $knownHosts) {
        throw 'ssh-keyscan did not return any host keys.'
    }

    return $knownHosts
}

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$SecureString)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Resolve-TailscaleSecretValues {
    param(
        [string]$OAuthClientId,
        [string]$Audience,
        [switch]$PromptForAuthKey
    )

    $result = @{}
    if ($OAuthClientId -and $Audience) {
        $result['TS_OAUTH_CLIENT_ID'] = $OAuthClientId
        $result['TS_AUDIENCE'] = $Audience
        return $result
    }

    if ($PromptForAuthKey) {
        Write-Host 'Waiting for Tailscale auth key input in this terminal.'
        $secureValue = Read-Host -AsSecureString -Prompt 'Enter Tailscale auth key (leave blank to skip)'
        $plainValue = Convert-SecureStringToPlainText -SecureString $secureValue
        if ($plainValue) {
            $result['TAILSCALE_AUTHKEY'] = $plainValue
        }
    }

    return $result
}

function Invoke-WorkflowDispatch {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$Repo,
        [string]$Id,
        [string]$TargetBranch,
        [bool]$ShouldForceRebuild,
        [switch]$PreviewOnly
    )

    if ($PreviewOnly) {
        Write-Host ('Would dispatch workflow ' + $Id + ' on branch ' + $TargetBranch)
        return
    }

    $uri = 'https://api.github.com/repos/{0}/{1}/actions/workflows/{2}/dispatches' -f $Owner, $Repo, $Id
    Invoke-GitHubApi -Method 'Post' -Uri $uri -Headers $Headers -Body @{ ref = $TargetBranch; inputs = @{ force_rebuild = $ShouldForceRebuild } } | Out-Null
    Write-Host ('Dispatched workflow: ' + $Id)
}

Assert-Command 'git.exe'
Assert-Command 'ssh-keyscan.exe'

$repository = Get-GitHubRepository -Owner $RepoOwner -Name $RepoName
$headers = Get-GitHubHeaders
$python = Get-PythonExecutable

Write-Step ('Target repository: ' + $repository.Owner + '/' + $repository.Name)

if (-not $SkipVariables) {
    Write-Step 'Registering repository variables'
    foreach ($variable in @(
        @{ Name = 'TS_NAS_HOST'; Value = $SynologyHost },
        @{ Name = 'TS_NAS_SSH_PORT'; Value = $Port.ToString() },
        @{ Name = 'TS_NAS_SSH_USER'; Value = $User },
        @{ Name = 'TS_REPO_DIR'; Value = $RepoDir }
    )) {
        Set-GitHubVariable -Headers $headers -Owner $repository.Owner -Repo $repository.Name -Name $variable.Name -Value $variable.Value -PreviewOnly:$DryRun
    }
}

if (-not $SkipSshSecrets) {
    Write-Step 'Registering SSH-related secrets'
    if (-not (Test-Path -LiteralPath $KeyPath)) {
        throw ('SSH private key was not found: ' + $KeyPath)
    }

    Ensure-PyNaCl -PythonExe $python

    $privateKeyValue = (Get-Content -LiteralPath $KeyPath -Raw).TrimEnd()
    $knownHostsValue = Get-KnownHostsValue -RemoteHost $SynologyHost -RemotePort $Port

    Set-GitHubSecret -Headers $headers -Owner $repository.Owner -Repo $repository.Name -Name 'TS_NAS_SSH_PRIVATE_KEY' -Value $privateKeyValue -PythonExe $python -PreviewOnly:$DryRun
    Set-GitHubSecret -Headers $headers -Owner $repository.Owner -Repo $repository.Name -Name 'TS_NAS_KNOWN_HOSTS' -Value $knownHostsValue -PythonExe $python -PreviewOnly:$DryRun
}

$tailscaleSecrets = Resolve-TailscaleSecretValues -OAuthClientId $TailscaleOAuthClientId -Audience $TailscaleAudience -PromptForAuthKey:$PromptForTailscaleAuthKey
foreach ($secretName in $tailscaleSecrets.Keys) {
    if ($secretName -in @('TS_OAUTH_CLIENT_ID', 'TS_AUDIENCE')) {
        Set-GitHubSecret -Headers $headers -Owner $repository.Owner -Repo $repository.Name -Name $secretName -Value $tailscaleSecrets[$secretName] -PythonExe $python -PreviewOnly:$DryRun
    }
    elseif ($secretName -eq 'TAILSCALE_AUTHKEY') {
        Set-GitHubSecret -Headers $headers -Owner $repository.Owner -Repo $repository.Name -Name $secretName -Value $tailscaleSecrets[$secretName] -PythonExe $python -PreviewOnly:$DryRun
    }
}

$secretNames = @()
if (-not $DryRun) {
    $secretNames = Get-GitHubSecretNames -Headers $headers -Owner $repository.Owner -Repo $repository.Name
}

if ($DispatchWorkflow) {
    $hasOidc = ($secretNames -contains 'TS_OAUTH_CLIENT_ID') -and ($secretNames -contains 'TS_AUDIENCE')
    $hasAuthKey = $secretNames -contains 'TAILSCALE_AUTHKEY'
    if (-not $DryRun -and -not ($hasOidc -or $hasAuthKey)) {
        throw 'Cannot dispatch the workflow because neither TS_OAUTH_CLIENT_ID/TS_AUDIENCE nor TAILSCALE_AUTHKEY is configured.'
    }

    Write-Step 'Dispatching the GitHub Actions workflow'
    Invoke-WorkflowDispatch -Headers $headers -Owner $repository.Owner -Repo $repository.Name -Id $WorkflowId -TargetBranch $Branch -ShouldForceRebuild:$ForceRebuild -PreviewOnly:$DryRun
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green