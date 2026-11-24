# Builds the Windows release of Twice Corrupted.
#
#   cd poe_qol
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Produces, in poe_qol\dist\release\:
#   TwiceCorrupted-Setup-<version>.exe   installer (needs Inno Setup 6)
#   TwiceCorrupted-<version>-portable.zip  unzip anywhere and run
#
# Uses .venv\Scripts\python.exe when it exists (run.bat creates it),
# otherwise `python` from PATH. The GitHub "Release" workflow runs this
# same script.
param(
    [string]$Version = "",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not $Version) {
    $init = Get-Content "src\poe_qol\__init__.py" -Raw
    if ($init -match '__version__\s*=\s*"([^"]+)"') { $Version = $Matches[1] }
    else { throw "Can't read __version__ from src\poe_qol\__init__.py" }
}
$Version = $Version.TrimStart("v")
Write-Host "== Twice Corrupted $Version"

$Py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed ($LASTEXITCODE)" }
}

# ---- dependencies ----
Invoke-Checked $Py @("-m", "pip", "install", "--disable-pip-version-check", "-q",
    "-r", "requirements.txt", "mss>=9,<11", "numpy>=1.26,<3",
    "pyinstaller>=6.11,<7")

# ---- Windows version resource (shown in the exe's Properties) ----
New-Item -ItemType Directory -Force "build" | Out-Null
$nums = @(($Version -split "[^0-9]+") | Where-Object { $_ -ne "" } | Select-Object -First 4)
while ($nums.Count -lt 4) { $nums += "0" }
$tuple = ($nums -join ", ")
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($tuple), prodvers=($tuple), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Twice Corrupted'),
      StringStruct('FileDescription', 'Twice Corrupted'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('InternalName', 'TwiceCorrupted'),
      StringStruct('OriginalFilename', 'TwiceCorrupted.exe'),
      StringStruct('ProductName', 'Twice Corrupted'),
      StringStruct('ProductVersion', '$Version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding UTF8 "build\version_info.txt"

# ---- PyInstaller ----
Invoke-Checked $Py @("-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", "dist", "--workpath", "build\pyinstaller",
    "packaging\twice_corrupted.spec")

$App = Join-Path $Root "dist\TwiceCorrupted"
# The app reads/writes these next to the exe (see src\poe_qol\paths.py).
Copy-Item -Recurse -Force "assets" (Join-Path $App "assets")
Copy-Item -Recurse -Force "config" (Join-Path $App "config")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $App "config\user.yaml")
Copy-Item -Force "..\README.md" (Join-Path $App "README.md")

# ---- portable zip ----
$Out = Join-Path $Root "dist\release"
New-Item -ItemType Directory -Force $Out | Out-Null
$Zip = Join-Path $Out "TwiceCorrupted-$Version-portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path $App -DestinationPath $Zip
Write-Host "Portable zip: $Zip"

# ---- installer (Inno Setup 6) ----
if ($SkipInstaller) { return }
$Iscc = (Get-Command "iscc.exe" -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                     "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $Iscc = $p; break }
    }
}
if (-not $Iscc) {
    Write-Warning "Inno Setup 6 not found, so no installer was built (the zip works on its own). Get it from https://jrsoftware.org/isdl.php"
    return
}
Invoke-Checked $Iscc @("/Qp", "/DAppVersion=$Version", "/DSourceDir=$App",
    "/DOutputDir=$Out", "packaging\installer.iss")
Write-Host "Installer:    $(Join-Path $Out "TwiceCorrupted-Setup-$Version.exe")"
