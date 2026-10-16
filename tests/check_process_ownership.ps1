#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'process-utils.ps1')
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
$launcherPath = Join-Path $repoRoot 'pwm_local.py'
$own = [pscustomobject]@{ ExecutablePath = $pythonPath; CommandLine = ('"{0}" "{1}" api' -f $pythonPath, $launcherPath) }
if (-not (Test-BridgeProcess $own)) { throw 'Current installation was not recognized.' }
$basePython = & $pythonPath -c 'import sys; print(sys._base_executable)'
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the virtual environment base interpreter.' }
$redirected = [pscustomobject]@{ ExecutablePath = $basePython.Trim(); CommandLine = $own.CommandLine }
if (-not (Test-BridgeProcess $redirected)) { throw 'Windows virtual environment redirected child was not recognized.' }
$wrongPython = [pscustomobject]@{ ExecutablePath = 'C:\other\python.exe'; CommandLine = $own.CommandLine }
if (Test-BridgeProcess $wrongPython) { throw 'Unrelated interpreter was accepted.' }
$wrongLauncher = [pscustomobject]@{ ExecutablePath = $pythonPath; CommandLine = ('"{0}" "{1}.other" api' -f $pythonPath, $launcherPath) }
if (Test-BridgeProcess $wrongLauncher) { throw 'Launcher prefix collision was accepted.' }
if (Test-BridgeProcess $null) { throw 'Missing process was accepted.' }
Write-Output 'Process ownership checks passed; no processes were started or stopped.'
