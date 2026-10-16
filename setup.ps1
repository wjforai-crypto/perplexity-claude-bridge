#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$uv = Get-Command uv -ErrorAction Stop
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & $uv.Source venv --python 3.12 (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python 3.12 environment.' }
}
& $uv.Source pip install --python $python -r (Join-Path $PSScriptRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python (Join-Path $PSScriptRoot 'initialize.py')
if ($LASTEXITCODE -ne 0) { throw 'Could not initialize local state.' }
Write-Output 'Installed. Next: pwsh -File .\login.ps1'
