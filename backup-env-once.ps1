# Encrypt .env with a passphrase. Normally launched by backup-env-once.bat.
#
# .env is the one file neither git nor the dumps carry: DISCORD_TOKEN, API key,
# JWT secret, DB password. A plaintext copy would only widen the exposure, so
# this writes AES-256-CBC with a key derived by PBKDF2 (SHA-256, 200k rounds).
# Decrypt with restore-env.ps1 / restore-env.bat.
#
# Default destination is inside the project (data/backups/env/), which is
# gitignored and travels with the project folder -- the deliberate choice of
# 25/08: backups stay local rather than going to a cloud or a USB drive. That
# means a dead SSD still loses everything; the encrypted file is safe to copy
# anywhere later precisely because it IS encrypted.
#
# KEEP THE PASSPHRASE OFF THIS MACHINE (a password manager on your phone). The
# encrypted file is exactly as recoverable as the passphrase is.
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot ".env"),
    [string]$OutFile,
    # Optional, so the script can be tested or automated; omit it and you are
    # prompted twice, which is the normal path.
    [securestring]$Passphrase
)
$ErrorActionPreference = "Stop"

function ConvertFrom-Secure([securestring]$Secure) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

if (-not (Test-Path $EnvFile)) { throw ".env not found at $EnvFile" }
if (-not $OutFile) {
    # A configured mirror wins (it is by definition the off-machine copy);
    # otherwise keep it with the project, where data/backups/ is gitignored.
    $mirrorLine = Select-String -Path $EnvFile -Pattern '^BACKUP_MIRROR_DIR=(.+)$' | Select-Object -First 1
    $OutFile = if ($mirrorLine) { Join-Path $mirrorLine.Matches.Groups[1].Value.Trim() "env\.env.enc" }
               else { Join-Path $PSScriptRoot "data\backups\env\.env.enc" }
}

if ($Passphrase) {
    $plainPass = ConvertFrom-Secure $Passphrase
} else {
    $first = Read-Host -AsSecureString "Nhap passphrase (se KHONG hien ra man hinh)"
    $again = Read-Host -AsSecureString "Nhap lai passphrase"
    $plainPass = ConvertFrom-Secure $first
    if ($plainPass -cne (ConvertFrom-Secure $again)) { throw "Hai lan nhap khong khop - chay lai" }
}
if ($plainPass.Length -lt 8) { throw "Passphrase phai tu 8 ky tu tro len" }

$salt = New-Object byte[] 16
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)
$kdf = New-Object Security.Cryptography.Rfc2898DeriveBytes($plainPass, $salt, 200000, [Security.Cryptography.HashAlgorithmName]::SHA256)
$aes = [Security.Cryptography.Aes]::Create()
$aes.Key = $kdf.GetBytes(32); $aes.GenerateIV()
$plain = [IO.File]::ReadAllBytes($EnvFile)
$cipher = $aes.CreateEncryptor().TransformFinalBlock($plain, 0, $plain.Length)

New-Item -ItemType Directory -Force (Split-Path $OutFile) | Out-Null
# Layout: 8-byte magic "LAIENV1\0" + 16B salt + 16B IV + ciphertext.
$magic = [Text.Encoding]::ASCII.GetBytes("LAIENV1`0")
[IO.File]::WriteAllBytes($OutFile, $magic + $salt + $aes.IV + $cipher)

Write-Host ""
Write-Host "Da ma hoa: $EnvFile" -ForegroundColor Green
Write-Host "       ->  $OutFile  ($((Get-Item $OutFile).Length) bytes)" -ForegroundColor Green
Write-Host ""
Write-Host "NHO: passphrase phai duoc cat O NGOAI MAY NAY (vi du trinh quan ly mat khau"
Write-Host "     tren dien thoai). Mat passphrase = mat file nay, khong co duong cuu."
Write-Host "Chay lai file nay moi khi .env doi (them token, doi mat khau DB...)."
