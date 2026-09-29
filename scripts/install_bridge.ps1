# Installs the bridge into the game: native\bin\GLU32.dll -> game folder, mod\ai_bridge -> mods folder.
# The game must be closed (Windows locks the DLL while it runs). The old DLL is kept as GLU32.dll.bak.
param([string]$GameDir = "")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

if (-not $GameDir) {
    $steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue).SteamPath
    $candidates = @("C:\Program Files (x86)\Steam\steamapps\common\Prison Architect")
    if ($steam) {
        $candidates = @((Join-Path $steam "steamapps\common\Prison Architect")) + $candidates
        $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            $candidates += Select-String -Path $vdf -Pattern '"path"\s+"([^"]+)"' | ForEach-Object {
                Join-Path ($_.Matches[0].Groups[1].Value -replace '\\\\', '\') "steamapps\common\Prison Architect" }
        }
    }
    $GameDir = $candidates | Where-Object { Test-Path (Join-Path $_ "Prison Architect64.exe") } | Select-Object -First 1
    if (-not $GameDir) { throw "Prison Architect not found. Pass -GameDir 'C:\path\to\Prison Architect'." }
}
if (Get-Process "Prison Architect64" -ErrorAction SilentlyContinue) {
    throw "Prison Architect is running. Quit the game first (the DLL is locked while it runs)."
}

$dll = Join-Path $root "native\bin\GLU32.dll"
$target = Join-Path $GameDir "GLU32.dll"
if (Test-Path $target) { Copy-Item $target "$target.bak" -Force }
Copy-Item $dll $target -Force
Write-Host "DLL:  $target"

$mods = Join-Path $env:LOCALAPPDATA "Introversion\Prison Architect\mods\ai_bridge"
New-Item -ItemType Directory -Force (Join-Path $mods "data") | Out-Null
Copy-Item (Join-Path $root "mod\ai_bridge\manifest.txt") $mods -Force
Copy-Item (Join-Path $root "mod\ai_bridge\data\world.lua") (Join-Path $mods "data") -Force
Write-Host "Mod:  $mods"
Write-Host "Start the game, make sure 'AI Bridge' is enabled in Extras > Mods, and load a prison."
Write-Host "Uninstall: delete $target"
