[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("set", "verify")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$expectedSids = @($currentSid.Value, $systemSid.Value)
$resolvedPaths = @($Path -split ';' | ForEach-Object { [IO.Path]::GetFullPath($_) })

foreach ($resolvedPath in $resolvedPaths) {
    if (-not (Test-Path -LiteralPath $resolvedPath)) {
        throw "private PostgreSQL path does not exist"
    }

    if ($Action -eq "set") {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $acl.SetOwner($currentSid)
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
        foreach ($sid in @($currentSid, $systemSid)) {
            $rule = [Security.AccessControl.FileSystemAccessRule]::new(
                $sid,
                [Security.AccessControl.FileSystemRights]::FullControl,
                $inheritance,
                [Security.AccessControl.PropagationFlags]::None,
                [Security.AccessControl.AccessControlType]::Allow
            )
            $acl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $resolvedPath -AclObject $acl
    }

    $acl = Get-Acl -LiteralPath $resolvedPath
    $rules = @($acl.Access)
    if ($rules.Count -ne 2) {
        throw "private PostgreSQL path has unexpected access rules"
    }
    foreach ($rule in $rules) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($expectedSids -notcontains $sid) {
            throw "private PostgreSQL path has an unexpected principal"
        }
        if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
            throw "private PostgreSQL path has a deny rule"
        }
        if (($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -ne [Security.AccessControl.FileSystemRights]::FullControl) {
            throw "private PostgreSQL path lacks full control for an allowed principal"
        }
    }
    if ($Action -eq "set" -and -not $acl.AreAccessRulesProtected) {
        throw "private PostgreSQL root inherited access rules"
    }
}
[Console]::WriteLine("private_acl_verified")
