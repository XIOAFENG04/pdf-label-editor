# Install or update the app on the Desktop.
# The asset library is only created when missing, so updating never wipes the
# user's collected assets.
param(
    [string]$Source = 'outputs\可执行版-重建'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root $Source
$exe = Join-Path $source 'PDF标签编辑器.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "missing build: $exe" }

$desk = [Environment]::GetFolderPath('Desktop')
$target = Join-Path $desk 'PDF标签编辑器'
New-Item -ItemType Directory -Force -Path $target | Out-Null

Get-Process -Name 'PDF标签编辑器' -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "closing running instance pid=$($_.Id)"
    $_.CloseMainWindow() | Out-Null
}
Start-Sleep -Milliseconds 800
Get-Process -Name 'PDF标签编辑器' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# A one-file build keeps the EXE open in its bootloader process for a moment
# after the window closes, so wait for the lock to be released before copying.
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Process -Name 'PDF标签编辑器' -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 300
}
$copied = $false
for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        Copy-Item -LiteralPath $exe -Destination (Join-Path $target 'PDF标签编辑器.exe') -Force
        $copied = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $copied) { throw "could not replace the EXE at $target (still in use)" }
foreach ($name in 'app.ico', 'pdf_doc.ico') {
    $from = Join-Path $source $name
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $target -Force }
}
$db = Join-Path $target '素材库.sqlite3'
if (-not (Test-Path -LiteralPath $db)) {
    $seed = Join-Path $source '素材库.sqlite3'
    if (Test-Path -LiteralPath $seed) { Copy-Item -LiteralPath $seed -Destination $db -Force }
    Write-Host 'created an empty asset library'
} else {
    Write-Host 'kept the existing asset library'
}

$lnkPath = Join-Path $desk 'PDF标签编辑器.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath = Join-Path $target 'PDF标签编辑器.exe'
$shortcut.WorkingDirectory = $target
$shortcut.IconLocation = (Join-Path $target 'app.ico') + ',0'
$shortcut.Description = 'PDF 标签编辑器'
$shortcut.Save()

$info = (Get-Item -LiteralPath (Join-Path $target 'PDF标签编辑器.exe')).VersionInfo
Write-Host ('installed {0}  {1:N1} MB  {2}' -f (Join-Path $target 'PDF标签编辑器.exe'),
    ((Get-Item -LiteralPath (Join-Path $target 'PDF标签编辑器.exe')).Length / 1MB),
    $info.FileVersion)
