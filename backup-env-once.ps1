# Encrypt .env with a passphrase into the backup mirror (or a given path).
# .env is the one file neither git nor the dumps carry: DISCORD_TOKEN, API key,
# JWT secret, DB password. Plaintext copies on another drive would widen the
# exposure instead of closing it, so this writes AES-256-CBC with a key derived
# by PBKDF2 (SHA-256, 200k iterations). Decrypt with restore-env.ps1.
#
# Run it manually after secrets change; it needs your passphrase, so it is not
# part of the nightly schedule. KEEP THE PASSPHRASE OUTSIDE THIS MACHINE — the
# encrypted file is exactly as recoverable as the passphrase is.
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot ".env"),
    [string]$OutFile
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $EnvFile)) { throw ".env not found at $EnvFile" }
if (-not $OutFile) {
    $mirror = (Select-String -Path $EnvFile -Pattern '^BACKUP_MIRROR_DIR=(.+)$').Matches.Groups[1].Value
    if (-not $mirror) { throw "No -OutFile given and no BACKUP_MIRROR_DIR in .env" }
    $OutFile = Join-Path $mirror "env\.env.enc"
}
$p1 = Read-Host -AsSecureString "Passphrase"
$p2 = Read-Host -AsSecureString "Repeat passphrase"
function Plain([securestring]$s) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}
if ((Plain $p1) -cne (Plain $p2)) { throw "Passphrases do not match" }
if ((Plain $p1).Length -lt 8) { throw "Use at least 8 characters" }

$salt = New-Object byte[] 16
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)
$kdf = New-Object Security.Cryptography.Rfc2898DeriveBytes((Plain $p1), $salt, 200000, [Security.Cryptography.HashAlgorithmName]::SHA256)
$aes = [Security.Cryptography.Aes]::Create()
$aes.Key = $kdf.GetBytes(32); $aes.GenerateIV()
$plain = [IO.File]::ReadAllBytes($EnvFile)
$cipher = $aes.CreateEncryptor().TransformFinalBlock($plain, 0, $plain.Length)

New-Item -ItemType Directory -Force (Split-Path $OutFile) | Out-Null
# Layout: 8-byte magic "LAIENV1\0" + 16B salt + 16B IV + ciphertext.
$magic = [Text.Encoding]::ASCII.GetBytes("LAIENV1`0")
[IO.File]::WriteAllBytes($OutFile, $magic + $salt + $aes.IV + $cipher)
Write-Host "Encrypted $EnvFile -> $OutFile ($((Get-Item $OutFile).Length) bytes)"
Write-Host "Copy this file somewhere OFF this machine (cloud/USB); D: shares the physical disk with C:."
