# Build and publish a GitHub release of PDF 标签编辑器.
#
# Usage:
#   work\publish_release.ps1 -Version 1.0.1 -Notes "修复了..." [-Repo owner/name]
#
# Requires: git and GitHub CLI (gh) authenticated (`gh auth login`).
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = '',
    [string]$Repo = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Require-Command([string]$name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "missing command: $name" }
}
Require-Command git
Require-Command gh

# 1) Version bump in the updater module (single source of truth).
$updater = Join-Path $PSScriptRoot '..\outputs\PDF小工具\updater.py'
$text = Get-Content -LiteralPath $updater -Raw -Encoding UTF8
$text = $text -replace "APP_VERSION = '\d+(\.\d+)*'", "APP_VERSION = '$Version'"
Set-Content -LiteralPath $updater -Value $text -Encoding UTF8 -NoNewline
Write-Host "APP_VERSION -> $Version"

# 2) Rebuild the app and installer.
& (Join-Path $PSScriptRoot 'build_exe.ps1') -OutDir 'outputs\可执行版-重建'
& (Join-Path $PSScriptRoot 'build_installer.ps1')
$installer = "outputs\安装包\PDF标签编辑器-安装程序-$Version.exe"
$built = 'outputs\安装包\PDF标签编辑器-安装程序-1.0.0.exe'
if (-not (Test-Path -LiteralPath $installer)) {
    if (Test-Path -LiteralPath $built) { Copy-Item -LiteralPath $built -Destination $installer -Force }
    else { throw "installer not built" }
}

# 3) Commit and tag.
if (-not (Test-Path '.git')) { git init | Out-Null; git branch -M main }
if (-not (git config user.email)) { git config user.email 'dev@localhost' }
if (-not (git config user.name)) { git config user.name 'PDF Label Editor' }
git add -A
$changes = git status --porcelain
if ($changes) { git commit -m "release v$Version" | Out-Null }
git tag -f "v$Version"
git push -f origin main 2>$null
git push -f origin "v$Version" 2>$null

# 4) Create the GitHub repository when needed.
if (-not $Repo) {
    $Repo = gh repo view --json nameWithOwner -q .nameWithOwner 2>$null
    if (-not $Repo) { throw 'repo unknown: pass -Repo owner/name' }
}
if (-not (gh repo view $Repo 2>$null)) {
    gh repo create $Repo --public --source . --remote origin --push
}

# 5) Publish the release with the installer attached.
$title = "PDF 标签编辑器 $Version"
$body = if ($Notes) { $Notes } else { "版本 $Version" }
gh release create "v$Version" $installer --repo $Repo --title $title --notes $body
Write-Host "released https://github.com/$Repo/releases/tag/v$Version"
