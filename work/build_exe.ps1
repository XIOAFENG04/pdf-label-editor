# Build the app EXE (one-file, windowed) and stage it with the asset library.
# The file is saved as UTF-8 with BOM: Windows PowerShell reads BOM-less UTF-8
# as ANSI and would garble the Chinese literals below.
param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Name = 'PDF标签编辑器'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# PyInstaller lives in a local target directory, not in site-packages.
$env:PYTHONPATH = Join-Path $PSScriptRoot 'pyinstaller-build'

$app = 'outputs\PDF小工具'
# PyInstaller resolves --icon / --version-file relative to the generated spec
# directory, so pass absolute paths for these two inputs.
$iconPath = (Resolve-Path 'work\assets\app.ico').Path
$versionPath = (Resolve-Path 'work\assets\version_info.txt').Path
$iconData = (Resolve-Path (Join-Path $app 'app.ico')).Path
$specDir = Join-Path $PSScriptRoot 'exe-build-new\spec'
$buildDir = Join-Path $PSScriptRoot 'exe-build-new\build'
$distDir = Join-Path $PSScriptRoot 'exe-build-new\dist'
New-Item -ItemType Directory -Force -Path $specDir, $buildDir, $distDir | Out-Null

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean',
    '--onefile', '--windowed',
    '--name', $Name,
    '--icon', $iconPath,
    '--version-file', $versionPath,
    '--paths', $app,
    '--paths', "$app\依赖",
    '--paths', "$app\依赖\win32",
    '--paths', "$app\依赖\win32\lib",
    '--paths', "$app\依赖\pythonwin",
    '--paths', "$app\依赖\pywin32_system32",
    '--hidden-import', 'batch_labels',
    '--hidden-import', 'printing',
    '--hidden-import', 'win32timezone',
    '--hidden-import', 'tkinterdnd2',
    '--hidden-import', 'updater',
    '--hidden-import', 'pdf_association',
    '--add-data', "$iconData;.",
    '--distpath', $distDir,
    '--workpath', $buildDir,
    '--specpath', $specDir,
    "$app\pdf_tool.py"
)

Write-Host "Building $Name ..."
# PyInstaller logs INFO lines to stderr; with ErrorActionPreference=Stop Windows
# PowerShell would turn the first one into a terminating error, so relax it for
# the build call and rely on the exit code instead.
$ErrorActionPreference = 'Continue'
& python @arguments 2>&1 | Tee-Object -FilePath (Join-Path $PSScriptRoot 'exe-build-new\build.log') | Out-Null
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { throw "PyInstaller failed with exit code $code" }

$exe = Join-Path $distDir "$Name.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "missing build output: $exe" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Copy-Item -LiteralPath $exe -Destination (Join-Path $OutDir "$Name.exe") -Force
# Ship an empty asset library: the working database accumulates test assets and
# the app recreates the table on first run anyway.
$db = Join-Path $OutDir '素材库.sqlite3'
Remove-Item -LiteralPath $db -Force -ErrorAction SilentlyContinue
& python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY, name TEXT NOT NULL, pdf BLOB NOT NULL, meta TEXT NOT NULL)'); c.commit(); c.close()" $db
Copy-Item -LiteralPath 'work\assets\app.ico' -Destination (Join-Path $OutDir 'app.ico') -Force
Copy-Item -LiteralPath 'work\assets\pdf_doc.ico' -Destination (Join-Path $OutDir 'pdf_doc.ico') -Force

$file = Get-Item -LiteralPath (Join-Path $OutDir "$Name.exe")
$version = $file.VersionInfo
Write-Host ('Built {0}  {1:N1} MB  {2}' -f $file.FullName, ($file.Length / 1MB), $file.LastWriteTime)
Write-Host ('  ProductName={0}  FileVersion={1}' -f $version.ProductName, $version.FileVersion)
