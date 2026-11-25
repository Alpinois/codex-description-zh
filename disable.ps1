[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$profileRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$profileRoot = [IO.Path]::GetFullPath($profileRoot)
$runtimePython = Join-Path $profileRoot 'description-zh/venv/Scripts/python.exe'
$workerScript = Join-Path $PSScriptRoot 'plugins/description-zh/scripts/localize.py'
if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw 'The local Python environment is missing. Run enable.ps1 before retrying.'
}

function Invoke-DescriptionCommand([string]$Command) {
    & $runtimePython -B -X utf8 $workerScript $Command
    if ($LASTEXITCODE -ne 0) { throw "Description ZH command failed ($Command)." }
}

$codex = Invoke-DescriptionCommand 'codex-path'
$catalogs = & $codex plugin marketplace list --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Could not read registered marketplaces.' }
$market = $catalogs.marketplaces | Where-Object name -eq 'personal-zh-tools'
if ($market -and [IO.Path]::GetFullPath([string]$market.root) -ne [IO.Path]::GetFullPath($PSScriptRoot)) {
    throw 'Run disable.ps1 from the registered Description ZH folder.'
}

Invoke-DescriptionCommand 'stop' | Out-Null
$deadline = [DateTime]::UtcNow.AddSeconds(90)
do {
    $status = Invoke-DescriptionCommand 'status' | ConvertFrom-Json
    if (-not $status.workerRunning) { break }
    if ([DateTime]::UtcNow -ge $deadline) { throw 'The background process is still stopping. Run disable.ps1 again once it exits.' }
    Start-Sleep -Milliseconds 500
} while ($true)

$restored = Invoke-DescriptionCommand 'restore' | ConvertFrom-Json
$restored | ConvertTo-Json -Depth 5
if ($restored.changedSinceTranslation.Count) {
    throw 'Some files changed after translation. Their backups were retained. Review the paths above before uninstalling.'
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Codex Description ZH.lnk'
if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    if ($shortcut.TargetPath -eq (Join-Path (Split-Path $runtimePython) 'pythonw.exe') -and
        $shortcut.Arguments.Contains('"' + $workerScript + '" watch --home "' + $profileRoot + '"')) {
        Remove-Item -LiteralPath $shortcutPath
    }
}

$listing = & $codex plugin list --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Could not read installed Codex plugins.' }
if ($listing.installed.pluginId -contains 'description-zh@personal-zh-tools') {
    & $codex plugin remove 'description-zh@personal-zh-tools'
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the Codex plugin.' }
}
if ($market) {
    & $codex plugin marketplace remove personal-zh-tools
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the Description ZH marketplace.' }
}
Write-Output 'Description ZH uninstalled. Local backups and cached translations were retained.'
