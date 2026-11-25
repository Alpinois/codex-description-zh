[CmdletBinding()]
param(
    [string]$Python,
    [switch]$Start,
    [switch]$AtLogon
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($AtLogon -and -not $Start) { throw '-AtLogon requires -Start.' }
if (-not $Python) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
}
$profileRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$profileRoot = [IO.Path]::GetFullPath($profileRoot)
$workerScript = Join-Path $PSScriptRoot 'plugins/description-zh/scripts/localize.py'
$venv = Join-Path $profileRoot 'description-zh/venv'
$runtimePython = Join-Path $venv 'Scripts/python.exe'
$runtimePythonw = Join-Path $venv 'Scripts/pythonw.exe'

function Invoke-DescriptionCommand([string]$Command) {
    & $runtimePython -B -X utf8 $workerScript $Command
    if ($LASTEXITCODE -ne 0) { throw "Description ZH command failed ($Command)." }
}

if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    & $Python -c 'import sys; sys.exit(sys.version_info < (3, 11))'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required.' }
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}
& $runtimePython -c 'import importlib.metadata as m, sys; sys.exit(not any(p.version == ''6.0.3'' for p in m.distributions(name=''PyYAML'')))'
if ($LASTEXITCODE -ne 0) {
    & $runtimePython -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the dependency from requirements.txt.' }
}
$codex = Invoke-DescriptionCommand 'codex-path'
$registered = & $codex plugin marketplace list --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Could not read Codex marketplaces.' }
$market = $registered.marketplaces | Where-Object name -eq 'personal-zh-tools'
if ($market -and [IO.Path]::GetFullPath([string]$market.root) -ne [IO.Path]::GetFullPath($PSScriptRoot)) {
    throw 'The Description ZH marketplace uses another folder. Run disable.ps1 from that folder before moving it.'
}
if (-not $market) {
    & $codex plugin marketplace add $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not register the local marketplace.' }
}
& $codex plugin add 'description-zh@personal-zh-tools'
if ($LASTEXITCODE -ne 0) { throw 'Could not install the Codex plugin.' }

if (-not $Start) {
    Write-Output 'Installed. Run manage.ps1 preview to inspect the scope. Run enable.ps1 -Start to start translation.'
    return
}
if (-not (Test-Path -LiteralPath $runtimePythonw -PathType Leaf)) { throw 'pythonw.exe is required to run in the background.' }
$workerArguments = '-B -X utf8 "' + $workerScript + '" watch --home "' + $profileRoot + '"'
if ($AtLogon) {
    $startup = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startup 'Codex Description ZH.lnk'
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    if ($shortcut.TargetPath -and ($shortcut.TargetPath -ne $runtimePythonw -or $shortcut.Arguments -ne $workerArguments)) {
        throw 'A different Description ZH startup shortcut already exists. Remove the previous installation before enabling startup.'
    }
    $shortcut.TargetPath = $runtimePythonw
    $shortcut.Arguments = $workerArguments
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = 'Translate Codex plugin and skill descriptions'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}
Invoke-DescriptionCommand 'resume' | Out-Null
$status = Invoke-DescriptionCommand 'status' | ConvertFrom-Json
if (-not $status.workerRunning) {
    $process = Start-Process -FilePath $runtimePythonw -ArgumentList $workerArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $status = Invoke-DescriptionCommand 'status' | ConvertFrom-Json
        if ($status.workerRunning) { break }
        if ($process.HasExited -or [DateTime]::UtcNow -ge $deadline) { throw 'The translation worker could not start.' }
        Start-Sleep -Milliseconds 300
    } while ($true)
}
Write-Output 'Description ZH worker is running. Use manage.ps1 status to see the latest scan.'
