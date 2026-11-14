# Register (or remove) this application as an *optional* handler for .pdf files
# in the current user's profile, with its own document icon, so a PDF file can
# show pdf_doc.ico while the EXE keeps app.ico.
#
# This never changes the default handler: it only adds the app to "打开方式".
# To make it the default, use Explorer: right click a PDF -> 打开方式 ->
# 选择其他应用 -> PDF 标签编辑器 -> 始终使用.
#
# Usage:
#   pwsh -NoProfile -File work\register_pdf_file_type.ps1
#   pwsh -NoProfile -File work\register_pdf_file_type.ps1 -Unregister
param(
    [string]$Exe,
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$progId = 'PDFLabelEditor.Document'
$classes = 'HKCU:\Software\Classes'

if ($Unregister) {
    Remove-Item -Path "$classes\$progId" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path "$classes\.pdf\OpenWithProgids" -Name $progId -Force -ErrorAction SilentlyContinue
    Write-Host "Removed $progId and the .pdf OpenWith entry."
} else {
    if (-not $Exe) { $Exe = Join-Path $PSScriptRoot '..\outputs\可执行版-重建\PDF标签编辑器.exe' }
    $exePath = (Resolve-Path -LiteralPath $Exe).Path
    $dir = Split-Path -Parent $exePath
    $iconPath = Join-Path $dir 'pdf_doc.ico'
    if (-not (Test-Path -LiteralPath $iconPath)) {
        throw "missing document icon: $iconPath (ship pdf_doc.ico next to the EXE)"
    }

    New-Item -Path "$classes\$progId" -Force | Out-Null
    Set-ItemProperty -Path "$classes\$progId" -Name '(default)' -Value 'PDF 标签文档'
    New-Item -Path "$classes\$progId\DefaultIcon" -Force | Out-Null
    Set-ItemProperty -Path "$classes\$progId\DefaultIcon" -Name '(default)' -Value ('"{0}",0' -f $iconPath)
    New-Item -Path "$classes\$progId\shell\open\command" -Force | Out-Null
    Set-ItemProperty -Path "$classes\$progId\shell\open\command" -Name '(default)' -Value ('"{0}" "%1"' -f $exePath)
    New-Item -Path "$classes\.pdf\OpenWithProgids" -Force | Out-Null
    New-ItemProperty -Path "$classes\.pdf\OpenWithProgids" -Name $progId -Value ([byte[]]@()) -PropertyType Binary -Force | Out-Null

    Write-Host "Registered $progId"
    Write-Host "  program : $exePath"
    Write-Host "  icon    : $iconPath"
}

Add-Type -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int a, int b, System.IntPtr c, System.IntPtr d);' -Name Shell32 -Namespace Win32 -ErrorAction SilentlyContinue
[Win32.Shell32]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host 'Explorer icon cache refresh requested.'
