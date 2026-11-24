$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop 'STS2 Training Dashboard.lnk'
if (Test-Path -LiteralPath $path) { throw "Shortcut already exists: $path" }
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$shortcut.TargetPath = (Join-Path $PSScriptRoot 'start-dashboard.cmd')
$shortcut.WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$shortcut.Description = 'INF2 local training dashboard'
$shortcut.Save()
