# Decrypt an .env.enc written by backup-env-once.ps1. Writes .env.restored
# next to the target (never overwrites .env itself — compare, then rename).
param(
    [Parameter(Mandatory = $true)][string]$EncFile,
    [string]$OutFile = (Join-Path $PSScriptRoot ".env.restored")
)
$ErrorActionPreference = "Stop"
$blob = [IO.File]::ReadAllBytes($EncFile)
if ([Text.Encoding]::ASCII.GetString($blob[0..6]) -ne "LAIENV1") { throw "Not a backup-env-once.ps1 file" }
$salt = $blob[8..23]; $iv = $blob[24..39]; $cipher = $blob[40..($blob.Length - 1)]
$pass = Read-Host -AsSecureString "Passphrase"
$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass)
try { $plainPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
$kdf = New-Object Security.Cryptography.Rfc2898DeriveBytes($plainPass, [byte[]]$salt, 200000, [Security.Cryptography.HashAlgorithmName]::SHA256)
$aes = [Security.Cryptography.Aes]::Create()
$aes.Key = $kdf.GetBytes(32); $aes.IV = [byte[]]$iv
try { $plain = $aes.CreateDecryptor().TransformFinalBlock([byte[]]$cipher, 0, $cipher.Length) }
catch { throw "Decryption failed - wrong passphrase or corrupted file" }
[IO.File]::WriteAllBytes($OutFile, $plain)
Write-Host "Decrypted -> $OutFile  (review it, then rename to .env yourself)"
