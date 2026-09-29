# Authenticode-sign one file (the app exe, the installer, the uninstaller).
# Called by tools\build.py and, through Inno Setup's SignTool, by ISCC.
#
# Configure ONE of these before building:
#   MHSTT_SIGN_THUMBPRINT  thumbprint of a code-signing certificate in the Windows
#                          certificate store (also works for USB tokens and cloud
#                          signing services that expose the certificate there)
#   MHSTT_SIGN_PFX (+ MHSTT_SIGN_PFX_PASSWORD)  path to a .pfx file
# Optional: MHSTT_SIGN_TIMESTAMP (default http://timestamp.digicert.com)
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = 'Stop'

$cert = $null
if ($env:MHSTT_SIGN_THUMBPRINT) {
    $cert = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My |
        Where-Object { $_.Thumbprint -eq $env:MHSTT_SIGN_THUMBPRINT } | Select-Object -First 1
} elseif ($env:MHSTT_SIGN_PFX) {
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
        $env:MHSTT_SIGN_PFX, $env:MHSTT_SIGN_PFX_PASSWORD)
}
if (-not $cert) { throw 'No code-signing certificate configured (see tools\sign.ps1).' }
if (-not $cert.HasPrivateKey) { throw "Certificate $($cert.Subject) has no private key." }

$ts = if ($env:MHSTT_SIGN_TIMESTAMP) { $env:MHSTT_SIGN_TIMESTAMP } else { 'http://timestamp.digicert.com' }
$result = Set-AuthenticodeSignature -FilePath $File -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $ts
if (-not $result.SignerCertificate) { throw "Signing failed for ${File}: $($result.StatusMessage)" }
if ($result.Status -ne 'Valid') {
    Write-Warning "Signed $File, but Windows does not trust the certificate: $($result.StatusMessage)"
} else {
    Write-Host "Signed $File ($($cert.Subject))"
}
