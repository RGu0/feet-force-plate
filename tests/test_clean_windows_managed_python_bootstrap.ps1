[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$uv = (Get-Command uv -ErrorAction Stop).Source
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("feetforceplate-uv-bootstrap-" + [Guid]::NewGuid())
$originalPath = $env:PATH
$originalInstallDirectory = $env:UV_PYTHON_INSTALL_DIR

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $env:UV_BIN = $uv
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $testRoot "managed-python"
    $env:PATH = (@(
        $originalPath -split [IO.Path]::PathSeparator |
            Where-Object { $_ -notmatch "(?i)(^|[\\/])python|windowsapps" }
    ) -join [IO.Path]::PathSeparator)

    Push-Location $projectRoot
    try {
        & (Join-Path $projectRoot "dev.ps1") setup
        if ($LASTEXITCODE -ne 0) {
            throw "dev.ps1 setup failed with exit code $LASTEXITCODE"
        }

        & (Join-Path $projectRoot "dev.ps1") run python -m pytest tests/test_project_command_contract.py
        if ($LASTEXITCODE -ne 0) {
            throw "dev.ps1 run pytest failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
} finally {
    $env:PATH = $originalPath
    if ($null -eq $originalInstallDirectory) {
        Remove-Item Env:UV_PYTHON_INSTALL_DIR -ErrorAction SilentlyContinue
    } else {
        $env:UV_PYTHON_INSTALL_DIR = $originalInstallDirectory
    }
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
