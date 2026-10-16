#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\process-utils.ps1"
$listeners = @(Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue)
$ownedIds = @()
foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if (-not (Test-BridgeProcess $process)) { throw 'Port belongs to another installation; nothing was stopped.' }
    $ownedIds += $listener.OwningProcess
}
foreach ($processId in ($ownedIds | Select-Object -Unique)) {
    Stop-Process -Id $processId
    Write-Output 'This installation was stopped.'
}
