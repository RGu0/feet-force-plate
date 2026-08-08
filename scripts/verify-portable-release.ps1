[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ReleaseDirectory,
    [switch]$AllowUnsignedDevelopment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localEnvironment = Join-Path $projectRoot "scripts\local-env.ps1"
$resolvedReleaseDirectory = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$arguments = @(
    "-m", "client.app.packaging.portable_release", "verify",
    "--release-directory", $resolvedReleaseDirectory
)
if (-not $AllowUnsignedDevelopment) {
    $arguments += "--require-signed"
}

& powershell -ExecutionPolicy Bypass -File $localEnvironment python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Portable release manifest verification failed with exit code $LASTEXITCODE"
}

$manifest = Get-Content -LiteralPath (Join-Path $resolvedReleaseDirectory "release-manifest.json") -Raw | ConvertFrom-Json
if ($manifest.signing_status -eq "unsigned-development") {
    if (-not $AllowUnsignedDevelopment) {
        throw "unsigned-development release cannot be delivered"
    }
    Write-Host "Unsigned development release verified for internal use only: $resolvedReleaseDirectory"
    exit 0
}

$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ("feetforceplate-release-verify-" + [guid]::NewGuid().ToString("N"))
try {
    Expand-Archive -LiteralPath (Join-Path $resolvedReleaseDirectory $manifest.archive.filename) -DestinationPath $temporaryDirectory
    $applicationExecutable = Join-Path $temporaryDirectory $manifest.application_executable
    if (-not (Test-Path -LiteralPath $applicationExecutable -PathType Leaf)) {
        throw "Portable release executable is missing after archive extraction"
    }
    if ((Get-AuthenticodeSignature -LiteralPath $applicationExecutable).Status -ne "Valid") {
        throw "Portable release executable does not have a valid Authenticode signature"
    }
} finally {
    if (Test-Path -LiteralPath $temporaryDirectory) {
        Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
    }
}

Write-Host "Signed portable release verified: $resolvedReleaseDirectory"
