[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputRoot,
    [switch]$UnsignedDevelopment,
    [string]$GitCommit
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localEnvironment = Join-Path $projectRoot "scripts\local-env.ps1"
$releaseRoot = Join-Path $OutputRoot "release"
$buildRoot = Join-Path $OutputRoot "build"
$distRoot = Join-Path $OutputRoot "dist"

if (Test-Path -LiteralPath $OutputRoot) {
    $existingItems = Get-ChildItem -LiteralPath $OutputRoot -Force
    if ($existingItems.Count -gt 0) {
        throw "OutputRoot must be empty: $OutputRoot"
    }
} else {
    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
}
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

$pyproject = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"(?<version>[^"]+)"\s*$') {
    throw "Cannot determine application version from pyproject.toml"
}
$appVersion = $Matches.version

if (-not $GitCommit) {
    $GitCommit = $env:FEETFORCEPLATE_BUILD_COMMIT
}
if (-not $GitCommit) {
    $GitCommit = (& git -C $projectRoot rev-parse --verify HEAD).Trim()
}
if (-not $GitCommit) {
    throw "GitCommit or FEETFORCEPLATE_BUILD_COMMIT is required"
}

& powershell -ExecutionPolicy Bypass -File $localEnvironment uv run --extra dev --extra build python -m PyInstaller `
    --noconfirm --clean `
    --distpath $distRoot `
    --workpath $buildRoot `
    (Join-Path $projectRoot "client\app\packaging\FeetForcePlate.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$applicationDirectory = Join-Path $distRoot "FeetForcePlate"
$applicationExecutable = Join-Path $applicationDirectory "FeetForcePlate.exe"
if (-not (Test-Path -LiteralPath $applicationExecutable -PathType Leaf)) {
    throw "PyInstaller did not produce FeetForcePlate.exe"
}

if ($UnsignedDevelopment) {
    $signingStatus = "unsigned-development"
} else {
    $certificateThumbprint = $env:FEETFORCEPLATE_SIGN_CERT_THUMBPRINT
    if (-not $certificateThumbprint) {
        throw "FEETFORCEPLATE_SIGN_CERT_THUMBPRINT is required for a customer release"
    }
    $signTool = $env:FEETFORCEPLATE_SIGNTOOL
    if (-not $signTool) {
        $signTool = (Get-Command signtool.exe -ErrorAction Stop).Source
    }
    & $signTool sign /sha1 $certificateThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $applicationExecutable
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed with exit code $LASTEXITCODE"
    }
    & $signTool verify /pa /v $applicationExecutable
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode verification failed with exit code $LASTEXITCODE"
    }
    if ((Get-AuthenticodeSignature -LiteralPath $applicationExecutable).Status -ne "Valid") {
        throw "Authenticode verification did not return Valid"
    }
    $signingStatus = "signed"
}

$archiveName = "FeetForcePlate-$appVersion-windows-x86_64.zip"
$archive = Join-Path $releaseRoot $archiveName
Compress-Archive -LiteralPath $applicationDirectory -DestinationPath $archive -CompressionLevel Optimal
$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$archive.sha256" -Value "$digest  $archiveName" -NoNewline -Encoding ascii

& powershell -ExecutionPolicy Bypass -File $localEnvironment python -m client.app.packaging.portable_release create `
    --archive $archive `
    --app-version $appVersion `
    --git-commit $GitCommit `
    --signing-status $signingStatus `
    --output (Join-Path $releaseRoot "release-manifest.json")
if ($LASTEXITCODE -ne 0) {
    throw "Release manifest creation failed with exit code $LASTEXITCODE"
}

if ($UnsignedDevelopment) {
    & (Join-Path $projectRoot "scripts\verify-portable-release.ps1") `
        -ReleaseDirectory $releaseRoot `
        -AllowUnsignedDevelopment
} else {
    & (Join-Path $projectRoot "scripts\verify-portable-release.ps1") `
        -ReleaseDirectory $releaseRoot
}
if ($LASTEXITCODE -ne 0) {
    throw "Portable release verification failed with exit code $LASTEXITCODE"
}

Write-Host "Portable release created: $releaseRoot"
