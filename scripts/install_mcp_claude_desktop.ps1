# Adds the prison-architect MCP server to the Claude desktop app config,
# keeping any existing settings. Backs up the old file first.
$ErrorActionPreference = "Stop"
$exe = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\pa-agent.exe"
if (-not (Test-Path $exe)) { throw "Not found: $exe (run: .\.venv\Scripts\python.exe -m pip install -e .)" }

$candidates = @(
    (Join-Path $env:APPDATA "Claude\claude_desktop_config.json")
) + (Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json" })
$config = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $config) { $config = $candidates[0]; New-Item -ItemType Directory -Force (Split-Path $config) | Out-Null }

$data = [pscustomobject]@{}
if ((Test-Path $config) -and (Get-Content $config -Raw).Trim()) {
    Copy-Item $config "$config.bak" -Force
    $data = Get-Content $config -Raw | ConvertFrom-Json
}
if (-not $data.PSObject.Properties["mcpServers"]) {
    $data | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
}
$entry = [pscustomobject]@{ command = $exe; args = @("mcp") }
if ($data.mcpServers.PSObject.Properties["prison-architect"]) { $data.mcpServers."prison-architect" = $entry }
else { $data.mcpServers | Add-Member -NotePropertyName "prison-architect" -NotePropertyValue $entry }

$json = $data | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($config, $json, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Added prison-architect to $config"
Write-Host "Now fully quit Claude (system tray > Quit) and reopen it."
