# Starts the built bgpwatch.exe in demo mode, checks that it keeps running and writes the expected
# log lines, and takes a screenshot of the desktop. Used by the CI job; also runnable by hand:
#     powershell -File packaging\smoke_windows.ps1 dist\bgpwatch\bgpwatch.exe
param([string]$Exe = "dist\bgpwatch\bgpwatch.exe", [string]$Out = "smoke")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$logs = Join-Path (Resolve-Path $Out) "logs"

$p = Start-Process -FilePath $Exe -PassThru -ArgumentList @(
    "--demo", "--ips", "8.8.8.8,8.8.4.4,1.1.1.1", "--interval", "5",
    "--no-restore", "--no-notify", "--log-dir", $logs)
Start-Sleep -Seconds 25

try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $Out "windows.png"))
    Write-Host "screenshot saved ($($b.Width)x$($b.Height))"
} catch { Write-Host "screenshot not possible here: $_" }

$alive = -not $p.HasExited
if ($alive) { Stop-Process -Id $p.Id -Force }
$log = Join-Path $logs "demo\bgpwatch.log"
$text = if (Test-Path $log) { Get-Content $log -Raw } else { "" }
Write-Host "still running after 25 s: $alive"
Write-Host "log file: $log ($($text.Length) bytes)"

$bad = @()
if (-not $alive)                          { $bad += "the app exited early (exit code $($p.ExitCode))" }
if ($text -notmatch "FIRST-SEEN")         { $bad += "no FIRST-SEEN event in the log" }
if ($text -notmatch "RPKI-INVALID")       { $bad += "no RPKI-INVALID event in the log" }
if ($bad.Count) { $bad | ForEach-Object { Write-Host "FAIL: $_" }; exit 1 }
Write-Host "OK: the Windows build starts, polls, validates RPKI and logs"
