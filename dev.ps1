[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("setup", "test", "lint", "build", "run")]
    [string]$Action,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($null -eq $Command) {
    $Command = @()
}

$projectRoot = (Resolve-Path $PSScriptRoot).Path
$uv = Get-Command ($env:UV_BIN ?? "uv") -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Error "uv is required; install it as a device bootstrap prerequisite."
    exit 127
}

# Do not let legacy process state bypass centralized project environments.
Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
$features = @($env:UV_PREVIEW_FEATURES -split ',' | Where-Object { $_ })
if ($features -notcontains "centralized-project-envs") {
    $env:UV_PREVIEW_FEATURES = ($features + "centralized-project-envs") -join ','
}
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$projectRoot$([IO.Path]::PathSeparator)$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $projectRoot
}

Push-Location $projectRoot
try {
    $artifactArguments = @("scripts/prepare_foundation_artifact.py")
    if ($Action -eq "setup") { $artifactArguments += "--download" }
    $managedPython = & $uv.Source python find --managed-python
    if ($LASTEXITCODE -ne 0 -or -not $managedPython) {
        throw "uv could not resolve the project Python runtime"
    }
    & $managedPython $artifactArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $syncArguments = @("sync", "--locked", "--extra", "dev")
    $syncArguments += @("--find-links", ".foundation-artifacts")
    if ($Action -eq "build") { $syncArguments += @("--extra", "build") }
    & $uv.Source @syncArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    switch ($Action) {
        "setup" { if ($Command.Count -gt 0) { throw "setup accepts no arguments" } }
        "test" {
            if ($Command.Count -gt 0) { throw "test accepts no arguments" }
            if (-not $env:QT_QPA_PLATFORM) { $env:QT_QPA_PLATFORM = "offscreen" }
            & $uv.Source run --locked --extra dev python -m pytest
        }
        "lint" {
            if ($Command.Count -gt 0) { throw "lint accepts no arguments" }
            & $uv.Source run --locked --extra dev ruff check .
            if ($LASTEXITCODE -eq 0) { & $uv.Source run --locked --extra dev mypy shared/contracts cloud/observability }
        }
        "build" {
            if ($Command.Count -gt 0) { throw "build accepts no arguments" }
            & $uv.Source run --locked --extra dev --extra build python -m compileall -q client cloud shared
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        "run" {
            if ($Command.Count -eq 0) { throw "run requires a command" }
            & $uv.Source run --locked --extra dev @Command
        }
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
