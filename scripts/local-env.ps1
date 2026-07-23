[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

# Run FeetForcePlate with a per-machine virtual environment outside OneDrive.
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$uvCommand = $null

if ($env:UV_BIN) {
    $uvCommand = Get-Command $env:UV_BIN -ErrorAction SilentlyContinue
}
if (-not $uvCommand) {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
}
if (-not $uvCommand) {
    Write-Error "uv is not installed. Install uv on this computer and run the script again."
    exit 127
}

if ($env:LOCALAPPDATA) {
    $cacheRoot = Join-Path $env:LOCALAPPDATA "FeetForcePlate"
} else {
    $cacheRoot = Join-Path $HOME ".cache/feetforceplate"
}

if ($env:FEETFORCEPLATE_VENV) {
    $env:UV_PROJECT_ENVIRONMENT = $env:FEETFORCEPLATE_VENV
} else {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $cacheRoot "venv"
}

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$projectRoot$([IO.Path]::PathSeparator)$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $projectRoot
}

Push-Location $projectRoot
try {
    & $uvCommand.Source sync --extra dev --locked
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    if ($Command.Count -gt 0) {
        & $uvCommand.Source run --extra dev @Command
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
