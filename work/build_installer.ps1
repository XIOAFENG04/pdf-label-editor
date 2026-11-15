# Build the Windows installer (single EXE) that carries the application payload.
# It asks for an install folder and can create Desktop / Start-menu shortcuts.
param(
    [string]$OutDir = 'outputs\安装包',
    [string]$AppDir = 'outputs\可执行版-重建'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = Join-Path $PSScriptRoot 'pyinstaller-build'

$app = $AppDir
$exe = Join-Path $app 'PDF标签编辑器.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "missing app build: $exe" }

$payload = Join-Path $PSScriptRoot 'installer\payload'
New-Item -ItemType Directory -Force -Path $payload | Out-Null
Copy-Item -LiteralPath $exe -Destination $payload -Force
foreach ($name in 'app.ico', 'pdf_doc.ico') {
    $source = Join-Path $app $name
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $payload -Force }
}

$icon = (Resolve-Path 'work\assets\app.ico').Path
$version = (Resolve-Path 'work\assets\version_info_installer.txt').Path
$association = (Resolve-Path 'outputs\PDF小工具\pdf_association.py').Path
$data = (Resolve-Path $payload).Path
$specDir = Join-Path $PSScriptRoot 'installer\spec'
$buildDir = Join-Path $PSScriptRoot 'installer\build'
$distDir = Join-Path $PSScriptRoot 'installer\dist'
New-Item -ItemType Directory -Force -Path $specDir, $buildDir, $distDir, $OutDir | Out-Null

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean',
    '--onefile', '--windowed',
    '--name', 'PDF标签编辑器-安装程序',
    '--icon', $icon,
    '--version-file', $version,
    '--add-data', "$data;payload",
    '--add-data', "$association;.",
    '--distpath', $distDir,
    '--workpath', $buildDir,
    '--specpath', $specDir,
    'work\installer\installer.py'
)

Write-Host 'Building installer ...'
$ErrorActionPreference = 'Continue'
& python @arguments 2>&1 | Tee-Object -FilePath (Join-Path $PSScriptRoot 'installer\build.log') | Out-Null
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { throw "PyInstaller failed with exit code $code" }

$built = Join-Path $distDir 'PDF标签编辑器-安装程序.exe'
if (-not (Test-Path -LiteralPath $built)) { throw "missing installer output: $built" }
$versionText = Get-Content -LiteralPath 'outputs\PDF小工具\updater.py' -Raw -Encoding UTF8
$appVersion = if ($versionText -match "APP_VERSION = '([^']+)'") { $matches[1] } else { '1.0.0' }
$target = Join-Path $OutDir "PDF标签编辑器-安装程序-$appVersion.exe"
$ascii = Join-Path $OutDir "PDFLabelEditor-Setup-$appVersion.exe"
Copy-Item -LiteralPath $built -Destination $ascii -Force
Copy-Item -LiteralPath $built -Destination $target -Force
$file = Get-Item -LiteralPath $target
Write-Host ('Installer: {0}  {1:N1} MB' -f $file.FullName, ($file.Length / 1MB))
