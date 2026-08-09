[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Command)

# Backward-compatible forwarding wrapper. New automation uses dev.ps1 directly.
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($Command.Count -eq 0) {
    & (Join-Path $projectRoot "dev.ps1") setup
} else {
    & (Join-Path $projectRoot "dev.ps1") run @Command
}
exit $LASTEXITCODE
