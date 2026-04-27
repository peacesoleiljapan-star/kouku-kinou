Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Get-LauncherRoot {
    return $PSScriptRoot
}

function Get-SettingsPath {
    return Join-Path (Get-LauncherRoot) 'TailscaleClientLauncher.settings.json'
}

function Get-Settings {
    $settingsPath = Get-SettingsPath
    if (-not (Test-Path $settingsPath)) {
        return [ordered]@{
            organizationName = '口腔機能・栄養評価システム'
            appUrl = ''
            downloadUrl = 'https://tailscale.com/download'
            supportText = '困ったときは管理者へ連絡してください。'
            supportContact = ''
        }
    }

    $raw = Get-Content -Path $settingsPath -Raw -Encoding UTF8
    $loaded = $raw | ConvertFrom-Json
    return [ordered]@{
        organizationName = [string]$loaded.organizationName
        appUrl = [string]$loaded.appUrl
        downloadUrl = [string]$loaded.downloadUrl
        supportText = [string]$loaded.supportText
        supportContact = [string]$loaded.supportContact
    }
}

function Resolve-FirstExistingPath {
    param(
        [string[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Resolve-TailscaleCliPath {
    $command = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    return Resolve-FirstExistingPath -Candidates @(
        (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'),
        (Join-Path $env:ProgramFiles 'Tailscale IPN\tailscale.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\tailscale.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale IPN\tailscale.exe'),
        (Join-Path $env:LocalAppData 'Tailscale\tailscale.exe'),
        (Join-Path $env:LocalAppData 'Tailscale IPN\tailscale.exe')
    )
}

function Resolve-TailscaleAppPath {
    return Resolve-FirstExistingPath -Candidates @(
        (Join-Path $env:ProgramFiles 'Tailscale\tailscale-ipn.exe'),
        (Join-Path $env:ProgramFiles 'Tailscale\Tailscale.exe'),
        (Join-Path $env:ProgramFiles 'Tailscale IPN\tailscale-ipn.exe'),
        (Join-Path $env:ProgramFiles 'Tailscale IPN\Tailscale IPN.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\tailscale-ipn.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\Tailscale.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale IPN\tailscale-ipn.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale IPN\Tailscale IPN.exe'),
        (Join-Path $env:LocalAppData 'Tailscale\tailscale-ipn.exe'),
        (Join-Path $env:LocalAppData 'Tailscale IPN\tailscale-ipn.exe')
    )
}

function Test-ConfiguredUrl {
    param(
        [string]$Url
    )

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $false
    }

    if ($Url -match 'REPLACE-WITH-YOUR-TAILSCALE-URL') {
        return $false
    }

    return $true
}

function Get-TailscaleStatus {
    $cliPath = Resolve-TailscaleCliPath
    if (-not $cliPath) {
        return [ordered]@{
            installed = $false
            connected = $false
            summary = 'Tailscale はまだ導入されていません。'
            detail = '「Tailscale をダウンロード」から導入してください。'
        }
    }

    try {
        $raw = & $cliPath status --json 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) {
            throw 'status を取得できませんでした。'
        }

        $status = $raw | ConvertFrom-Json
        $backendState = [string]$status.BackendState
        $selfInfo = $status.Self
        $loginName = ''
        $dnsName = ''
        $tailscaleIp = ''

        if ($selfInfo) {
            if ($selfInfo.UserProfile) {
                $loginName = [string]$selfInfo.UserProfile.LoginName
            }
            $dnsName = [string]$selfInfo.DNSName
            if ($selfInfo.TailscaleIPs -and $selfInfo.TailscaleIPs.Count -gt 0) {
                $tailscaleIp = [string]$selfInfo.TailscaleIPs[0]
            }
        }

        if ($backendState -eq 'Running') {
            $detailParts = @()
            if ($loginName) {
                $detailParts += "利用者: $loginName"
            }
            if ($dnsName) {
                $detailParts += "端末: $dnsName"
            }
            if ($tailscaleIp) {
                $detailParts += "IP: $tailscaleIp"
            }

            return [ordered]@{
                installed = $true
                connected = $true
                summary = 'Tailscale は接続済みです。'
                detail = ($detailParts -join "`r`n")
            }
        }

        return [ordered]@{
            installed = $true
            connected = $false
            summary = 'Tailscale は導入済みですが、まだ接続されていません。'
            detail = "状態: $backendState`r`n「Tailscale を起動」でサインインまたは接続を確認してください。"
        }
    }
    catch {
        return [ordered]@{
            installed = $true
            connected = $false
            summary = 'Tailscale の状態確認に失敗しました。'
            detail = $_.Exception.Message
        }
    }
}

function Show-Info {
    param(
        [string]$Message,
        [string]$Title = 'Tailscale 接続案内'
    )

    [System.Windows.Forms.MessageBox]::Show($Message, $Title, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
}

$settings = Get-Settings
$statusState = Get-TailscaleStatus

$form = New-Object System.Windows.Forms.Form
$form.Text = if ($settings.organizationName) { "$($settings.organizationName) 接続ツール" } else { 'Tailscale 接続ツール' }
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(760, 560)
$form.MinimumSize = New-Object System.Drawing.Size(760, 560)
$form.Font = New-Object System.Drawing.Font('Yu Gothic UI', 10)
$form.BackColor = [System.Drawing.Color]::FromArgb(247, 250, 252)

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Location = New-Object System.Drawing.Point(20, 18)
$titleLabel.Size = New-Object System.Drawing.Size(700, 30)
$titleLabel.Font = New-Object System.Drawing.Font('Yu Gothic UI', 16, [System.Drawing.FontStyle]::Bold)
$titleLabel.Text = if ($settings.organizationName) { $settings.organizationName } else { '口腔機能・栄養評価システム' }
$form.Controls.Add($titleLabel)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Location = New-Object System.Drawing.Point(20, 58)
$statusLabel.Size = New-Object System.Drawing.Size(700, 26)
$statusLabel.Font = New-Object System.Drawing.Font('Yu Gothic UI', 11, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($statusLabel)

$detailsBox = New-Object System.Windows.Forms.TextBox
$detailsBox.Location = New-Object System.Drawing.Point(20, 94)
$detailsBox.Size = New-Object System.Drawing.Size(700, 122)
$detailsBox.Multiline = $true
$detailsBox.ScrollBars = 'Vertical'
$detailsBox.ReadOnly = $true
$detailsBox.BackColor = [System.Drawing.Color]::White
$form.Controls.Add($detailsBox)

$stepsLabel = New-Object System.Windows.Forms.Label
$stepsLabel.Location = New-Object System.Drawing.Point(20, 230)
$stepsLabel.Size = New-Object System.Drawing.Size(700, 84)
$stepsLabel.Text = "使い方`r`n1. 初回は「Tailscale をダウンロード」で導入します。`r`n2. 次に「Tailscale を起動」でサインインします。`r`n3. 状態が接続済みになったら「アプリを開く」を押します。"
$form.Controls.Add($stepsLabel)

$downloadButton = New-Object System.Windows.Forms.Button
$downloadButton.Location = New-Object System.Drawing.Point(20, 330)
$downloadButton.Size = New-Object System.Drawing.Size(210, 42)
$downloadButton.Text = 'Tailscale をダウンロード'
$form.Controls.Add($downloadButton)

$startButton = New-Object System.Windows.Forms.Button
$startButton.Location = New-Object System.Drawing.Point(250, 330)
$startButton.Size = New-Object System.Drawing.Size(210, 42)
$startButton.Text = 'Tailscale を起動'
$form.Controls.Add($startButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Location = New-Object System.Drawing.Point(480, 330)
$refreshButton.Size = New-Object System.Drawing.Size(240, 42)
$refreshButton.Text = '状態を確認'
$form.Controls.Add($refreshButton)

$copyUrlButton = New-Object System.Windows.Forms.Button
$copyUrlButton.Location = New-Object System.Drawing.Point(20, 388)
$copyUrlButton.Size = New-Object System.Drawing.Size(210, 42)
$copyUrlButton.Text = 'アプリ URL をコピー'
$form.Controls.Add($copyUrlButton)

$openAppButton = New-Object System.Windows.Forms.Button
$openAppButton.Location = New-Object System.Drawing.Point(250, 388)
$openAppButton.Size = New-Object System.Drawing.Size(210, 42)
$openAppButton.Text = 'アプリを開く'
$form.Controls.Add($openAppButton)

$openSettingsButton = New-Object System.Windows.Forms.Button
$openSettingsButton.Location = New-Object System.Drawing.Point(480, 388)
$openSettingsButton.Size = New-Object System.Drawing.Size(240, 42)
$openSettingsButton.Text = '設定ファイルを開く'
$form.Controls.Add($openSettingsButton)

$supportLabel = New-Object System.Windows.Forms.Label
$supportLabel.Location = New-Object System.Drawing.Point(20, 450)
$supportLabel.Size = New-Object System.Drawing.Size(700, 52)
$supportLines = @()
if (-not [string]::IsNullOrWhiteSpace($settings.supportText)) {
    $supportLines += [string]$settings.supportText
}
if (-not [string]::IsNullOrWhiteSpace($settings.supportContact)) {
    $supportLines += "連絡先: $($settings.supportContact)"
}
$supportLabel.Text = ($supportLines -join "`r`n")
$form.Controls.Add($supportLabel)

function Update-StatusView {
    $script:statusState = Get-TailscaleStatus
    $statusLabel.Text = $script:statusState.summary
    $detailsBox.Text = $script:statusState.detail
}

$downloadButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($settings.downloadUrl)) {
        Show-Info 'ダウンロード URL が設定されていません。管理者へ連絡してください。'
        return
    }

    Start-Process $settings.downloadUrl
})

$startButton.Add_Click({
    $appPath = Resolve-TailscaleAppPath
    if (-not $appPath) {
        Show-Info 'Tailscale の起動ファイルが見つかりません。先にインストールしてください。'
        return
    }

    try {
        Start-Process -FilePath $appPath | Out-Null
        Show-Info 'Tailscale を起動しました。サインイン後に「状態を確認」を押してください。'
    }
    catch {
        Show-Info ("Tailscale の起動に失敗しました。`r`n{0}" -f $_.Exception.Message)
    }
})

$refreshButton.Add_Click({
    Update-StatusView
})

$copyUrlButton.Add_Click({
    if (-not (Test-ConfiguredUrl $settings.appUrl)) {
        Show-Info 'アプリ URL がまだ設定されていません。管理者に設定ファイルを確認してもらってください。'
        return
    }

    Set-Clipboard -Value $settings.appUrl
    Show-Info 'アプリ URL をコピーしました。'
})

$openAppButton.Add_Click({
    if (-not (Test-ConfiguredUrl $settings.appUrl)) {
        Show-Info 'アプリ URL がまだ設定されていません。管理者に設定ファイルを確認してもらってください。'
        return
    }

    Start-Process $settings.appUrl
})

$openSettingsButton.Add_Click({
    Start-Process notepad.exe (Get-SettingsPath)
})

Update-StatusView
[void]$form.ShowDialog()