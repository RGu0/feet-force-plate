[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$DeliveryDirectory,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRoot,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$delivery = (Resolve-Path -LiteralPath $DeliveryDirectory).Path
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$requiredFiles = @(
    "bundle-manifest.json",
    "approval.json",
    "README.md",
    "public-cloud-defaults\\cloud-default.json",
    "public-cloud-defaults\\cloud-ca.pem",
    "public-cloud-defaults\\license-public.key"
)
foreach ($relativePath in $requiredFiles) {
    $file = Join-Path $delivery $relativePath
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Windows cloud delivery is incomplete: $relativePath"
    }
    $item = Get-Item -LiteralPath $file
    if (($item.Attributes -band [IO.FileAttributes]::Offline) -ne 0) {
        throw "Windows cloud delivery has not finished syncing locally: $relativePath"
    }
}

$dev = Join-Path $project "dev.ps1"
$settingsJson = & $dev run python scripts/windows_cloud_default_bundle.py validate --delivery $delivery
if ($LASTEXITCODE -ne 0) {
    throw "Windows cloud delivery validation failed"
}
$settings = $settingsJson | ConvertFrom-Json

$env:FEETFORCEPLATE_API_BASE_URL = $settings.api_base_url
$env:FEETFORCEPLATE_INTEGRATION_MODE = if ($settings.integration_mode) { "1" } else { "" }
$env:FEETFORCEPLATE_CA_BUNDLE = $settings.ca_bundle
$env:FEETFORCEPLATE_LICENSE_KEY_ID = $settings.license_key_id
$env:FEETFORCEPLATE_LICENSE_PUBLIC_KEY_FILE = $settings.license_public_key_file

if ($ValidateOnly) {
    $settingsJson
    exit 0
}

& $dev run python -m client.app.packaged_entry
if ($LASTEXITCODE -ne 0) {
    throw "FeetForcePlate institution client exited with code $LASTEXITCODE"
}
