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
    $syncArguments = @("sync", "--locked", "--extra", "dev")
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
            $foundationReleaseDirectory = Join-Path ([IO.Path]::GetTempPath()) ("techflex-cloud-foundation-" + [guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path $foundationReleaseDirectory -Force | Out-Null
            try {
                & $uv.Source build packages/techflex-cloud-foundation --out-dir $foundationReleaseDirectory
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
                & $uv.Source run --locked --extra dev python scripts/record_foundation_release_baseline.py `
                    --project-root $projectRoot `
                    --dist-dir $foundationReleaseDirectory `
                    --baseline-strategy legacy-httpx-client/1 `
                    --output (Join-Path $foundationReleaseDirectory "release-evidence.json")
            } finally {
                Remove-Item -LiteralPath $foundationReleaseDirectory -Recurse -Force -ErrorAction SilentlyContinue
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
