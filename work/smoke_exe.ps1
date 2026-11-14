param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Pdf,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$WaitSeconds = 40
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Shot {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$name = [System.IO.Path]::GetFileNameWithoutExtension($Exe)
$running = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
if ($running.Count) { throw "an instance of $name is already running; close it first" }

$proc = Start-Process -FilePath $Exe -ArgumentList "`"$Pdf`"" -PassThru
# A one-file build starts a bootloader parent plus the real child process, so the
# window belongs to a process other than $proc. Look for any window of that name.
$windowed = $null
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    $windowed = Get-Process -Name $name -ErrorAction SilentlyContinue |
                Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($windowed) { break }
    $proc.Refresh()
    if ($proc.HasExited -and -not (Get-Process -Name $name -ErrorAction SilentlyContinue)) { break }
}

if (-not $windowed) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "NO WINDOW after $WaitSeconds s"
    exit 1
}

$hwnd = $windowed.MainWindowHandle
Write-Host "pid=$($windowed.Id) hwnd=$hwnd title='$($windowed.MainWindowTitle)'"
Start-Sleep -Seconds 6  # let the first page render
$windowed.Refresh()
if ($windowed.HasExited) { Write-Host 'EXITED AFTER WINDOW'; exit 1 }

$rect = New-Object Win32Shot+RECT
[void][Win32Shot]::GetWindowRect($hwnd, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
Write-Host "window ${width}x${height}"
if ($width -lt 100 -or $height -lt 100) { Write-Host 'BAD WINDOW SIZE'; exit 1 }

$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
$ok = [Win32Shot]::PrintWindow($hwnd, $hdc, 2)
$graphics.ReleaseHdc($hdc)
$graphics.Dispose()
$bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()
Write-Host "printwindow=$ok saved=$Out"

Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host 'stopped'
