#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\process-utils.ps1"
if ($env:PWM_PRIVATE_DIR) { $stateDir = $env:PWM_PRIVATE_DIR } else { $stateDir = Join-Path $PSScriptRoot 'private' }
foreach ($required in @('session.token', 'api-key.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $stateDir $required))) {
        throw 'Run setup.ps1 and login.ps1 before starting the proxy.'
    }
}
$listeners = @(Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if (-not (Test-BridgeProcess $process)) { throw 'Port 18080 belongs to another installation or application.' }
    }
    Write-Output 'This installation is already running.'
    exit 0
}
New-Item -ItemType Directory -Path "$PSScriptRoot\logs" -Force | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$proxyArgs = @(('"{0}"' -f "$PSScriptRoot\pwm_local.py"), 'api', '--host', '127.0.0.1', '--port', '18080', '--model', 'claude-opus-5-5')
$proxyProcess = Start-Process -FilePath "$PSScriptRoot\.venv\Scripts\python.exe" -ArgumentList $proxyArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\logs\proxy.stdout.log" -RedirectStandardError "$PSScriptRoot\logs\proxy.stderr.log" -PassThru
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($proxyProcess.HasExited) { throw 'Proxy exited. Check logs/proxy.stderr.log.' }
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:18080/health' -TimeoutSec 2 -NoProxy
        if ($health) { Write-Output 'Proxy started: http://127.0.0.1:18080'; exit 0 }
    } catch {}
}
throw 'Startup timed out. Check logs/proxy.stderr.log.'
