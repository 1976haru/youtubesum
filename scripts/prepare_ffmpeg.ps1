$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$vendor = Join-Path $repo 'vendor\ffmpeg'
$archive = Join-Path $vendor 'ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip'
$staging = Join-Path $vendor 'staging'
$expectedHash = '1DB36DC94E379E3A7E974E995E278DA05D46C14EBB6DEB7DA11BC8AD1A4A3E3E'
$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-23-14-55/ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip'

New-Item -ItemType Directory -Path $vendor -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive) -or (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $expectedHash) {
    Invoke-WebRequest -Uri $url -OutFile $archive
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $expectedHash) {
    throw 'FFmpeg archive SHA-256 did not match the pinned release.'
}

if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
$package = Get-ChildItem -LiteralPath $staging -Directory | Select-Object -First 1
$sourceBin = Join-Path $package.FullName 'bin'
$targetBin = Join-Path $vendor 'bin'
New-Item -ItemType Directory -Path $targetBin -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceBin 'ffmpeg.exe') -Destination $targetBin -Force
Get-ChildItem -LiteralPath $sourceBin -Filter '*.dll' -File | Copy-Item -Destination $targetBin -Force
Copy-Item -LiteralPath (Join-Path $package.FullName 'LICENSE.txt') -Destination (Join-Path $vendor 'LICENSE.txt') -Force

$gplLicense = Join-Path $vendor 'COPYING.GPLv3'
if (-not (Test-Path -LiteralPath $gplLicense)) {
    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/FFmpeg/FFmpeg/n9.0.2/COPYING.GPLv3' -OutFile $gplLicense
}

$ffmpeg = Join-Path $targetBin 'ffmpeg.exe'
$previousErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$licenseOutput = & $ffmpeg -L 2>&1 | Out-String
$ErrorActionPreference = $previousErrorPreference
if ($licenseOutput -notmatch 'GNU Lesser General Public License' -or $licenseOutput -match 'GNU General Public License') {
    throw 'Bundled FFmpeg is not the expected LGPL-only build.'
}
if ($licenseOutput -match '--enable-libx264|--enable-libx265') {
    throw 'GPL encoder detected in LGPL FFmpeg configuration.'
}
Write-Output "Pinned LGPL FFmpeg ready: $ffmpeg"
Write-Output "Archive SHA-256: $expectedHash"
Write-Output 'Motion H.264 uses the Windows Media Foundation h264_mf encoder.'
