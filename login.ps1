#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\initialize.py"
if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize local state.' }
Write-Host 'Log in locally with your Perplexity email and verification code.'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\pwm_local.py" login
if ($LASTEXITCODE -ne 0) { throw 'Login failed. Do not share your code or session token.' }
