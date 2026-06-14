# Creates two shortcuts (.lnk) in this folder, each with its own icon:
#   "Chaser's Shenanigans.lnk" -> launches the app (no console), app icon
#   "Install.lnk"              -> runs install.bat, install icon
# Run via create_shortcuts.bat (which handles the execution policy).
# A .bat file cannot itself hold an icon - a shortcut is the Windows-correct way.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ws   = New-Object -ComObject WScript.Shell

# --- App shortcut: launch the GUI directly via the venv's pythonw (no console).
$pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
$app = $ws.CreateShortcut((Join-Path $root "Chaser's Shenanigans.lnk"))
if (Test-Path $pyw) { $app.TargetPath = $pyw } else { $app.TargetPath = 'pythonw.exe' }
$app.Arguments        = 'launcher.py'
$app.WorkingDirectory = $root
$app.IconLocation     = (Join-Path $root 'icon.ico')
$app.Description       = "Chaser's Shenanigans"
$app.Save()

# --- Installer shortcut: runs install.bat, with the install-themed icon.
$ins = $ws.CreateShortcut((Join-Path $root 'Install.lnk'))
$ins.TargetPath       = (Join-Path $root 'install.bat')
$ins.WorkingDirectory = $root
$ins.IconLocation     = (Join-Path $root 'install.ico')
$ins.Description      = "Install Chaser's Shenanigans"
$ins.Save()

Write-Host "Created shortcuts in $root :"
Write-Host "  Chaser's Shenanigans.lnk  (app icon)"
Write-Host "  Install.lnk               (install icon)"
Write-Host ""
Write-Host "Tip: drag either onto your Desktop, or right-click the running app"
Write-Host "on the taskbar and choose 'Pin to taskbar'."
