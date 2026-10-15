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

$postgresTestAction = $env:FEETFORCEPLATE_TEST_POSTGRES_ACTION
if ($postgresTestAction) {
    $allowedPostgresActions = switch ($Action) {
        "setup" { @("prepare", "resume", "start", "stop", "status") }
        "test" { @("live") }
        default { @() }
    }
    if ($allowedPostgresActions -notcontains $postgresTestAction) {
        throw "FEETFORCEPLATE_TEST_POSTGRES_ACTION is not valid for the governed $Action action"
    }

    foreach ($override in @(
        "FEETFORCEPLATE_TEST_POSTGRES_BIND_HOST",
        "FEETFORCEPLATE_TEST_POSTGRES_PORT",
        "FEETFORCEPLATE_TEST_POSTGRES_DATABASE",
        "FEETFORCEPLATE_TEST_POSTGRES_RUNTIME_ROOT"
    )) {
        if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($override))) {
            throw "PostgreSQL test target is fixed to loopback, port 55432, database ffp_ray513_test, and its private runtime root; target overrides are refused"
        }
    }
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
    & $uv.Source python install --managed-python 3.11.9
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not install the project managed Python runtime"
    }
    $managedPython = & $uv.Source python find --managed-python
    if ($LASTEXITCODE -ne 0 -or -not $managedPython) {
        throw "uv could not resolve the project Python runtime"
    }
    $syncArguments = @("sync", "--locked", "--extra", "dev")
    if ($Action -eq "build") { $syncArguments += @("--extra", "build") }
    & $uv.Source @syncArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    switch ($Action) {
        "setup" {
            if ($Command.Count -gt 0) { throw "setup accepts no arguments" }
            if ($postgresTestAction) {
                & $uv.Source run --locked --extra dev python scripts/local_postgres_test_environment.py $postgresTestAction
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            }
        }
        "test" {
            if ($Command.Count -gt 0) { throw "test accepts no arguments" }
            if (-not $env:QT_QPA_PLATFORM) { $env:QT_QPA_PLATFORM = "offscreen" }
            if ($postgresTestAction -eq "live") {
                & $uv.Source run --locked --extra dev python scripts/local_postgres_test_environment.py live-tests
            } else {
                & $uv.Source run --locked --extra dev python -m pytest
            }
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
            & $uv.Source run --locked --extra dev python -m cloud.api.contract_export
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            if ($env:FEETFORCEPLATE_PORTABLE_OUTPUT_ROOT) {
                if ($env:FEETFORCEPLATE_PORTABLE_UNSIGNED_DEVELOPMENT -ne "1") {
                    throw "governed portable build requires explicit unsigned development mode"
                }
                & (Join-Path $projectRoot "scripts\build-portable-release.ps1") `
                    -OutputRoot $env:FEETFORCEPLATE_PORTABLE_OUTPUT_ROOT `
                    -UnsignedDevelopment `
                    -GitCommit ((& git rev-parse --verify HEAD).Trim())
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            }
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
