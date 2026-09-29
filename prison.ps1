<#
 prison.ps1 - the EASY front door to the Prison Architect agent bridge.

 One verb per call, a few lines of plain text back, and a HINT line when something fails.

   .\prison.ps1 help            # list verbs
   .\prison.ps1 help room       # details for one verb
   .\prison.ps1 status          # money, clock, prisoners, staff, construction
   .\prison.ps1 next            # what the prison needs next, as commands

 It runs `pa-agent play <verb> ...` from this folder's .venv. Works in Windows PowerShell 5.1 and PowerShell 7.
#>
$exe = Join-Path $PSScriptRoot ".venv\Scripts\pa-agent.exe"
if (-not (Test-Path $exe)) {
    Write-Output "ERROR: $exe not found. Install first: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ."
    exit 2
}
if ($args.Count -eq 0) { & $exe play help; exit $LASTEXITCODE }
& $exe play @args
exit $LASTEXITCODE
