[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('preview','scan','status','pause','resume','stop','restore','markets','projects','codex-path')]
    [string]$Action,
    [string[]]$Market,
    [switch]$ClearMarkets,
    [string]$Project,
    [string]$RemoveProject
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$profileRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$runtimePython = Join-Path $profileRoot 'description-zh/venv/Scripts/python.exe'
$workerScript = Join-Path $PSScriptRoot 'plugins/description-zh/scripts/localize.py'
if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw 'Run enable.ps1 first. It installs the local Python environment.'
}
$arguments = @()
foreach ($name in $Market) { $arguments += @('--market', $name) }
if ($ClearMarkets) { $arguments += '--clear-markets' }
if ($Project) { $arguments += @('--project', $Project) }
if ($RemoveProject) { $arguments += @('--remove-project', $RemoveProject) }

& $runtimePython -B -X utf8 $workerScript $Action @arguments
exit $LASTEXITCODE
