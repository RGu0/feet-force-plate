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
$scriptProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ($project -ne $scriptProject) {
    throw "ProjectRoot must be the controlled source tree containing this launcher"
}

$dev = Join-Path $project "dev.ps1"
$settingsOutput = Join-Path ([IO.Path]::GetTempPath()) ("feetforceplate-r321-" + [guid]::NewGuid().ToString() + ".json")
$runtimeDirectory = $null
try {
    & $dev run python scripts/windows_cloud_default_bundle.py validate --delivery $delivery --project-root $project --settings-output $settingsOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Windows cloud delivery validation failed"
    }
    if (-not (Test-Path -LiteralPath $settingsOutput -PathType Leaf)) {
        throw "Windows cloud delivery did not produce launch settings"
    }
    $settingsJson = Get-Content -LiteralPath $settingsOutput -Raw
    $settings = $settingsJson | ConvertFrom-Json
    $runtimeDirectory = [string]$settings.runtime_directory
    if (-not $runtimeDirectory) {
        throw "Windows cloud delivery did not produce local runtime materials"
    }

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
}
finally {
    if ($runtimeDirectory) {
        Remove-Item -LiteralPath $runtimeDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $settingsOutput -Force -ErrorAction SilentlyContinue
}
