param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectRoot 'BASLAT.bat'
$icon = Join-Path $projectRoot 'supreme_council\assets\yuksek_sura.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutName = 'Y' + [char]0x00FC + 'ksek ' + [char]0x015E + 'ura.lnk'
$shortcutPath = Join-Path $desktop $shortcutName

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "Application icon not found: $icon"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'Yuksek Sura multi-API council application'
$shortcut.WindowStyle = 1
$shortcut.Save()

if (-not $Quiet) {
    Write-Host "Desktop shortcut created: $shortcutPath"
}
